#!/usr/bin/env python3
"""recorder.py — Phase 4 実飛行試験のデータ記録（MAVLink 観測 / CSV・JSONL 入出力）

飛行中（移動局 F9P を機体に搭載した状態）の MAVLink ストリームから、
  - GPS_RAW_INT          : fix_type / hdop / vdop / satellites_visible
  - EKF_STATUS_REPORT    : flags / pos_horiz_variance / pos_vert_variance / velocity_variance
  - STATUSTEXT           : フェイルセーフ発動の証跡（"Failsafe …" 等）
  - HEARTBEAT            : モード遷移（RTL / LAND 等を FS 補助証跡として利用）
を記録し、サンプル時系列を CSV、FS/モードイベントを JSON Lines に書き出す。

pymavlink は実機（MAVLink）接続時のみ必要。import できなくても本モジュールは読める。
"""

from __future__ import annotations

import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# 実行位置に依存しない import（リポジトリルートを sys.path に追加）
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gcs.fix_metrics import fix_name  # noqa: E402
from gcs.flight_test.metrics import classify_failsafe_text  # noqa: E402

try:
    from pymavlink import mavutil  # noqa: F401
except ImportError:  # pragma: no cover - 実機なし環境
    mavutil = None  # type: ignore[assignment]

# MAVLink メッセージ ID
_MSG_GPS_RAW_INT = "GPS_RAW_INT"
_MSG_EKF_STATUS_REPORT = "EKF_STATUS_REPORT"
_MSG_STATUSTEXT = "STATUSTEXT"
_MSG_HEARTBEAT = "HEARTBEAT"

# 出力 CSV のカラム順（サンプル時系列）
CSV_FIELDS = [
    "timestamp", "elapsed_sec", "fix_type", "fix_name",
    "hdop_m", "vdop_m", "sats",
    "ekf_flags", "ekf_pos_horiz_m", "ekf_pos_vert_m", "ekf_vel_var",
]


