#!/usr/bin/env python3
"""sources.py — GCS 統合用データソース（MAVLink テレメトリ受信 + 合成ヘルパー）

本番アーキテクチャ（DroneCAN + MAVLink + UDP）向けの主役クラス:

- ``MavlinkTelemetryReader`` : pymavlink でローバー（Raspberry Pi / MAVProxy /
  ArduPilot）から UDP で届く MAVLink パケットを待ち受け、以下を抽出する。
    * GPS_RAW_INT  : fix_type（0..6）・衛星数・緯度経度高度・EPH/EPV
    * HEARTBEAT    : フライトモード・ARM 状態・機体種別（MAV_TYPE）
    * SYS_STATUS   : バッテリー電圧・電流・残量
  複数台対応のため、状態は ``system_id``（機体ID）をキーとする辞書で保持する。

廃止 / 非推奨:
- ``RoverUbxReader`` : 旧来の UBX シリアル/TCP 直読。本番構成では使用しない。
  既存コード（gcs/preflight 等）との後方互換のため残すが、``DeprecationWarning``
  を発する。新規コードは ``MavlinkTelemetryReader`` を使用すること。
- ``BaseRtcmReader`` : 基地局 RTCM の USB 直読。RTCM の UDP 配信は
  ``gcs.integration.rtcm_caster.RtcmCaster`` に置き換える（後方互換のため残置）。

合成ヘルパー（``make_ubx_rxm_rtcm`` / ``make_rtcm3_frame``）と、旧 Phase1 自己検証用の
``SyntheticRoverSource`` / ``SyntheticBaseSource`` / ``FakeF9pStream`` /
``run_phase1_offline`` は後方互換のため末尾に保持する。
"""

from __future__ import annotations

import glob
import struct
import sys
import threading
import time
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional

# 実行位置に依存しない import パス
_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "archive" / "udp"):
    if _p.is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from gcs.rtcm_monitor import (  # noqa: E402
    ubx_checksum,
    rtcm3_crc24q,
    UBX_RXM_RTCM_CLASS,
    UBX_RXM_RTCM_ID,
)
from gcs.fix_metrics import ubx_to_fix_type  # noqa: E402
from gcs.app.mavlink.telemetry import (  # noqa: E402
    VehicleStateStore,
    mav_type_name,
    decode_flight_mode,
)

try:
    from pymavlink import mavutil
except ImportError:  # pragma: no cover - pymavlink 未導入環境
    mavutil = None


# ---------------------------------------------------------------------------
# MAVLink 定数 / ヘルパー
# ---------------------------------------------------------------------------
# メッセージ → 機体状態 の抽出ロジック（mav_type_name / decode_flight_mode /
# 機体状態の初期化）は gcs.app.mavlink.telemetry へ一本化した。
# 本モジュールは後方互換のため同シンボルを再エクスポートする（下記 import 参照）。


# ---------------------------------------------------------------------------
# ポート自動検出（既存 archive/udp/base_ubx_logger.py を再利用。無ければローカル実装）
# ---------------------------------------------------------------------------
def auto_detect_port() -> Optional[str]:
    try:
        from base_ubx_logger import auto_detect_port as _detect  # noqa: PLC0415
        port = _detect()
        if port:
            return port
    except Exception:  # noqa: BLE001
        pass
    for pat in ("/dev/cu.usbmodem*", "/dev/tty.usbmodem*",
                "/dev/ttyACM*", "/dev/ttyUSB*"):
        m = sorted(glob.glob(pat))
        if m:
            return m[0]
    return None


# ---------------------------------------------------------------------------
# 合成フレーム生成（自己検証用。rtcm_monitor のチェックサム関数を再利用）
# ---------------------------------------------------------------------------
def make_ubx_rxm_rtcm(flags: int = 0x04, ref_station: int = 0,
                      msg_type: int = 1077) -> bytes:
    """UBX-RXM-RTCM フレームを生成する（checksum 付き）。

    flags=0x04: crcFailed=0, msgUsed=2（使用済み）。
    """
    payload = struct.pack("<BBHHH", 1, flags, 0, ref_station, msg_type)
    header = bytes((UBX_RXM_RTCM_CLASS, UBX_RXM_RTCM_ID,
                    len(payload) & 0xFF, (len(payload) >> 8) & 0xFF))
    return b"\xb5\x62" + header + payload + ubx_checksum(header + payload)


