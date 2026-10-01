"""gcs.app.display — MAVLink テレメトリ → 表示用 dict の純粋変換ロジック。

Phase 0 統合計画（§4.1 / §7 Phase 2）に基づき、Web バックエンド各所に散在していた
表示変換ロジックを本モジュールへ一本化する。実ハードウェア・pymavlink 非依存で、
ダックタイピングされたメッセージ（``getattr`` で属性を読めるオブジェクト）のみを
入力に取るため、``gcs.app.test_display`` で実機なしに単体テストできる。

一本化対象（旧定義の所在）:
- GPS fix 名マッピング … ``gcs.app.api.websocket`` / ``gcs.app.mavlink.message_router``
- フライトモード名マッピング … ``gcs.app.api.websocket`` / ``gcs.app.api.server`` / ``gcs.app.api.routes``
- STATUSTEXT severity 名 … ``gcs.app.api.websocket`` / ``gcs.app.mavlink.message_router``
- ペイロード各サブセクションの整形 … ``gcs.app.api.websocket``

> 注: RTK 定量判定用の正規化マッピングは ``gcs.fix_metrics.FIX_NAMES``（0..6）が
> 正典である。本モジュールの ``FIX_NAMES`` は Web 表示用の MAVLink GPS_FIX_TYPE
> 表示マッピング（0..8、0=NO_GPS と 1=NO_FIX を区別）として独立に定義する。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# 定数テーブル
# ---------------------------------------------------------------------------

# MAVLink GPS_RAW_INT.fix_type の表示名（Web 表示用。0=NO_GPS と 1=NO_FIX を区別）
FIX_NAMES: Dict[int, str] = {
    0: "NO_GPS",
    1: "NO_FIX",
    2: "2D_FIX",
    3: "3D_FIX",
    4: "DGPS",
    5: "RTK_FLOAT",
    6: "RTK_FIXED",
    7: "STATIC",
    8: "PPP",
}

# ArduPilot Copter のカスタムモード番号 → 表示名
COPTER_MODES: Dict[int, str] = {
    0: "STABILIZE", 1: "ACRO", 2: "ALT_HOLD", 3: "AUTO",
    4: "GUIDED", 5: "LOITER", 6: "RTH", 7: "CIRCLE",
    9: "LAND", 10: "OPTFLOW", 11: "POSHOLD", 13: "AUTO_TUNE",
    14: "SPORT", 16: "BRAKE", 17: "THROW", 18: "AVOID_ADSB",
    19: "GUIDED_NOGPS", 20: "SMART_RTL", 21: "FLOWHOLD",
    22: "FOLLOW", 23: "ZIGZAG", 24: "SYSTEMID",
    25: "AUTOROTATE", 26: "AUTO_RTL",
}

# モード名 → 番号（/api/set_mode の逆引き用）
_COPTER_MODE_NUMBERS: Dict[str, int] = {v: k for k, v in COPTER_MODES.items()}

# MAVLink STATUSTEXT severity → 表示名
SEVERITY_NAMES: Dict[int, str] = {
    0: "EMERGENCY",
    1: "ALERT",
    2: "CRITICAL",
    3: "ERROR",
    4: "WARNING",
    5: "NOTICE",
    6: "INFO",
    7: "DEBUG",
}

# MAV_MODE_FLAG_SAFETY_ARMED（HEARTBEAT.base_mode の ARM ビット）
MAV_MODE_FLAG_SAFETY_ARMED = 0x00000080


# ---------------------------------------------------------------------------
# テーブル参照ヘルパー（純関数）
# ---------------------------------------------------------------------------

def fix_name(fix_type: Any) -> str:
    """fix_type を人間可読な表示名へ変換する。"""
    try:
        ft = int(fix_type)
    except (TypeError, ValueError):
        return "UNKNOWN(%s)" % (fix_type,)
    return FIX_NAMES.get(ft, "UNKNOWN(%d)" % ft)


def flight_mode_name(custom_mode: Any) -> str:
    """カスタムモード番号を表示名へ変換する。"""
    try:
        m = int(custom_mode)
    except (TypeError, ValueError):
        return "MODE_%s" % (custom_mode,)
    return COPTER_MODES.get(m, "MODE_%d" % m)


def mode_number(name: Any) -> Optional[int]:
    """フライトモード表示名をカスタムモード番号へ逆変換する。"""
    if name is None:
        return None
    return _COPTER_MODE_NUMBERS.get(str(name).upper())


def severity_name(severity: Any) -> str:
    """STATUSTEXT severity を表示名へ変換する。"""
    try:
        s = int(severity)
    except (TypeError, ValueError):
        return "UNKNOWN"
    return SEVERITY_NAMES.get(s, "UNKNOWN")


# ---------------------------------------------------------------------------
# ペイロード整形（純関数・ダックタイピング入力）
# ---------------------------------------------------------------------------

def heartbeat_to_display(hb: Any) -> Dict[str, Any]:
    """HEARTBEAT メッセージ → 表示 dict。"""
    if hb is None:
        return {"armed": False, "mode": "N/A", "base_mode": 0, "custom_mode": -1}
    try:
        base_mode = int(getattr(hb, "base_mode", 0))
        custom_mode = int(getattr(hb, "custom_mode", -1))
        return {
            "armed": (base_mode & MAV_MODE_FLAG_SAFETY_ARMED) != 0,
            "mode": flight_mode_name(custom_mode),
            "base_mode": base_mode,
            "custom_mode": custom_mode,
        }
    except Exception:  # noqa: BLE001 - 表示崩れを防ぐ安全化
        return {"armed": False, "mode": "ERR", "base_mode": 0, "custom_mode": -1}


def battery_to_display(ss: Any) -> Dict[str, Any]:
    """SYS_STATUS メッセージ → バッテリー表示 dict。"""
    if ss is None:
        return {"voltage": None, "current": None, "remaining": None}
    try:
        voltage = getattr(ss, "voltage_battery", 0) / 1000.0
        current = getattr(ss, "current_battery", 0) / 100.0
        remaining = getattr(ss, "battery_remaining", -1)
        return {
            "voltage": round(voltage, 2),
            "current": round(current, 2),
            "remaining": remaining if remaining >= 0 else None,
        }
    except Exception:  # noqa: BLE001
        return {"voltage": None, "current": None, "remaining": None}


def gps_to_display(gps_raw: Any, gpos: Any) -> Dict[str, Any]:
    """GPS_RAW_INT / GLOBAL_POSITION_INT → GPS 表示 dict。"""
    result: Dict[str, Any] = {
        "fix_type": -1,
        "fix_name": "N/A",
        "satellites": 0,
        "lat": None,
        "lon": None,
        "alt": None,
        "hdop": None,
    }

    if gps_raw is not None:
        try:
            fix_type = int(getattr(gps_raw, "fix_type", -1))
            result["fix_type"] = fix_type
            result["fix_name"] = fix_name(fix_type)
            result["satellites"] = int(getattr(gps_raw, "satellites_visible", 0))
            eph = getattr(gps_raw, "eph", 65535)
            result["hdop"] = round(eph / 100.0, 2) if eph < 65535 else None
        except Exception:  # noqa: BLE001
            pass

    if gpos is not None:
        try:
            result["lat"] = round(getattr(gpos, "lat", 0) / 1e7, 7)
            result["lon"] = round(getattr(gpos, "lon", 0) / 1e7, 7)
            result["alt"] = round(getattr(gpos, "alt", 0) / 1000.0, 2)
        except Exception:  # noqa: BLE001
            pass

    return result


def command_state_to_display(pending: List[Dict[str, Any]]) -> Dict[str, Any]:
    """保留コマンドリスト → コマンド状態表示 dict。"""
    last_ack = None
    for cmd in reversed(pending):
        if cmd.get("status") in ("acked", "failed", "timeout"):
            last_ack = {
                "command": cmd.get("description", ""),
                "status": cmd["status"],
            }
            break
    return {"pending_count": len(pending), "last_ack": last_ack}


def status_texts_to_display(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """STATUSTEXT リングバッファ → 表示リスト。"""
    result: List[Dict[str, Any]] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        sev = e.get("severity", 7)
        result.append({
            "text": e.get("text", ""),
            "severity": sev,
            "severity_name": severity_name(sev),
            "name": e.get("name", ""),
            "time": e.get("time", 0),
        })
    return result


def connection_status_to_display(status: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """MavlinkConnection.get_connection_status() の生 dict → 表示 dict。"""
    if not status:
        return {"is_connected": False, "type": "unknown"}
    last_error = status.get("last_error")
    return {
        "is_connected": status.get("is_connected", False),
        "type": status.get("connection_type", "unknown"),
        "packets_received": status.get("packet_received", 0),
        "packet_loss": status.get("packet_loss", 0),
        "last_error": str(last_error) if last_error else None,
    }


__all__ = [
    "FIX_NAMES",
    "COPTER_MODES",
    "SEVERITY_NAMES",
    "MAV_MODE_FLAG_SAFETY_ARMED",
    "fix_name",
    "flight_mode_name",
    "mode_number",
    "severity_name",
    "heartbeat_to_display",
    "battery_to_display",
    "gps_to_display",
    "command_state_to_display",
    "status_texts_to_display",
    "connection_status_to_display",
]