def _num(v: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _sqrt_var(v: Any) -> Optional[float]:
    """EKF 分散（m^2）を 1σ 誤差（m）に変換する。非正値・None は None。"""
    f = _num(v)
    if f is None or f < 0:
        return None
    return float(f) ** 0.5


class FlightRecorder:
    """MAVLink から飛行中の測位状態を記録する。

    Args:
        device: シリアルデバイス（例: /dev/ttyAMA0）。None で connection_string を使用。
        baud: シリアルボーレート（既定 921600 = Pixhawk6C TELEM1）。
        connection_string: ``mavutil.mavlink_connection()`` に渡す接続文字列
            （例: "tcp:192.168.1.100:5760", "udpin:0.0.0.0:14550"）。device より優先。
        timeout: MAVLink 応答待ちタイムアウト（秒）。
    """

    DEFAULT_BAUD = 921600

    def __init__(self, device: Optional[str] = None, baud: int = DEFAULT_BAUD,
                 connection_string: Optional[str] = None, timeout: float = 3.0):
        self.device = device
        self.baud = baud
        self.connection_string = connection_string
        self.timeout = timeout
        self._master = None
        self._latest_gps: Dict[str, Any] = {}
        self._latest_ekf: Dict[str, Any] = {}
        self._last_mode: Optional[str] = None

    # ------------------------------------------------------------------
    # トランスポート
    # ------------------------------------------------------------------
    def _connection_desc(self) -> str:
        if self.connection_string:
            return self.connection_string
        return "%s @ %d bps" % (self.device or "(auto)", self.baud)

    def connect(self) -> None:
        if mavutil is None:
            raise RuntimeError(
                "pymavlink が必要です: pip install pymavlink（または ~/Mavlink_venv を有効化）")
        if self.connection_string:
            self._master = mavutil.mavlink_connection(self.connection_string, baud=self.baud)
        elif self.device:
            self._master = mavutil.mavlink_connection(self.device, baud=self.baud)
        else:
            raise RuntimeError("接続先を指定してください（--device または --mavlink）")
        self._master.wait_heartbeat(timeout=self.timeout)

    def close(self) -> None:
        if self._master is not None:
            try:
                self._master.close()
            except Exception:  # noqa: BLE001
                pass
            self._master = None

    def enable_streams(self, interval_hz: float = 5.0) -> None:
        """観測対象メッセージの MAVLink ストリームを要求する（ベストエフォート）。"""
        if mavutil is None or self._master is None:
            return
        interval_us = int(1e6 / max(1.0, interval_hz))
        ids = {_MSG_GPS_RAW_INT: 24, _MSG_EKF_STATUS_REPORT: 193}
        for msg_name, msg_id in ids.items():
            try:
                self._master.mav.command_long_send(
                    self._master.target_system, self._master.target_component,
                    mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, 0,
                    float(msg_id), float(interval_us), 0.0, 0.0, 0.0, 0.0, 0.0)
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # メッセージ処理
    # ------------------------------------------------------------------
    def _handle_gps(self, msg: Any) -> None:
        hdop = _num(getattr(msg, "hdop", None))
        vdop = _num(getattr(msg, "vdop", None))
        sats = getattr(msg, "satellites_visible", None)
        ft = getattr(msg, "fix_type", None)
        self._latest_gps = {
            "fix_type": int(ft) if ft is not None and int(ft) >= 0 else None,
            "hdop": (hdop / 100.0) if hdop is not None else None,
            "vdop": (vdop / 100.0) if vdop is not None else None,
            "sats": int(sats) if sats is not None else None,
        }

    def _handle_ekf(self, msg: Any) -> None:
        self._latest_ekf = {
            "ekf_flags": int(getattr(msg, "flags", 0)),
            "ekf_pos_horiz_m": _sqrt_var(getattr(msg, "pos_horiz_variance", None)),
            "ekf_pos_vert_m": _sqrt_var(getattr(msg, "pos_vert_variance", None)),
            "ekf_vel_var": _num(getattr(msg, "velocity_variance", None)),
        }

    def _drain(self, start_t: float,
               failsafe_events: List[Dict[str, Any]],
               mode_events: List[Dict[str, Any]]) -> None:
        """受信バッファを短時間読み、各メッセージを処理する。"""
        while True:
            msg = self._master.recv_match(blocking=False, timeout=0.05)
            if msg is None:
                break
            mtype = msg.get_type()
            now = time.monotonic()
            t = now - start_t
            if mtype == _MSG_GPS_RAW_INT:
                self._handle_gps(msg)
            elif mtype == _MSG_EKF_STATUS_REPORT:
                self._handle_ekf(msg)
            elif mtype == _MSG_STATUSTEXT:
                text = getattr(msg, "text", "")
                if isinstance(text, bytes):
                    text = text.decode("utf-8", "replace")
                kind = classify_failsafe_text(text)
                if kind:
                    failsafe_events.append({
                        "t": t,
                        "ts": datetime.now().strftime("%H:%M:%S.%f")[:-3],
                        "kind": kind,
                        "text": text,
                    })
            elif mtype == _MSG_HEARTBEAT:
                mode = None
                mapping = getattr(self._master, "mode_mapping", None)
                if mapping:
                    mode = mapping.get(getattr(msg, "custom_mode", -1))
                mode = mode or str(getattr(msg, "custom_mode", ""))
                if mode and mode != self._last_mode:
                    self._last_mode = mode
                    mode_events.append({
                        "t": t,
                        "ts": datetime.now().strftime("%H:%M:%S.%f")[:-3],
                        "mode": mode,
                    })

    def sample(self) -> Dict[str, Any]:
        """最新の GPS / EKF 状態を 1 サンプルに合成する。"""
        s: Dict[str, Any] = {"fix_type": None, "hdop": None, "vdop": None,
                             "sats": None, "ekf_flags": None,
                             "ekf_pos_horiz_m": None, "ekf_pos_vert_m": None,
                             "ekf_vel_var": None}
        s.update(self._latest_gps)
        s.update(self._latest_ekf)
        return s

    # ------------------------------------------------------------------
    # 観測ループ
    # ------------------------------------------------------------------
    def observe(self, duration: float, interval: float = 1.0,
                on_event: Optional[Callable[[Dict[str, Any]], None]] = None
                ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        """duration 秒間観測し、(series, failsafe_events, mode_events) を返す。"""
        series: List[Dict[str, Any]] = []
        failsafe_events: List[Dict[str, Any]] = []
        mode_events: List[Dict[str, Any]] = []
        if self._master is None:
            self.connect()
        self.enable_streams()

        start = time.monotonic()
        last_sample = 0.0
        last_progress = 0.0
        try:
            while time.monotonic() - start < duration:
                self._drain(start, failsafe_events, mode_events)
                now = time.monotonic()
                if now - last_sample >= interval:
                    last_sample = now
                    s = self.sample()
                    s["t"] = now - start
                    s["ts"] = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    if s["fix_type"] is not None:
                        series.append(s)
                if on_event is not None and now - last_progress >= 1.0:
                    last_progress = now
                    on_event({
                        "type": "progress",
                        "elapsed_sec": now - start,
                        "duration_sec": duration,
                        "fix_type": self._latest_gps.get("fix_type"),
                        "ekf_flags": self._latest_ekf.get("ekf_flags"),
                    })
                time.sleep(min(0.05, interval))
        finally:
            self.close()
        return series, failsafe_events, mode_events

# ---------------------------------------------------------------------------
# CSV / JSON Lines 入出力
# ---------------------------------------------------------------------------
def write_flight_csv(series: List[Dict[str, Any]], path: str) -> None:
    """観測したサンプル時系列を CSV に書き出す。"""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_FIELDS)
        for s in series:
            ft = s.get("fix_type")
            w.writerow([
                s.get("ts", ""),
                ("%.3f" % s["t"]) if s.get("t") is not None else "",
                "" if ft is None else int(ft),
                fix_name(int(ft)) if ft is not None else "",
                _fmt_or_blank(s.get("hdop")),
                _fmt_or_blank(s.get("vdop")),
                _fmt_or_blank(s.get("sats")),
                _fmt_or_blank(s.get("ekf_flags")),
                _fmt_or_blank(s.get("ekf_pos_horiz_m")),
                _fmt_or_blank(s.get("ekf_pos_vert_m")),
                _fmt_or_blank(s.get("ekf_vel_var")),
            ])


def write_events_jsonl(failsafe_events: List[Dict[str, Any]],
                       mode_events: List[Dict[str, Any]], path: str) -> None:
    """FS / モードイベントを JSON Lines に書き出す。"""
    with open(path, "w", encoding="utf-8") as f:
        for ev in failsafe_events:
            f.write(json.dumps({"type": "failsafe", **ev}, ensure_ascii=False) + "\n")
        for ev in mode_events:
            f.write(json.dumps({"type": "mode", **ev}, ensure_ascii=False) + "\n")


def _fmt_or_blank(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return "%.4f" % v
    return str(v)


def load_flight_csv(path: str) -> List[Dict[str, Any]]:
    """Phase 4 のサンプル CSV を読み込み、metrics の入力スキーマへ変換する。"""
    series: List[Dict[str, Any]] = []
    with open(path, "r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ft = _num(row.get("fix_type"))
            series.append({
                "t": _num(row.get("elapsed_sec")),
                "ts": row.get("timestamp", ""),
                "fix_type": int(ft) if ft is not None else None,
                "hdop": _num(row.get("hdop_m")),
                "vdop": _num(row.get("vdop_m")),
                "sats": _num(row.get("sats")),
                "ekf_flags": _num(row.get("ekf_flags")),
                "ekf_pos_horiz_m": _num(row.get("ekf_pos_horiz_m")),
                "ekf_pos_vert_m": _num(row.get("ekf_pos_vert_m")),
                "ekf_vel_var": _num(row.get("ekf_vel_var")),
            })
    return series


def load_events_jsonl(path: str
                      ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """イベント JSON Lines を読み込み、(failsafe_events, mode_events) を返す。"""
    failsafe_events: List[Dict[str, Any]] = []
    mode_events: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                typ = obj.pop("type", None)
                if typ == "failsafe":
                    failsafe_events.append(obj)
                elif typ == "mode":
                    mode_events.append(obj)
    except FileNotFoundError:
        return [], []
    return failsafe_events, mode_events


__all__ = [
    "CSV_FIELDS", "FlightRecorder",
    "write_flight_csv", "write_events_jsonl",
    "load_flight_csv", "load_events_jsonl",
]


