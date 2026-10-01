"""gcs.app.mavlink.telemetry — MAVLink メッセージから機体状態（flattened）を抽出する正典ロジック。

Phase 0 統合計画（§6 / §7 後処理）に基づき、旧 ``gcs/integration/sources.py`` の
``MavlinkTelemetryReader`` が内包していた「メッセージ → 機体状態」変換ロジックを
本モジュールへ一本化する。

これにより:
- Web バックエンド（``gcs.app.mavlink.message_router`` + ``gcs.app.rtk_tools.telemetry_store``）
  と既存 ``gcs.integration`` の双方が同じ抽出ロジックを共有し、二重実装が解消される。
- ``gcs.integration.sources.MavlinkTelemetryReader`` は本モジュールを再利用する
  薄い互換ラッパーとして残す（既存テスト / runner の後方互換）。

抽出対象メッセージ:
- GPS_RAW_INT : fix_type / 衛星数 / 緯度経度高度 / EPH / EPV
- HEARTBEAT   : フライトモード / ARM 状態 / 機体種別 / system_status
- SYS_STATUS  : バッテリー電圧 / 電流 / 残量
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

from gcs.fix_metrics import fix_name

try:
    from pymavlink import mavutil
except ImportError:  # pragma: no cover - pymavlink 未導入環境
    mavutil = None


# ---------------------------------------------------------------------------
# MAVLink 定数 / ヘルパー
# ---------------------------------------------------------------------------
MAV_MODE_FLAG_CUSTOM_MODE_ENABLED = 0x00000001
MAV_MODE_FLAG_SAFETY_ARMED = 0x00000080

MAV_TYPE_NAMES: Dict[int, str] = {
    0: "GENERIC", 1: "FIXED_WING", 2: "QUADROTOR", 3: "COAXIAL",
    4: "HELICOPTER", 5: "ANTENNA_TRACKER", 6: "GCS", 7: "AIRSHIP",
    8: "FREE_BALLOON", 9: "ROCKET", 10: "ROVER", 11: "SURFACE_BOAT",
    12: "SUBMARINE", 13: "HEXAROTOR", 14: "OCTOROTOR", 15: "TRICOPTER",
    16: "FLAPPING_WING", 17: "KITE", 18: "ONBOARD_CONTROLLER",
    19: "VTOL_DUOROTOR", 20: "VTOL_QUADROTOR", 21: "VTOL_TILTROTOR",
    26: "GIMBAL", 27: "ADSB", 28: "PARAFOIL", 29: "DODECAROTOR",
    30: "CAMERA", 31: "CHARGING_STATION",
}

STATS_KEYS = ("packets", "gps_raw_int", "heartbeat", "sys_status", "other")


def mav_type_name(vehicle_type: int) -> str:
    """MAV_TYPE 整数値を人間可読な名前に変換する。"""
    try:
        vt = int(vehicle_type)
    except (TypeError, ValueError):
        return "UNKNOWN"
    return MAV_TYPE_NAMES.get(vt, "TYPE_%d" % vt)


def decode_flight_mode(msg: Any) -> str:
    """HEARTBEAT メッセージからフライトモード文字列を取得する。

    pymavlink の ``mode_string_v10``（ArduPilot/PX4 の mode 番号を正規デコード）
    を優先し、利用できない場合は base_mode / custom_mode から最低限の表現を返す。
    """
    if mavutil is not None:
        try:
            s = mavutil.mode_string_v10(msg)
            if s:
                return str(s)
        except Exception:  # noqa: BLE001
            pass
    base = int(getattr(msg, "base_mode", 0))
    custom = int(getattr(msg, "custom_mode", 0))
    if not (base & MAV_MODE_FLAG_CUSTOM_MODE_ENABLED):
        return "ARMED" if (base & MAV_MODE_FLAG_SAFETY_ARMED) else "DISARMED"
    return "MODE_%d" % custom


def new_vehicle_state(system_id: int) -> Dict[str, Any]:
    """機体（system_id）ごとの flattened 状態の初期値を作成する。"""
    return {
        "system_id": system_id,
        "component_id": None,
        "vehicle_type": None,
        "vehicle_type_name": None,
        "fix_type": None,
        "fix_name": None,
        "satellites": None,
        "lat": None,
        "lon": None,
        "alt_m": None,
        "eph_m": None,
        "epv_m": None,
        "flight_mode": None,
        "custom_mode": None,
        "base_mode": None,
        "system_status": None,
        "armed": False,
        "battery_voltage_v": None,
        "battery_current_a": None,
        "battery_remaining_pct": None,
        "last_update": None,
        "last_message": None,
        "messages": {"GPS_RAW_INT": 0, "HEARTBEAT": 0, "SYS_STATUS": 0},
    }


def new_stats() -> Dict[str, int]:
    return {"packets": 0, "gps_raw_int": 0, "heartbeat": 0,
            "sys_status": 0, "other": 0}


def apply_message(state: Dict[str, Any], msg: Any,
                  stats: Dict[str, int]) -> Dict[str, Any]:
    """受信した MAVLink メッセージを機体状態へ反映する（純粋ロジック）。

    Args:
        state: ``new_vehicle_state()`` で初期化した機体状態 dict（破壊的に更新）。
        msg:   pymavlink メッセージ（``get_type()`` / ``get_srcSystem()`` を持つ）。
        stats: メッセージ種別カウンタ dict（``new_stats()`` で初期化。破壊的に更新）。

    Returns:
        更新後の ``state``（内部参照）。
    """
    mtype = msg.get_type()
    comp = int(msg.get_srcComponent())
    now = time.time()

    state["component_id"] = comp
    state["last_update"] = now
    state["last_message"] = mtype

    if mtype == "GPS_RAW_INT":
        stats["gps_raw_int"] += 1
        state["messages"]["GPS_RAW_INT"] += 1
        state["fix_type"] = int(getattr(msg, "fix_type", 0))
        state["fix_name"] = fix_name(state["fix_type"])
        state["satellites"] = int(getattr(msg, "satellites_visible", 0))
        lat = getattr(msg, "lat", 0)
        lon = getattr(msg, "lon", 0)
        alt = getattr(msg, "alt", 0)
        state["lat"] = (lat / 1e7) if lat else None
        state["lon"] = (lon / 1e7) if lon else None
        state["alt_m"] = alt / 1000.0
        eph = getattr(msg, "eph", 65535)
        epv = getattr(msg, "epv", 65535)
        state["eph_m"] = (eph / 100.0) if eph not in (65535, -1) else None
        state["epv_m"] = (epv / 100.0) if epv not in (65535, -1) else None

    elif mtype == "HEARTBEAT":
        stats["heartbeat"] += 1
        state["messages"]["HEARTBEAT"] += 1
        vt = int(getattr(msg, "type", 0))
        state["vehicle_type"] = vt
        state["vehicle_type_name"] = mav_type_name(vt)
        state["custom_mode"] = int(getattr(msg, "custom_mode", 0))
        state["base_mode"] = int(getattr(msg, "base_mode", 0))
        state["system_status"] = int(getattr(msg, "system_status", 0))
        state["armed"] = bool(state["base_mode"] & MAV_MODE_FLAG_SAFETY_ARMED)
        state["flight_mode"] = decode_flight_mode(msg)

    elif mtype == "SYS_STATUS":
        stats["sys_status"] += 1
        state["messages"]["SYS_STATUS"] += 1
        vb = getattr(msg, "voltage_battery", 0)
        cb = getattr(msg, "current_battery", 0)
        br = getattr(msg, "battery_remaining", -1)
        state["battery_voltage_v"] = (vb / 1000.0) if vb else None
        state["battery_current_a"] = (cb / 100.0) if cb else None
        state["battery_remaining_pct"] = int(br) if br >= 0 else None

    else:
        stats["other"] += 1

    return state


class VehicleStateStore:
    """system_id をキーとする機体状態（flattened）のスレッドセーフ保持。

    ``MavlinkTelemetryReader`` と Web バックエンドの双方から再利用できる、
    メッセージ抽出ロジック（``apply_message``）の共有コンテナ。
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._vehicles: Dict[int, Dict[str, Any]] = {}
        self.stats: Dict[str, int] = new_stats()

    def apply(self, msg: Any) -> Dict[str, Any]:
        """メッセージを該当機体状態へ反映し、更新後の状態を返す。"""
        system_id = int(msg.get_srcSystem())
        with self._lock:
            state = self._vehicles.get(system_id)
            if state is None:
                state = new_vehicle_state(system_id)
                self._vehicles[system_id] = state
            return apply_message(state, msg, self.stats)

    def get_state(self, system_id: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            state = self._vehicles.get(system_id)
            return dict(state) if state is not None else None

    def vehicles(self) -> Dict[int, Dict[str, Any]]:
        """機体 ID → 状態 の辞書（コピー）を返す。"""
        with self._lock:
            return {sid: dict(st) for sid, st in self._vehicles.items()}

    def snapshot(self) -> Dict[str, Any]:
        return {"vehicles": self.vehicles(), "stats": dict(self.stats)}


__all__ = [
    "MAV_MODE_FLAG_CUSTOM_MODE_ENABLED",
    "MAV_MODE_FLAG_SAFETY_ARMED",
    "MAV_TYPE_NAMES",
    "STATS_KEYS",
    "mav_type_name",
    "decode_flight_mode",
    "new_vehicle_state",
    "new_stats",
    "apply_message",
    "VehicleStateStore",
]
