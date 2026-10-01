#!/usr/bin/env python3
"""reader.py — UBX-NAV-RELPOSNED のシリアル読み取り（pyubx2 利用）

各ローバーに USB/UART 直結した F9P から UBX-NAV-RELPOSNED をポーリングし、
SI 単位へ正規化した :class:`RelposnedSample` を生成する。

既存資産の再利用:
  - ``archive/udp/base_ubx_logger.py`` の ``auto_detect_port``（シリアルポート自動検出）
  - ``pyubx2``（UBX メッセージのパース。既存の base_ubx_logger.py と同じ方式）

単位換算（pyubx2 の NAV-RELPOSNED 定義に基づく）:
  - relPosN / relPosE / relPosD / relPosLength : 生値は cm → /100 で m
  - relPosHeading                              : 既に deg（SCAL5=1e-5 適用済み）
  - accN / accE / accD / accLength             : 生値は 0.1mm → /1000 で m
  - accHeading                                 : 既に deg

Usage:
    from gcs.relpos.reader import UbxRelposReader

    r = UbxRelposReader(port="/dev/cu.usbmodemXXXX", rover_id="A")
    if r.start():
        sample = r.latest()   # RelposnedSample（最新値・未受信なら None）
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .pairing import RelposnedSample

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_UDP_DIR = _REPO_ROOT / "archive" / "udp"

try:
    if str(_UDP_DIR) not in sys.path:
        sys.path.insert(0, str(_UDP_DIR))
    from base_ubx_logger import auto_detect_port  # noqa: E402
except Exception:  # noqa: BLE001 - 既存資産が無くても reader 自体は動く
    auto_detect_port = None

DEFAULT_BAUD = 115200

# pyubx2 の NAV-RELPOSNED flags ビットを簡潔な名前へ写像する
_FLAG_ATTRS = {
    "gnssFixOK": "gnss_fix_ok",
    "diffSoln": "diff_soln",
    "relPosValid": "rel_pos_valid",
    "carrSoln": "carr_soln",
    "isMoving": "is_moving",
    "refPosMiss": "ref_pos_miss",
    "refObsMiss": "ref_obs_miss",
    "relPosHeadingValid": "rel_pos_heading_valid",
    "relPosNormalized": "rel_pos_normalized",
}


def _f(v: Any, default: float = 0.0) -> float:
    """None を default に落として float 化する。"""
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _i(v: Any, default: int = 0) -> int:
    try:
        if v is None:
            return default
        return int(v)
    except (TypeError, ValueError):
        return default


def from_pyubx2(parsed: Any, rover_id: str,
                wall_ts: Optional[float] = None) -> RelposnedSample:
    """pyubx2 の NAV-RELPOSNED 解析結果を SI 単位の RelposnedSample へ変換する。"""
    if wall_ts is None:
        wall_ts = time.time()

    flags: Dict[str, Any] = {}
    for src, dst in _FLAG_ATTRS.items():
        v = getattr(parsed, src, None)
        flags[dst] = _i(v) if dst == "carr_soln" else bool(v)

    # cm → m
    rel_n = _f(getattr(parsed, "relPosN", None)) / 100.0
    rel_e = _f(getattr(parsed, "relPosE", None)) / 100.0
    rel_d = _f(getattr(parsed, "relPosD", None)) / 100.0
    rel_length = _f(getattr(parsed, "relPosLength", None)) / 100.0
    rel_heading = _f(getattr(parsed, "relPosHeading", None))  # 既に deg

    # 0.1mm → m
    acc_n = _f(getattr(parsed, "accN", None)) / 1000.0
    acc_e = _f(getattr(parsed, "accE", None)) / 1000.0
    acc_d = _f(getattr(parsed, "accD", None)) / 1000.0
    acc_length = _f(getattr(parsed, "accLength", None)) / 1000.0
    acc_heading = _f(getattr(parsed, "accHeading", None))

    return RelposnedSample(
        rover_id=rover_id,
        itow_ms=_i(getattr(parsed, "iTOW", None)),
        ref_station_id=_i(getattr(parsed, "refStationID", None)),
        rel_n_m=rel_n,
        rel_e_m=rel_e,
        rel_d_m=rel_d,
        rel_length_m=rel_length,
        rel_heading_deg=rel_heading,
        acc_n_m=acc_n,
        acc_e_m=acc_e,
        acc_d_m=acc_d,
        acc_length_m=acc_length,
        acc_heading_deg=acc_heading,
        flags=flags,
        wall_ts=wall_ts,
    )


class UbxRelposReader:
    """F9P 直結シリアルから UBX-NAV-RELPOSNED をポーリングして最新値を保持する。

    ``fix_type_logger.UbxPvtReader`` と同様にバックグラウンドスレッドで
    POLL → read を繰り返し、最新の NAV-RELPOSNED を正規化して保持する。

    NAV-RELPOSNED が意味を持つには、F9P が RTK 補正（基準局からの RTCM3）を
    受信できている必要がある。refStationId / relPosValid で状態を確認できる。
    """

    def __init__(self, port: str, rover_id: str = "A",
                 baud: int = DEFAULT_BAUD, poll_interval: float = 0.1):
        self.port = port
        self.rover_id = rover_id
        self.baud = baud
        self.poll_interval = poll_interval
        self._ser = None
        self._ubr = None
        self._running = False
        self._thread = None
        self._sample: Optional[RelposnedSample] = None
        self._recv_count = 0

    def start(self) -> bool:
        try:
            import serial  # noqa: PLC0415
            from pyubx2 import UBXMessage, UBXReader, POLL  # noqa: PLC0415
        except ImportError as e:
            print("[RELPOS] 依存ライブラリ不足: %s (pyserial/pyubx2 が必要)" % e)
            return False

        try:
            self._ser = serial.Serial(self.port, self.baud, timeout=1.0)
            self._ubr = UBXReader(self._ser)
        except Exception as e:  # noqa: BLE001
            print("[RELPOS] シリアル接続に失敗: %s" % e)
            return False

        self._running = True
        import threading  # noqa: PLC0415
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print("[RELPOS:%s] NAV-RELPOSNED ポーリング開始: %s @ %d bps"
              % (self.rover_id, self.port, self.baud))
        return True

    def _loop(self) -> None:
        from pyubx2 import UBXMessage, POLL  # noqa: PLC0415

        while self._running:
            try:
                self._ser.write(UBXMessage("NAV", "NAV-RELPOSNED", POLL).serialize())
            except Exception:  # noqa: BLE001
                pass

            parsed = None
            try:
                _raw, parsed = self._ubr.read()
            except Exception:  # noqa: BLE001
                parsed = None

            if parsed is not None and parsed.identity == "NAV-RELPOSNED":
                self._sample = from_pyubx2(parsed, self.rover_id)
                self._recv_count += 1
            time.sleep(self.poll_interval)

    def latest(self) -> Optional[RelposnedSample]:
        return self._sample

    def recv_count(self) -> int:
        return self._recv_count

    def close(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        if self._ser:
            try:
                self._ser.close()
            except Exception:  # noqa: BLE001
                pass


def resolve_port(explicit: Optional[str]) -> Optional[str]:
    """シリアルポートを解決する（明示指定が優先、無ければ自動検出）。"""
    if explicit:
        return explicit
    if auto_detect_port is not None:
        return auto_detect_port()
    return None


__all__ = [
    "DEFAULT_BAUD",
    "from_pyubx2",
    "UbxRelposReader",
    "resolve_port",
]
