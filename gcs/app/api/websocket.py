"""
WebSocket endpoint for real-time telemetry broadcast.

Broadcasts to all connected clients at 1Hz:
- connection: MavlinkConnection status (is_connected, packet stats, error)
- system_state: armed/mode from HEARTBEAT
- battery: voltage, current, remaining from SYS_STATUS
- gps: fix_type, satellites, lat/lon/alt, hdop
- command_state: pending count, last ACK status
- rtk: RTK forwarder and fix state statistics
"""

import asyncio
import json
import logging
import time
from typing import Optional, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from gcs.app.display import (  # noqa: E402
    connection_status_to_display,
    heartbeat_to_display,
    battery_to_display,
    gps_to_display,
    command_state_to_display,
    status_texts_to_display,
)

logger = logging.getLogger("api.websocket")

router = APIRouter()

# ── Client management ──────────────────────────────────────────────────
_active_clients: Set[WebSocket] = set()


# ── WebSocket endpoint ─────────────────────────────────────────────────

@router.websocket("/ws/telemetry")
async def telemetry_websocket(ws: WebSocket):
    """Enhanced telemetry WebSocket endpoint.

    Clients receive a JSON payload every second containing:
    connection, drones[system_id]{heartbeat, battery, gps, system_state, command_state}, rtk
    """
    await ws.accept()
    _active_clients.add(ws)
    logger.info(f"WS client connected (telemetry). Total: {len(_active_clients)}")

    try:
        while True:
            # Receive loop: accept client pings / configuration requests
            try:
                data = await asyncio.wait_for(ws.receive_text(), timeout=1.0)
                logger.debug(f"WS message: {data}")
            except asyncio.TimeoutError:
                # Normal polling timeout - no action needed
                pass
    except WebSocketDisconnect:
        logger.info("WS client disconnected (telemetry)")
    except Exception as e:
        logger.error(f"WS error: {e}")
    finally:
        _active_clients.discard(ws)
        logger.info(f"WS client removed. Total: {len(_active_clients)}")


# ── Broadcast coroutine ────────────────────────────────────────────────

async def broadcast_loop():
    """Every 1 second, build telemetry payload and send to all _active_clients."""
    global _active_clients
    # Read from api.server module each iteration so connect/disconnect works
    import gcs.app.api.server as api_srv

    while True:
        await asyncio.sleep(1.0)

        if not _active_clients:
            continue

        try:
            payload = _build_payload(
                api_srv.telemetry_store,
                api_srv.connection,
                api_srv.dispatcher,

                rtk_forwarder_stats=getattr(api_srv, "rtk_forwarder_stats", None),
                f9p_fix_state=getattr(api_srv, "f9p_fix_state", None),
            )
            if payload is None:
                continue

            text = json.dumps(payload, default=str)

            dead: Set[WebSocket] = set()
            for ws in _active_clients:
                try:
                    await ws.send_text(text)
                except Exception:
                    dead.add(ws)

            _active_clients -= dead

        except Exception as e:
            logger.error(f"Broadcast error: {e}", exc_info=True)


# ── Payload builder ────────────────────────────────────────────────────

# 表示変換のテーブル（fix 名 / モード名 / severity 名）と整形関数は
# gcs.app.display に一本化済み。ここでは store / dispatcher からの取り出しと
# 純関数への委譲のみを行う。

OFFLINE_TIMEOUT = 10.0  # seconds without telemetry → consider drone offline


def _build_payload(telemetry_store, connection, dispatcher,
                   rtk_forwarder_stats=None, f9p_fix_state=None) -> Optional[dict]:
    """Build the complete telemetry payload for broadcast.

    Drones that haven't sent any telemetry in OFFLINE_TIMEOUT seconds
    are flagged with ``online: false`` so the frontend can immediately
    show them as offline.
    """
    if telemetry_store is None:
        return None

    t_now = time.time()

    payload: dict = {
        "type": "telemetry",
        "timestamp": t_now,
        "connection": _build_connection_status(connection),
        "drones": {},
        "rtk": _build_rtk_status(rtk_forwarder_stats, f9p_fix_state),
    }

    last_seen_all = {}
    if hasattr(telemetry_store, "get_last_seen_all"):
        try:
            last_seen_all = telemetry_store.get_last_seen_all()
        except Exception:
            pass

    for sysid in sorted(telemetry_store.get_all_drone_ids()):
        last_seen = last_seen_all.get(sysid, 0)
        is_online = (t_now - last_seen) < OFFLINE_TIMEOUT if last_seen else False

        drone: dict = {
            "online": is_online,
            "heartbeat": _build_heartbeat(telemetry_store, sysid),
            "battery": _build_battery(telemetry_store, sysid),
            "gps": _build_gps(telemetry_store, sysid),
            "system_state": _build_system_state(telemetry_store, sysid),
            "command_state": _build_command_state(dispatcher, sysid),
            "status_texts": _build_status_texts(telemetry_store, sysid),
        }

        payload["drones"][str(sysid)] = drone

    return payload


