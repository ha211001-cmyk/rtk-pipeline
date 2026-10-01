#!/usr/bin/env python3
"""
tcp2serial.py — Robust TCP-to-Serial Bridge

Listens on a TCP port and forwards all received data to a serial device.
Designed for RTCM3 injection into F9P UART2 on Raspberry Pi.

Features:
- Auto-reconnect: re-enters accept() when a TCP client disconnects
- Health check: if no data flows for --health-timeout seconds, drops the
  stale connection and re-listens
- Activity watchdog: periodic stats logging (packets/bytes per interval)
- Graceful shutdown on SIGTERM/SIGINT (systemd-friendly)
- Timestamped logging for all connect/disconnect/reconnect events

Usage:
  python tcp2serial.py 0.0.0.0 2102 /dev/ttyAMA4
  python tcp2serial.py 0.0.0.0 2102 /dev/ttyAMA4 --baudrate 115200 --health-timeout 30
"""

import argparse
import logging
import signal
import socket
import sys
import time
from dataclasses import dataclass
from typing import Optional

import serial

logger = logging.getLogger("tcp2serial")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
RECV_BUFFER = 4096
DEFAULT_BAUDRATE = 115200
DEFAULT_HEALTH_TIMEOUT = 30.0  # seconds
DEFAULT_LISTEN_BACKLOG = 1
DEFAULT_STATS_INTERVAL = 60.0  # seconds
DEFAULT_TCP_TIMEOUT = 5.0  # seconds
DEFAULT_SERIAL_TIMEOUT = 1.0  # seconds


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclass
class BridgeStats:
    """Runtime statistics for the bridge."""

    total_packets: int = 0
    total_bytes: int = 0
    last_data_time: float = 0.0
    last_stats_time: float = 0.0
    connections: int = 0
    reconnects: int = 0
    health_resets: int = 0


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------
class Tcp2SerialBridge:
    """TCP server that forwards all received bytes to a serial port.

    Only one TCP client is served at a time.  When the client disconnects
    (or the health-check timer fires) the server goes back to ``accept()``.
    """

    def __init__(
        self,
        bind_host: str,
        bind_port: int,
        serial_device: str,
        baudrate: int = DEFAULT_BAUDRATE,
        health_timeout_sec: float = DEFAULT_HEALTH_TIMEOUT,
        tcp_timeout_sec: float = DEFAULT_TCP_TIMEOUT,
        serial_timeout_sec: float = DEFAULT_SERIAL_TIMEOUT,
        stats_interval_sec: float = DEFAULT_STATS_INTERVAL,
    ) -> None:
        self.bind_host = bind_host
        self.bind_port = bind_port
        self.serial_device = serial_device
        self.baudrate = baudrate
        self.health_timeout = health_timeout_sec
        self.tcp_timeout = tcp_timeout_sec
        self.serial_timeout = serial_timeout_sec
        self.stats_interval = stats_interval_sec

        self.stats = BridgeStats()
        self._server_sock: Optional[socket.socket] = None
        self._shutdown_requested = False

    def stop(self) -> None:
        """GCS 統合用の停止要求。accept() を解除して run_forever を終了させる。"""
        self._shutdown_requested = True
        self._close_server_socket()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def run_forever(self) -> None:
        """Blocking main loop: bind → accept loop → bridge → repeat."""
        self._setup_signal_handlers()

        logger.info(
            "tcp2serial starting: tcp=%s:%d → serial=%s @ %d bps",
            self.bind_host,
            self.bind_port,
            self.serial_device,
            self.baudrate,
        )
        logger.info(
            "health_timeout=%.0fs  tcp_timeout=%.0fs  serial_timeout=%.0fs  stats_interval=%.0fs",
            self.health_timeout,
            self.tcp_timeout,
            self.serial_timeout,
            self.stats_interval,
        )

        # Open serial once – keep the device handle across reconnects so we
        # don't churn /dev/ttyAMA4.
        ser = self._open_serial()

        try:
            self._server_sock = self._create_server_socket()

            while not self._shutdown_requested:
                client_sock, client_addr = self._accept_client()
                if client_sock is None:
                    break  # shutdown requested during accept

                self.stats.connections += 1
                logger.info(
                    "[CONNECT] client %s:%d (connection #%d)",
                    client_addr[0],
                    client_addr[1],
                    self.stats.connections,
                )

                self._bridge_loop(client_sock, client_addr, ser)

                # If we get here the client disconnected or health-check fired.
                if self._shutdown_requested:
                    logger.info("[SHUTDOWN] bridge loop exited, stopping")
                else:
                    self.stats.reconnects += 1
                    logger.info(
                        "[DISCONNECT] client %s:%d gone (reconnects: %d)",
                        client_addr[0],
                        client_addr[1],
                        self.stats.reconnects,
                    )
        finally:
            self._close_server_socket()
            self._close_serial(ser)

        logger.info(
            "tcp2serial stopped: connections=%d  reconnects=%d  health_resets=%d  "
            "total_packets=%d  total_bytes=%d",
            self.stats.connections,
            self.stats.reconnects,
            self.stats.health_resets,
            self.stats.total_packets,
            self.stats.total_bytes,
        )

    # ------------------------------------------------------------------
    # Serial
    # ------------------------------------------------------------------
    def _open_serial(self) -> serial.Serial:
        """Open the serial device and return the handle."""
        ser = serial.Serial(
            port=self.serial_device,
            baudrate=self.baudrate,
            timeout=self.serial_timeout,
        )
        ser.reset_output_buffer()
        logger.info(
            "[SERIAL] opened %s @ %d bps (timeout=%.1fs)",
            self.serial_device,
            self.baudrate,
            self.serial_timeout,
        )
        return ser

    @staticmethod
    def _close_serial(ser: serial.Serial) -> None:
        try:
            ser.close()
            logger.info("[SERIAL] closed")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # TCP server socket
    # ------------------------------------------------------------------
    def _create_server_socket(self) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(2.0)  # allow periodic shutdown checks
        sock.bind((self.bind_host, self.bind_port))
        sock.listen(DEFAULT_LISTEN_BACKLOG)
        logger.info("[LISTEN] tcp://%s:%d", self.bind_host, self.bind_port)
        return sock

    def _close_server_socket(self) -> None:
        if self._server_sock is not None:
            try:
                self._server_sock.close()
            except Exception:
                pass
            self._server_sock = None

    def _accept_client(self) -> tuple[Optional[socket.socket], tuple[str, int]]:
        """Block until a client connects or shutdown is requested.

        Returns (None, ("", 0)) when shutting down.
        """
        while not self._shutdown_requested:
            try:
                client_sock, addr = self._server_sock.accept()  # type: ignore[union-attr]
                client_sock.settimeout(self.tcp_timeout)
                return client_sock, addr
            except socket.timeout:
                continue  # just a poll interval for shutdown flag
            except Exception as exc:
                if not self._shutdown_requested:
                    logger.warning("[ACCEPT] error: %s (retrying…)", exc)
                    time.sleep(1)
        return None, ("", 0)

    # ------------------------------------------------------------------
    # Bridge loop (per-client)
    # ------------------------------------------------------------------
    def _bridge_loop(
        self,
        client_sock: socket.socket,
        client_addr: tuple[str, int],
        ser: serial.Serial,
    ) -> None:
        """Forward TCP → serial until the client disconnects or health fires."""
        self.stats.last_data_time = time.time()
        self.stats.last_stats_time = time.time()

        try:
            while not self._shutdown_requested:
                # --- read from TCP ---
                try:
                    data = client_sock.recv(RECV_BUFFER)
                except socket.timeout:
                    data = b""

                if data:
                    self._on_data_received(data, ser)
                elif self._is_health_timeout():
                    # No data for too long → force reconnect
                    self.stats.health_resets += 1
                    logger.warning(
                        "[HEALTH] no data for %.0fs, forcing reconnect (health_resets: %d)",
                        self.health_timeout,
                        self.stats.health_resets,
                    )
                    return

                # --- periodic stats ---
                self._maybe_log_stats()
        except (ConnectionError, OSError) as exc:
            logger.warning("[CLIENT] connection error: %s", exc)
        finally:
            try:
                client_sock.close()
            except Exception:
                pass

    def _on_data_received(self, data: bytes, ser: serial.Serial) -> None:
        """Write received TCP data to serial and update stats."""
        ser.write(data)
        ser.flush()

        now = time.time()
        self.stats.last_data_time = now
        self.stats.total_packets += 1
        self.stats.total_bytes += len(data)

    def _is_health_timeout(self) -> bool:
        """Return True when the health-check interval has elapsed."""
        if self.health_timeout <= 0:
            return False
        elapsed = time.time() - self.stats.last_data_time
        return elapsed >= self.health_timeout

    def _maybe_log_stats(self) -> None:
        now = time.time()
        if now - self.stats.last_stats_time < self.stats_interval:
            return
        self.stats.last_stats_time = now

        dt = now - self.stats.last_data_time
        logger.info(
            "[STATS] packets=%d  bytes=%d  last_data=%.0fs ago",
            self.stats.total_packets,
            self.stats.total_bytes,
            dt,
        )

    # ------------------------------------------------------------------
    # Signal handling (systemd-friendly)
    # ------------------------------------------------------------------
    def _setup_signal_handlers(self) -> None:
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, self._on_shutdown_signal)
            except ValueError:
                # Not in main thread – signals are set up early so this
                # shouldn't happen, but be safe.
                pass

    def _on_shutdown_signal(self, signum: int, _frame) -> None:
        sig_name = signal.Signals(signum).name
        logger.info("[SIGNAL] received %s, shutting down gracefully…", sig_name)
        self._shutdown_requested = True
        # Close the server socket so accept() unblocks
        self._close_server_socket()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def load_bridge_config(path: str) -> dict:
    """設定ファイル（YAML）から tcp2serial の設定を読み込む。

    設定ファイルベース起動用（Phase 0 統合計画 §4.4）。キー:
      bind_host / bind_port / serial_device / baudrate /
      health_timeout_sec / tcp_timeout_sec / serial_timeout_sec / stats_interval_sec
    """
    try:
        import yaml
    except ImportError:
        raise ImportError("PyYAML が必要です。 `pip install pyyaml` でインストールしてください。")

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return raw


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Robust TCP-to-Serial bridge with auto-reconnect and health check",
    )
    parser.add_argument(
        "bind_host",
        nargs="?",
        help="TCP listen address (e.g. 0.0.0.0). Required unless --config is used.",
    )
    parser.add_argument(
        "bind_port",
        nargs="?",
        type=int,
        help="TCP listen port (e.g. 2102). Required unless --config is used.",
    )
    parser.add_argument(
        "serial_device",
        nargs="?",
        help="Serial device path (e.g. /dev/ttyAMA4). Required unless --config is used.",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="YAML 設定ファイルパス（相対パスは gcs/config/ 基準で解決）。"
             "指定時は位置引数を省略できる。",
    )
    parser.add_argument(
        "--baudrate",
        type=int,
        default=DEFAULT_BAUDRATE,
        help=f"Serial baud rate (default: {DEFAULT_BAUDRATE})",
    )
    parser.add_argument(
        "--health-timeout",
        type=float,
        default=DEFAULT_HEALTH_TIMEOUT,
        help=f"Max idle seconds before forcing reconnect (default: {DEFAULT_HEALTH_TIMEOUT})",
    )
    parser.add_argument(
        "--tcp-timeout",
        type=float,
        default=DEFAULT_TCP_TIMEOUT,
        help=f"TCP recv timeout in seconds (default: {DEFAULT_TCP_TIMEOUT})",
    )
    parser.add_argument(
        "--serial-timeout",
        type=float,
        default=DEFAULT_SERIAL_TIMEOUT,
        help=f"Serial write timeout in seconds (default: {DEFAULT_SERIAL_TIMEOUT})",
    )
    parser.add_argument(
        "--stats-interval",
        type=float,
        default=DEFAULT_STATS_INTERVAL,
        help=f"Stats log interval in seconds (default: {DEFAULT_STATS_INTERVAL})",
    )
    return parser.parse_args()