def make_rtcm3_frame(msg_type: int = 1077, body_len: int = 12) -> bytes:
    """RTCM3 フレームを生成する（CRC-24Q 付き）。"""
    if msg_type < 0 or msg_type > 0xFFF:
        raise ValueError("msg_type must be 0..0xFFF")
    body = bytes(((msg_type >> 4) & 0xFF, (msg_type & 0x0F) << 4))
    body += b"\x00" * body_len
    frame_len = len(body)
    header = bytes((0xD3, (frame_len >> 8) & 0x03, frame_len & 0xFF))
    no_crc = header + body
    crc = rtcm3_crc24q(no_crc)
    return no_crc + bytes(((crc >> 16) & 0xFF, (crc >> 8) & 0xFF, crc & 0xFF))


# ---------------------------------------------------------------------------
# MAVLink テレメトリ受信（本番構成の主役）
# ---------------------------------------------------------------------------
class MavlinkTelemetryReader:
    """UDP から MAVLink テレメトリを受信し、機体ごとの flattened 状態を保持する互換ラッパー。

    Phase 0 統合計画（§6 / §7 後処理）に基づき、メッセージ → 機体状態 の抽出ロジックは
    ``gcs.app.mavlink.telemetry``（正典）へ一本化した。本クラスは UDP 受信ループと
    ライフサイクル（start/stop）のみを担い、状態保持は ``VehicleStateStore`` に委譲する。

    Args:
        host: 待受 UDP バインドアドレス（既定 0.0.0.0）。
        port: 待受 UDP ポート（既定 14550 = MAVProxy 標準）。
        timeout: ``recv_match`` のブロッキングタイムアウト [秒]。
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 14550,
                 timeout: float = 1.0):
        if mavutil is None:
            raise ImportError("pymavlink が必要です: pip install pymavlink")
        self.host = host
        self.port = int(port)
        self.timeout = timeout
        self._master: Any = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        # 状態保持・抽出ロジックは正典モジュールへ委譲（二重実装の解消）
        self._store = VehicleStateStore()
        self.stats = self._store.stats

    # ------------------------------------------------------------------
    # 状態管理（gcs.app.mavlink.telemetry.VehicleStateStore へ委譲）
    # ------------------------------------------------------------------
    def process_message(self, msg: Any) -> Dict[str, Any]:
        """受信した MAVLink メッセージを機体状態へ反映する（正典ロジックへ委譲）。"""
        return self._store.apply(msg)

    def get_state(self, system_id: int) -> Optional[Dict[str, Any]]:
        return self._store.get_state(system_id)

    def vehicles(self) -> Dict[int, Dict[str, Any]]:
        """機体 ID → 状態 の辞書（コピー）を返す。"""
        return self._store.vehicles()

    def snapshot(self) -> Dict[str, Any]:
        return self._store.snapshot()

    # ------------------------------------------------------------------
    # 接続 / 受信ループ
    # ------------------------------------------------------------------
    def _open(self) -> Any:
        return mavutil.mavlink_connection("udpin:%s:%d" % (self.host, self.port))

    def start(self) -> bool:
        """UDP 待受を開始し、受信スレッドを起動する。"""
        if self._running:
            return True
        try:
            self._master = self._open()
        except Exception as e:  # noqa: BLE001
            print("[mavlink] UDP 待受を開始できません: %s" % e)
            return False
        self._running = True
        self._thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._thread.start()
        return True

    def _recv_loop(self) -> None:
        while self._running:
            try:
                msg = self._master.recv_match(
                    type=["GPS_RAW_INT", "HEARTBEAT", "SYS_STATUS"],
                    blocking=True,
                    timeout=self.timeout)
            except Exception:  # noqa: BLE001
                time.sleep(0.05)
                continue
            if msg is None:
                continue
            self.stats["packets"] += 1
            try:
                self.process_message(msg)
            except Exception as e:  # noqa: BLE001
                print("[mavlink] メッセージ処理エラー: %s" % e)

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        if self._master is not None:
            try:
                self._master.close()
            except Exception:  # noqa: BLE001
                pass
            self._master = None

    def is_running(self) -> bool:
        return self._running


# ---------------------------------------------------------------------------
# 後方互換（非推奨 / 既存 preflight・ekf_failsafe が参照）
# ---------------------------------------------------------------------------
class RoverUbxReader:
    """[非推奨] ローバー F9P の UBX ストリームを読む旧実装。

    本番構成（DroneCAN + MAVLink + UDP）では使用しない。
    ``MavlinkTelemetryReader`` へ置き換えてください。
    """

    NAV_PVT_CLASS = 0x01
    NAV_PVT_ID = 0x07

    def __init__(self, port: str, baud: int = 115200, monitor: Any = None,
                 poll_interval: float = 1.0, host: Optional[str] = None,
                 timeout: Optional[float] = None):
        warnings.warn(
            "RoverUbxReader は非推奨です（UBX シリアル/TCP 直読は廃止）。"
            "MavlinkTelemetryReader を使用してください。",
            DeprecationWarning, stacklevel=2)
        self.port = port
        self.baud = baud
        self.monitor = monitor
        self.poll_interval = poll_interval
        self.host = host
        self.timeout = timeout
        self._ser = None
        self._thread = None
        self._running = False
        self._lock = threading.Lock()
        self._latest: Dict[str, Any] = {
            "fix_type": None, "carr_soln": None, "diff_soln": None,
            "num_sv": None, "updated": False,
        }
        self.stats: Dict[str, int] = {"rx_bytes": 0, "rxm_rtcm": 0, "nav_pvt": 0}

    def start(self) -> bool:
        try:
            import serial  # noqa: PLC0415
        except ImportError as e:
            print("[rover] 依存ライブラリ不足: %s (pyserial が必要)" % e)
            return False
        try:
            self._ser = serial.Serial(self.port, self.baud, timeout=1.0)
        except Exception as e:  # noqa: BLE001
            print("[rover] シリアル接続に失敗: %s" % e)
            return False
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print("[rover] UBX 読取開始: %s @ %d bps" % (self.port, self.baud))
        return True

    def _loop(self) -> None:
        from pyubx2 import UBXMessage, UBXReader, POLL  # noqa: PLC0415
        ubr = UBXReader(self._ser)
        last_poll = 0.0
        while self._running:
            now = time.monotonic()
            if now - last_poll >= self.poll_interval:
                try:
                    self._ser.write(UBXMessage("NAV", "NAV-PVT", POLL).serialize())
                except Exception:  # noqa: BLE001
                    pass
                last_poll = now
            try:
                raw, parsed = ubr.read()
            except Exception:  # noqa: BLE001
                time.sleep(0.02)
                continue
            if raw:
                self.stats["rx_bytes"] += len(raw)
                if self.monitor is not None:
                    try:
                        infos = self.monitor.feed_ubx(raw)
                        self.stats["rxm_rtcm"] += len(infos)
                    except Exception:  # noqa: BLE001
                        pass
            if parsed is not None and parsed.identity == "NAV-PVT":
                self.stats["nav_pvt"] += 1
                with self._lock:
                    self._latest.update({
                        "fix_type": getattr(parsed, "fixType", None),
                        "carr_soln": getattr(parsed, "carrSoln", None),
                        "diff_soln": getattr(parsed, "diffSoln", None),
                        "num_sv": getattr(parsed, "numSV", None),
                        "updated": True,
                    })

    def sample(self) -> Optional[int]:
        with self._lock:
            u = dict(self._latest)
        if not u.get("updated"):
            return None
        return ubx_to_fix_type(u.get("fix_type"), u.get("carr_soln"), u.get("diff_soln"))

    def latest(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._latest)

    def tick(self) -> None:
        """ライブソースは自身のスレッドで供給するため no-op。"""

    def close(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        if self._ser:
            try:
                self._ser.close()
            except Exception:  # noqa: BLE001
                pass


class BaseRtcmReader:
    """[非推奨] 基地局 F9P の RTCM3 ストリームを読み、``monitor.feed_rtcm3()`` へ供給する。

    RTCM の UDP 配信は ``gcs.integration.rtcm_caster.RtcmCaster`` に置き換える。
    """

    def __init__(self, port: str, baud: int = 115200, monitor: Any = None):
        self.port = port
        self.baud = baud
        self.monitor = monitor
        self._ser = None
        self._thread = None
        self._running = False
        self.stats: Dict[str, int] = {"rx_bytes": 0, "frames": 0}

    def start(self) -> bool:
        try:
            import serial  # noqa: PLC0415
        except ImportError as e:
            print("[base] 依存ライブラリ不足: %s (pyserial が必要)" % e)
            return False
        try:
            self._ser = serial.Serial(self.port, self.baud, timeout=1.0)
        except Exception as e:  # noqa: BLE001
            print("[base] シリアル接続に失敗: %s" % e)
            return False
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print("[base] RTCM3 読取開始: %s @ %d bps" % (self.port, self.baud))
        return True

    def _loop(self) -> None:
        while self._running:
            try:
                data = self._ser.read(4096)
            except Exception:  # noqa: BLE001
                time.sleep(0.02)
                continue
            if data:
                self.stats["rx_bytes"] += len(data)
                if self.monitor is not None:
                    try:
                        frames = self.monitor.feed_rtcm3(data)
                        self.stats["frames"] += len(frames)
                    except Exception:  # noqa: BLE001
                        pass

    def tick(self) -> None:
        """ライブソースは自身のスレッドで供給するため no-op。"""

    def close(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        if self._ser:
            try:
                self._ser.close()
            except Exception:  # noqa: BLE001
                pass

# ---------------------------------------------------------------------------
# 合成ソース（自己検証用。実機なし）
# ---------------------------------------------------------------------------
class SyntheticRoverSource:
    """自己検証用: 合成 fix_type 時系列と合成 UBX-RXM-RTCM を供給する。

    ``fix_script`` は ``(経過秒, fix_type)`` のリスト（昇順）。``sample()`` は
    現在時刻に対応する fix_type を返すと同時に、``monitor`` へ正常な
    UBX-RXM-RTCM（msgUsed=2, crcFailed=0）を約1秒毎に供給する。
    """

    def __init__(self, monitor: Any = None, fix_script: Optional[List[tuple]] = None,
                 interval: float = 1.0):
        self.monitor = monitor
        self.interval = interval
        self.fix_script = list(fix_script or [(0.0, 5), (5.0, 6), (12.0, 5), (15.0, 6)])
        self._start: Optional[float] = None
        self._last_feed = 0.0

    def start(self) -> None:
        self._start = time.monotonic()
        self._last_feed = 0.0

    def _feed(self, t: float) -> None:
        if t - self._last_feed >= self.interval:
            self._last_feed = t
            if self.monitor is not None:
                self.monitor.feed_ubx(make_ubx_rxm_rtcm())

    def tick(self) -> None:
        if self._start is None:
            self.start()
        self._feed(time.monotonic() - self._start)

    def sample(self) -> Optional[int]:
        if self._start is None:
            self.start()
        t = time.monotonic() - self._start
        self._feed(t)
        cur: Optional[int] = None
        for tt, ft in self.fix_script:
            if t >= tt:
                cur = ft
            else:
                break
        return cur

    def close(self) -> None:
        pass


class SyntheticBaseSource:
    """自己検証用: 合成 RTCM3 フレームを ``monitor`` へ供給する。"""

    def __init__(self, monitor: Any = None, interval: float = 1.0):
        self.monitor = monitor
        self.interval = interval
        self._start: Optional[float] = None
        self._last_feed = 0.0

    def start(self) -> None:
        self._start = time.monotonic()
        self._last_feed = 0.0

    def tick(self) -> None:
        if self._start is None:
            self.start()
        t = time.monotonic() - self._start
        if t - self._last_feed >= self.interval:
            self._last_feed = t
            if self.monitor is not None:
                self.monitor.feed_rtcm3(make_rtcm3_frame())

    def sample(self) -> Optional[int]:
        return None

    def close(self) -> None:
        pass

# ---------------------------------------------------------------------------
# ① F9pConfigGuard の自己検証用フェイクストリーム
# ---------------------------------------------------------------------------
class FakeF9pStream:
    """pyserial 風インターフェースで F9P の挙動を再現する（① の実機なし検証用）。

    ``gcs/backend/test_f9p_configurator.py`` の FakeF9pStream と同趣旨だが、
    本パッケージ内で完結するよう最小構成で再実装した（既存テストは無改変）。
    """

    def __init__(self, current: Dict[str, int], apply_fix: bool = True,
                 fail_read: bool = False):
        from pyubx2.ubxhelpers import attsiz, cfgname2key  # noqa: PLC0415
        self.current = dict(current)
        self.apply_fix = apply_fix
        self.fail_read = fail_read
        self._rx = bytearray()
        self.valsets: List[Dict[str, Any]] = []
        self._sizes: Dict[int, int] = {}
        self._kid2name: Dict[int, str] = {}
        for name in current:
            kid, typ = cfgname2key(name)
            self._kid2name[kid] = name
            self._sizes[kid] = attsiz(typ)

    # -- pyserial 風 --
    def write(self, data) -> None:
        self._handle(bytes(data))

    def flush(self) -> None:
        pass

    def read(self, size: int) -> bytes:
        if self._rx:
            out = bytes(self._rx[:size])
            del self._rx[:size]
            return out
        return b""

    def reset_input_buffer(self) -> None:
        self._rx.clear()

    def close(self) -> None:
        pass

    # -- UBX ハンドリング --
    def _handle(self, data: bytes) -> None:
        from pyubx2.ubxhelpers import attsiz, cfgname2key  # noqa: PLC0415
        if len(data) < 8 or data[0:2] != b"\xb5\x62":
            return
        cls, mid = data[2], data[3]
        length = int.from_bytes(data[4:6], "little")
        payload = data[6:6 + length]
        if cls == 0x06 and mid == 0x8B:  # CFG-VALGET
            self._reply_valget()
        elif cls == 0x06 and mid == 0x8A:  # CFG-VALSET
            self._apply_valset(payload)

    def _reply_valget(self) -> None:
        from pyubx2.ubxhelpers import attsiz, cfgname2key  # noqa: PLC0415
        if self.fail_read:
            return
        payload = bytearray([1, 0, 0, 0])  # version=1, layer=0(RAM), position=0
        for name, val in self.current.items():
            kid, typ = cfgname2key(name)
            payload += kid.to_bytes(4, "little") + val.to_bytes(attsiz(typ), "little")
        self._rx.extend(self._frame(0x06, 0x8B, bytes(payload)))

    def _apply_valset(self, payload: bytes) -> None:
        layers = int.from_bytes(payload[1:3], "little")
        pos = 4
        cfg: Dict[str, int] = {}
        while pos + 4 <= len(payload):
            kid = int.from_bytes(payload[pos:pos + 4], "little")
            pos += 4
            name = self._kid2name.get(kid)
            size = self._sizes.get(kid, 1)
            if pos + size > len(payload):
                break
            val = int.from_bytes(payload[pos:pos + size], "little")
            pos += size
            if name is not None:
                cfg[name] = val
        self.valsets.append({"layer": layers, "cfg": cfg})
        if self.apply_fix:
            for name, val in cfg.items():
                self.current[name] = val

    @staticmethod
    def _frame(cls: int, mid: int, payload: bytes) -> bytes:
        body = bytes([cls, mid]) + len(payload).to_bytes(2, "little") + payload
        ck_a = ck_b = 0
        for b in body:
            ck_a = (ck_a + b) & 0xFF
            ck_b = (ck_b + ck_a) & 0xFF
        return b"\xb5\x62" + body + bytes([ck_a, ck_b])


def run_phase1_offline(guard: Any, current: Optional[Dict[str, int]] = None,
                       apply_fix: bool = True) -> Dict[str, Any]:
    """① F9pConfigGuard.run_check_and_fix() をフェイクストリームで実行する。

    Args:
        guard: F9pConfigGuard インスタンス。
        current: 現在の Golden 値（省略時は guard.golden をそのまま使う）。
        apply_fix: VALSET が反映されるか（False で修正失敗を再現できる）。
    """
    if current is None:
        current = dict(guard.golden)
    fake = FakeF9pStream(current, apply_fix=apply_fix)
    guard._open = lambda: setattr(guard, "_stream", fake)
    guard._close = lambda: None
    # run_check_and_fix() は _emit() で標準出力へ表示するため、自己検証では抑制する
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        return guard.run_check_and_fix()


__all__ = [
    "auto_detect_port",
    "make_ubx_rxm_rtcm",
    "make_rtcm3_frame",
    "mav_type_name",
    "decode_flight_mode",
    "MavlinkTelemetryReader",
    "RoverUbxReader",
    "BaseRtcmReader",
    "SyntheticRoverSource",
    "SyntheticBaseSource",
    "FakeF9pStream",
    "run_phase1_offline",
]