def _build_connection_status(connection) -> dict:
    if connection is None:
        return {"is_connected": False, "type": "unknown"}
    try:
        return connection_status_to_display(connection.get_connection_status())
    except Exception:
        return {"is_connected": False, "type": "error"}


def _build_heartbeat(store, sysid: int) -> dict:
    return heartbeat_to_display(store.get_heartbeat(sysid))


def _build_battery(store, sysid: int) -> dict:
    return battery_to_display(store.get_sys_status(sysid))


def _build_gps(store, sysid: int) -> dict:
    return gps_to_display(store.get_gps_raw(sysid),
                          store.get_global_position(sysid))


def _build_system_state(store, sysid: int) -> dict:
    """Alias for heartbeat (armed + mode)."""
    return _build_heartbeat(store, sysid)


def _build_command_state(dispatcher, sysid: int) -> dict:
    if dispatcher is None:
        return {"pending_count": 0, "last_ack": None}

    try:
        pending = dispatcher.get_pending_commands(sysid)
    except Exception:
        return {"pending_count": 0, "last_ack": None}

    return command_state_to_display(pending)


def _build_status_texts(store, sysid: int) -> list:
    """Return the latest STATUSTEXT entries with severity as a named string."""
    try:
        entries = store.get_status_texts(sysid, count=20)
        return status_texts_to_display(entries) if entries else []
    except Exception:
        return []


def _build_rtk_status(rtk_forwarder_stats=None, f9p_fix_state=None) -> dict:
    """Build enriched RTK status payload with architecture detection.

    Priority: UART2 direct injection > Legacy MAVLink RTCM path > default/disabled.
    Only ONE architecture path is reported per payload.
    """
    result: dict = {
        "architecture": "none",
        "enabled": False,
    }

    # ── UART2 direct injection path ────────────────────────────────────
    if rtk_forwarder_stats is not None:
        result["architecture"] = "uart2_direct"
        result["enabled"] = True
        try:
            fwd = rtk_forwarder_stats() if callable(rtk_forwarder_stats) else rtk_forwarder_stats
            if fwd and isinstance(fwd, dict):
                result["uart2_injection"] = {
                    "total_packets": fwd.get("total_packets", 0),
                    "total_bytes": fwd.get("total_bytes", 0),
                    "forward_type": fwd.get("forward_type", "serial"),
                    "serial_port": fwd.get("serial_port", ""),
                    "last_update": fwd.get("last_update", 0),
                }
            else:
                result["uart2_injection"] = {
                    "total_packets": 0,
                    "total_bytes": 0,
                    "forward_type": "serial",
                    "serial_port": "",
                }
        except Exception:
            result["uart2_injection"] = {
                "total_packets": 0,
                "total_bytes": 0,
                "forward_type": "serial",
                "serial_port": "",
            }

    # ── F9P Fix state ──────────────────────────────────────────────────
    if f9p_fix_state is not None:
        try:
            fix = f9p_fix_state() if callable(f9p_fix_state) else f9p_fix_state
            if fix and isinstance(fix, dict):
                result["fix_status"] = {
                    "carrSoln": fix.get("carrSoln", -1),
                    "carrSoln_name": fix.get("carrSoln_name", "N/A"),
                    "fixType": fix.get("fixType", -1),
                    "numSV": fix.get("numSV", 0),
                    "hAcc": fix.get("hAcc", 0),
                    "vAcc": fix.get("vAcc", 0),
                    "lat": fix.get("lat", 0),
                    "lon": fix.get("lon", 0),
                    "hMSL": fix.get("hMSL", 0),
                    "last_update": fix.get("last_update", 0),
                }
        except Exception:
            pass

    return result