def _resolve_config_path(path: str) -> str:
    from pathlib import Path

    candidate = Path(path)
    if candidate.is_absolute():
        return str(candidate)
    if candidate.exists():
        return str(candidate)
    default_dir = Path(__file__).resolve().parent.parent / "config"
    return str(default_dir / path)


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def main() -> None:
    args = parse_args()

    if args.config:
        cfg = load_bridge_config(_resolve_config_path(args.config))
        bind_host = cfg.get("bind_host") or args.bind_host
        bind_port = cfg.get("bind_port") or args.bind_port
        serial_device = cfg.get("serial_device") or args.serial_device
        baudrate = cfg.get("baudrate", args.baudrate)
        health_timeout = cfg.get("health_timeout_sec", args.health_timeout)
        tcp_timeout = cfg.get("tcp_timeout_sec", args.tcp_timeout)
        serial_timeout = cfg.get("serial_timeout_sec", args.serial_timeout)
        stats_interval = cfg.get("stats_interval_sec", args.stats_interval)
    else:
        bind_host = args.bind_host
        bind_port = args.bind_port
        serial_device = args.serial_device
        baudrate = args.baudrate
        health_timeout = args.health_timeout
        tcp_timeout = args.tcp_timeout
        serial_timeout = args.serial_timeout
        stats_interval = args.stats_interval

    if not bind_host or bind_port is None or not serial_device:
        parser_error = (
            "bind_host / bind_port / serial_device が必要です"
            "（位置引数 3 つ、または --config で指定）"
        )
        print(f"ERROR: {parser_error}", file=sys.stderr)
        sys.exit(2)

    configure_logging()

    bridge = Tcp2SerialBridge(
        bind_host=bind_host,
        bind_port=int(bind_port),
        serial_device=serial_device,
        baudrate=int(baudrate),
        health_timeout_sec=float(health_timeout),
        tcp_timeout_sec=float(tcp_timeout),
        serial_timeout_sec=float(serial_timeout),
        stats_interval_sec=float(stats_interval),
    )
    bridge.run_forever()


if __name__ == "__main__":
    main()
