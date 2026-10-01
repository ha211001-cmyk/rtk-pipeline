import argparse
import base64
import csv
import logging
import os
import socket
import time
from dataclasses import dataclass

import serial
import yaml


@dataclass
class SourceConfig:
    source_type: str
    host: str
    port: int
    mountpoint: str
    user_agent: str
    username: str
    password: str
    serial_port: str
    baudrate: int
    timeout_sec: float


@dataclass
class ForwardConfig:
    forward_type: str
    host: str
    port: int
    serial_port: str
    serial_baudrate: int


@dataclass
class RetryConfig:
    reconnect_sec: float


@dataclass
class LogConfig:
    level: str
    stats_interval_sec: int


@dataclass
class ServiceConfig:
    source: SourceConfig
    forward: ForwardConfig
    retry: RetryConfig
    log: LogConfig


class RtcmForwarderService:
    INJECTION_LOG_DIR = "logs"
    INJECTION_LOG_FILE = os.path.join(INJECTION_LOG_DIR, "rtcm_injection.log")

    def __init__(self, config: ServiceConfig):
        self.config = config
        self.logger = logging.getLogger("rtk_forwarder")
        self.total_packets = 0
        self.total_bytes = 0
        self.last_stats_time = time.time()
        # レート計算用の前回値
        self._last_packets = 0
        self._last_bytes = 0
        self._errors = 0
        self._csv_file = None
        self._csv_writer = None
        # GCS（OperationManager）からの停止要求フラグ
        self._stop_requested = False

    def stop(self) -> None:
        """GCS 統合用の停止要求。run_forever のループを抜けさせる。"""
        self._stop_requested = True
        self.logger.info("rtk_forwarder: stop requested")

    def _init_injection_log(self) -> None:
        """RTCM注入ログのCSVファイルを初期化（ヘッダ行を書き込み）"""
        os.makedirs(self.INJECTION_LOG_DIR, exist_ok=True)
        self._csv_file = open(self.INJECTION_LOG_FILE, "a", newline="")
        self._csv_writer = csv.writer(self._csv_file)
        # ファイルが空ならヘッダを書き込む
        if os.path.getsize(self.INJECTION_LOG_FILE) == 0:
            self._csv_writer.writerow([
                "timestamp",
                "frame_count",
                "cumulative_bytes",
                "frames_per_min",
                "bytes_per_minute",
                "errors",
            ])
            self._csv_file.flush()
        self.logger.info("RTCM injection log opened: %s", self.INJECTION_LOG_FILE)

    def _close_injection_log(self) -> None:
        """RTCM注入ログファイルを閉じる"""
        if self._csv_file is not None:
            try:
                self._csv_file.close()
            except Exception:
                pass
            self._csv_file = None
            self._csv_writer = None

    def run_forever(self) -> None:
        self._init_injection_log()
        fwd = self.config.forward
        if fwd.forward_type == "serial":
            dest = f"{fwd.serial_port}@{fwd.serial_baudrate}bps"
        else:
            dest = f"{fwd.host}:{fwd.port}"
        self.logger.info(
            "RTK forwarder start: source=%s, forward.type=%s, destination=%s",
            self.config.source.source_type,
            fwd.forward_type,
            dest,
        )
        while not self._stop_requested:
            try:
                if self.config.source.source_type == "ntrip":
                    self._run_ntrip_once()
                elif self.config.source.source_type == "serial":
                    self._run_serial_once()
                elif self.config.source.source_type == "tcp":
                    self._run_tcp_once()
                else:
                    raise ValueError(
                        "source.source_type must be 'tcp', 'ntrip' or 'serial'"
                    )
            except KeyboardInterrupt:
                self.logger.info("Stopped by user")
                break
            except Exception as exc:
                self.logger.exception("Source loop error: %s", exc)

            self.logger.info(
                "Reconnecting in %.1f sec", self.config.retry.reconnect_sec
            )
            time.sleep(self.config.retry.reconnect_sec)

    # ------------------------------------------------------------------
    # Forward output helpers
    # ------------------------------------------------------------------
    def _open_forward(self):
        """Open the forward output channel based on forward.forward_type."""
        fwd = self.config.forward
        if fwd.forward_type == "serial":
            ser = serial.Serial(
                port=fwd.serial_port,
                baudrate=fwd.serial_baudrate,
                timeout=1.0,
            )
            ser.reset_output_buffer()
            self.logger.info(
                "Forward serial port opened: %s @ %s bps",
                fwd.serial_port,
                fwd.serial_baudrate,
            )
            return ser
        else:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.logger.info(
                "Forward UDP socket ready: %s:%s",
                fwd.host,
                fwd.port,
            )
            return sock

    @staticmethod
    def _close_forward(fwd_obj) -> None:
        """Close the forward output channel."""
        try:
            fwd_obj.close()
        except Exception:
            pass

    def _forward_chunk(self, fwd_obj, chunk: bytes) -> None:
        """Write an RTCM chunk to the forward destination."""
        fwd_cfg = self.config.forward
        if fwd_cfg.forward_type == "serial":
            fwd_obj.write(chunk)
            fwd_obj.flush()
        else:
            fwd_obj.sendto(chunk, (fwd_cfg.host, fwd_cfg.port))
        self._count(chunk)

    # ------------------------------------------------------------------
    # Source loops
    # ------------------------------------------------------------------
    def _run_ntrip_once(self) -> None:
        src = self.config.source
        fwd_obj = self._open_forward()
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as ntrip_sock:
                ntrip_sock.settimeout(src.timeout_sec)
                ntrip_sock.connect((src.host, src.port))
                ntrip_sock.sendall(self._build_ntrip_request())
                self.logger.info(
                    "Connected to NTRIP caster: %s:%s / %s",
                    src.host,
                    src.port,
                    src.mountpoint,
                )

                first_chunk = ntrip_sock.recv(4096)
                if not first_chunk:
                    raise ConnectionError("NTRIP connection closed on initial response")

                header, payload = self._split_header_payload(first_chunk)
                self._check_ntrip_response(header)

                if payload:
                    self._forward_chunk(fwd_obj, payload)

                while True:
                    chunk = ntrip_sock.recv(4096)
                    if not chunk:
                        raise ConnectionError("NTRIP stream closed by server")
                    self._forward_chunk(fwd_obj, chunk)
        finally:
            self._close_forward(fwd_obj)

    def _run_serial_once(self) -> None:
        src = self.config.source
        fwd_obj = self._open_forward()
        try:
            with serial.Serial(src.serial_port, src.baudrate, timeout=src.timeout_sec) as ser:
                self.logger.info(
                    "Connected to serial source: %s (%sbps)",
                    src.serial_port,
                    src.baudrate,
                )
                while True:
                    # RTCM v3 preamble 0xD3 を探す
                    b0 = ser.read(1)
                    if not b0:
                        continue
                    if b0 != b"\xd3":
                        continue

                    header_tail = ser.read(2)
                    if len(header_tail) < 2:
                        continue

                    payload_len = ((header_tail[0] & 0x03) << 8) | header_tail[1]
                    payload_and_crc = ser.read(payload_len + 3)
                    if len(payload_and_crc) < payload_len + 3:
                        continue

                    frame = b0 + header_tail + payload_and_crc
                    self._forward_chunk(fwd_obj, frame)
        finally:
            self._close_forward(fwd_obj)

    def _run_tcp_once(self) -> None:
        """Raw TCP source: connect directly and forward RTCM stream (no NTRIP handshake).

        rtk_base_station_v2.py provides a raw TCP stream (not NTRIP), so we
        simply connect and stream bytes without any HTTP/NTRIP negotiation.
        Added per: docs/04-testing/2026-07-21_rtk_failure_analysis.md Section 9.2
        """
        src = self.config.source
        fwd_obj = self._open_forward()
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp_sock:
                tcp_sock.settimeout(src.timeout_sec)
                tcp_sock.connect((src.host, src.port))
                self.logger.info(
                    "Connected to raw TCP source: %s:%s",
                    src.host,
                    src.port,
                )

                buffer = bytearray()
                send_buf = bytearray()      # batch buffer for serial writes
                last_flush = time.monotonic()
                BATCH_BYTES = 1024           # flush when >= 1KB accumulated
                BATCH_INTERVAL = 0.5         # flush at least every 0.5s

                while True:
                    try:
                        chunk = tcp_sock.recv(4096)
                    except socket.timeout:
                        # Flush batch if timeout expired
                        if send_buf and time.monotonic() - last_flush >= BATCH_INTERVAL:
                            fwd_obj.write(bytes(send_buf))
                            fwd_obj.flush()
                            self._count(bytes(send_buf))
                            send_buf.clear()
                            last_flush = time.monotonic()
                        continue
                    if not chunk:
                        # Flush remaining batch before raising
                        if send_buf:
                            fwd_obj.write(bytes(send_buf))
                            fwd_obj.flush()
                            self._count(bytes(send_buf))
                        raise ConnectionError(
                            "TCP stream closed by server"
                        )
                    buffer.extend(chunk)

                    # Extract complete RTCM v3 frames (preamble 0xD3)
                    while len(buffer) >= 6:
                        if buffer[0] != 0xD3:
                            buffer.pop(0)
                            continue
                        reserved = buffer[1] >> 6
                        frame_len = ((buffer[1] & 0x03) << 8) | buffer[2]
                        total_len = 6 + frame_len

                        if len(buffer) < total_len:
                            break

                        frame = bytes(buffer[:total_len])
                        buffer = buffer[total_len:]
                        send_buf.extend(frame)

                        # Batch flush: write when buffer is full enough
                        if len(send_buf) >= BATCH_BYTES:
                            fwd_obj.write(bytes(send_buf))
                            fwd_obj.flush()
                            self._count(bytes(send_buf))
                            send_buf.clear()
                            last_flush = time.monotonic()
        finally:
            self._close_forward(fwd_obj)

    def _build_ntrip_request(self) -> bytes:
        src = self.config.source
        lines = [
            f"GET /{src.mountpoint} HTTP/1.0",
            f"User-Agent: {src.user_agent}",
        ]
        if src.username and src.password:
            token = base64.b64encode(
                f"{src.username}:{src.password}".encode("utf-8")
            ).decode("ascii")
            lines.append(f"Authorization: Basic {token}")
        request = "\r\n".join(lines) + "\r\n\r\n"
        return request.encode("ascii")

    @staticmethod
    def _split_header_payload(chunk: bytes) -> tuple[bytes, bytes]:
        if b"\r\n\r\n" in chunk:
            return chunk.split(b"\r\n\r\n", 1)
        if b"\n\n" in chunk:
            return chunk.split(b"\n\n", 1)
        return chunk, b""

    def _check_ntrip_response(self, header: bytes) -> None:
        text = header.decode(errors="ignore")
        preview = text[:200].replace("\r", " ").replace("\n", " ")
        self.logger.info("NTRIP response: %s", preview)
        if "200" not in text:
            raise ConnectionError(f"NTRIP rejected: {preview}")

    def _count(self, data: bytes) -> None:
        self.total_packets += 1
        self.total_bytes += len(data)

        now = time.time()
        interval = self.config.log.stats_interval_sec
        if now - self.last_stats_time >= interval:
            elapsed = now - self.last_stats_time
            self.last_stats_time = now

            # レート計算（frames/min, bytes/min）
            delta_packets = self.total_packets - self._last_packets
            delta_bytes = self.total_bytes - self._last_bytes
            frames_per_min = (delta_packets / elapsed) * 60.0 if elapsed > 0 else 0.0
            bytes_per_minute = (delta_bytes / elapsed) * 60.0 if elapsed > 0 else 0.0

            self._last_packets = self.total_packets
            self._last_bytes = self.total_bytes

            self.logger.info(
                "Forward stats: packets=%s, bytes=%s",
                self.total_packets,
                self.total_bytes,
            )

            # CSV注入ログ出力
            if self._csv_writer is not None:
                timestamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now))
                self._csv_writer.writerow([
                    timestamp,
                    self.total_packets,
                    self.total_bytes,
                    f"{frames_per_min:.1f}",
                    f"{bytes_per_minute:.1f}",
                    self._errors,
                ])
                self._csv_file.flush()


def _expand_env(value):
    """文字列内の ${ENV_VAR} を環境変数で展開する（シークレットのハードコード回避）。

    認証情報（username / password など）は YAML に平文で書かず、
    ``${NTRIP_USER}`` / ``${NTRIP_PASSWORD}`` の形式で環境変数を参照する。
    環境変数が未設定の場合は空文字になる（NTRIP ベーシック認証を送らない）。
    """
    if not isinstance(value, str):
        return value
    import re as _re

    def _sub(match):
        return os.environ.get(match.group(1), "")

    return _re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", _sub, value)


def load_config(path: str) -> ServiceConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    source_raw = raw.get("source", {}) or {}
    forward_raw = raw.get("forward", {}) or {}
    retry_raw = raw.get("retry", {}) or {}
    log_raw = raw.get("log", {}) or {}

    source = SourceConfig(
        source_type=source_raw.get("source_type", "ntrip"),
        host=_expand_env(source_raw.get("host", "127.0.0.1")),
        port=int(_expand_env(source_raw.get("port", 2101))),
        mountpoint=_expand_env(source_raw.get("mountpoint", "UBLOX_EVK_F9P")),
        user_agent=_expand_env(source_raw.get("user_agent", "NTRIP PythonClient")),
        username=_expand_env(source_raw.get("username", "")),
        password=_expand_env(source_raw.get("password", "")),
        serial_port=_expand_env(source_raw.get("serial_port", "COM8")),
        baudrate=int(_expand_env(source_raw.get("baudrate", 115200))),
        timeout_sec=float(_expand_env(source_raw.get("timeout_sec", 2.0))),
    )
    forward = ForwardConfig(
        forward_type=forward_raw.get("type", "udp"),
        host=forward_raw.get("host", "127.0.0.1"),
        port=int(forward_raw.get("port", 50010)),
        serial_port=forward_raw.get("serial_port", "/dev/ttyAMA4"),
        serial_baudrate=int(forward_raw.get("baudrate", 115200)),
    )
    retry = RetryConfig(reconnect_sec=float(retry_raw.get("reconnect_sec", 3.0)))
    log = LogConfig(
        level=str(log_raw.get("level", "INFO")).upper(),
        stats_interval_sec=int(log_raw.get("stats_interval_sec", 5)),
    )
    return ServiceConfig(source=source, forward=forward, retry=retry, log=log)


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def _resolve_config_path(path: str) -> str:
    """設定ファイルパスを解決する（相対パスは gcs/config/ 基準で補完）。"""
    from pathlib import Path

    candidate = Path(path)
    if candidate.is_absolute():
        return str(candidate)
    # 現在の作業ディレクトリから見つかればそれを優先
    if candidate.exists():
        return str(candidate)
    # 本モジュール基準（gcs/rtk_tools/ → gcs/config/）
    default_dir = Path(__file__).resolve().parent.parent / "config"
    resolved = default_dir / path
    return str(resolved)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RTK/RTCM転送サービス（統合版）"
    )
    parser.add_argument(
        "--config",
        default="rtk_forwarder.yml",
        help="設定ファイルパス（相対パスは gcs/config/ 基準で解決）",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(_resolve_config_path(args.config))
    configure_logging(config.log.level)

    service = RtcmForwarderService(config)
    service.run_forever()


if __name__ == "__main__":
    main()
