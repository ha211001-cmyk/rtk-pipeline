"""app/api/routes.py — REST API endpoints for command dispatch and connection management."""

import asyncio
import logging
import threading
import time
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from gcs.app.display import COPTER_MODES  # noqa: E402

logger = logging.getLogger("api.routes")
router = APIRouter(prefix="/api", tags=["commands"])

# ── Lazy backend references (always read from api.server module) ──────

def _get_ts():
    """Get telemetry_store from api.server, raise 503 if not initialized."""
    import gcs.app.api.server as api_srv
    ts = api_srv.telemetry_store
    if ts is None:
        raise HTTPException(status_code=503, detail="Backend not initialized (telemetry_store)")
    return ts


def _get_disp():
    """Get dispatcher from api.server, raise 503 if not initialized."""
    import gcs.app.api.server as api_srv
    disp = api_srv.dispatcher
    if disp is None:
        raise HTTPException(status_code=503, detail="Backend not initialized (dispatcher)")
    return disp


def _get_conn():
    """Get connection from api.server, raise 503 if not initialized."""
    import gcs.app.api.server as api_srv
    conn = api_srv.connection
    if conn is None:
        raise HTTPException(status_code=503, detail="Backend not initialized (connection)")
    return conn


# ── Connection request model ─────────────────────────────────────────

class ConnectRequest(BaseModel):
    config_path: Optional[str] = None


# ==========================================================================
# Pydantic request models
# ==========================================================================

class SystemIdsRequest(BaseModel):
    system_ids: List[int] = Field(..., min_length=1)
    component_id: int = Field(default=1)

class ParamRequest(BaseModel):
    system_id: int = Field(default=1)
    param_id: str
    component_id: int = Field(default=1)


class ForceArmRequest(SystemIdsRequest):
    confirmed: bool = Field(..., description="Must be true to proceed")


class TakeoffRequest(SystemIdsRequest):
    altitude: float = Field(default=2.0, ge=0.5, le=500.0)


class LandRequest(SystemIdsRequest):
    descent_rate: float = Field(default=0.5, ge=0.0, le=20.0)


class GuidedPositionRequest(SystemIdsRequest):
    north: float = Field(default=0.0)
    east: float = Field(default=0.0)
    down: float = Field(default=-5.0)
    yaw: float = Field(default=0.0, ge=-180.0, le=180.0)


class GuidedVelocityRequest(SystemIdsRequest):
    vx: float = Field(default=0.0, ge=-20.0, le=20.0)
    vy: float = Field(default=0.0, ge=-20.0, le=20.0)
    vz: float = Field(default=0.0, ge=-20.0, le=20.0)
    yaw: float = Field(default=0.0, ge=-180.0, le=180.0)


# ==========================================================================
# Flight-mode decoding
# ==========================================================================

# モード名マッピングは gcs.app.display.COPTER_MODES に一本化済み。


# ==========================================================================
# POST /api/connect — Initialize backend and connect to drone
# ==========================================================================

@router.post("/connect")
async def connect_to_drone(req: ConnectRequest, request: Request):
    """Initialize all backend components and connect to drone."""
    import gcs.app.api.server as api_srv

    if api_srv.connection is not None:
        logger.warning("Backend already connected.")
        return JSONResponse(
            {"status": "error", "detail": "Already connected. POST /api/disconnect first."},
            status_code=409,
        )

    app = request.app
    logger.info("=== Backend initialization via /api/connect ===")

    try:
        import os
        import yaml

        from gcs.rtk_tools.config_loader import resolve_config_path
        from gcs.app.mavlink.connection import MavlinkConnection
        from gcs.app.mavlink.message_router import MessageRouter
        from gcs.app.rtk_tools.telemetry_store import TelemetryStore
        from gcs.app.rtk_tools.command_dispatcher import CommandDispatcher
        from gcs.app.rtk_tools.guided_control import GuidedControl

        config_path = req.config_path or resolve_config_path()
        logger.info(f"Config: {config_path}")

        telemetry_store = TelemetryStore()
        mav_conn = MavlinkConnection(config_path)

        dispatcher = CommandDispatcher(mav_conn)
        dispatcher.guided = GuidedControl(mav_conn)

        router = MessageRouter(mav_conn, telemetry_store, command_dispatcher=dispatcher)
        router.start()

        def _request_streams():
            import time as _time
            _time.sleep(2.0)
            try:
                msg = mav_conn.mav.request_data_stream_encode(1, 0, 0, 5, 1)
                frame = msg.pack(mav_conn.mav)
                mav_conn.send(1, frame)
                logger.info("Data stream request sent")
            except Exception as e:
                logger.error(f"Stream request failed: {e}")

        threading.Thread(target=_request_streams, daemon=True).start()

        # ── RTK architecture detection ──────────────────────────────────
        rtk_forwarder_stats = None
        f9p_fix_state_ref = None
        uart2_direct = False

        # Determine project root for config detection
        _project_root = os.environ.get(
            "GCS_PROJECT_ROOT",
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        )
        _rtk_fwd_config_path = os.path.join(_project_root, "config", "rtk_forwarder.yml")

        if os.path.exists(_rtk_fwd_config_path):
            try:
                with open(_rtk_fwd_config_path, "r") as f:
                    _fwd_cfg = yaml.safe_load(f) or {}
                _fwd_type = (
                    _fwd_cfg.get("forward", {}).get("type", "udp")
                    if isinstance(_fwd_cfg, dict)
                    else "udp"
                )
                if _fwd_type == "serial":
                    uart2_direct = True
                    logger.info(
                        "RTK architecture: UART2 direct injection (rtk_forwarder type=serial)"
                    )
                else:
                    logger.info(
                        f"RTK forwarder: type={_fwd_type} (UART2 serial injection not configured)"
                    )
            except Exception as e:
                logger.warning(f"Could not parse rtk_forwarder.yml: {e}")
        else:
            logger.info("No rtk_forwarder.yml found; UART2 direct injection not configured")

        if uart2_direct:
            from gcs.app.api.rtk_state import get_forwarder_stats, get_fix_state

            rtk_forwarder_stats = get_forwarder_stats
            f9p_fix_state_ref = get_fix_state

            logger.info("UART2 direct injection: using rtk_state module for RTK monitoring")
        else:
            logger.info("RTK: UART2 direct injection not configured (rtk_forwarder.yml forward.type != serial)")

        api_srv.init_api(
            telemetry_store, dispatcher, mav_conn,
            _rtk_forwarder_stats=rtk_forwarder_stats,
            _f9p_fix_state=f9p_fix_state_ref,
        )

        app.state.mav_conn = mav_conn
        app.state.router = router
        app.state.rtk_architecture = "uart2_direct" if uart2_direct else "none"

        conn_status = mav_conn.get_connection_status()
        logger.info("=== Backend connected ===")
        return {"status": "connected", "connection": conn_status, "config_path": config_path}

    except Exception as e:
        logger.error(f"Backend init failed: {e}", exc_info=True)
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)


# ==========================================================================
# POST /api/disconnect — Safely disconnect backend
# ==========================================================================

@router.post("/disconnect")
async def disconnect_from_drone(request: Request):
    """Safely disconnect and tear down all backend components."""
    import gcs.app.api.server as api_srv

    if api_srv.connection is None:
        return JSONResponse(
            {"status": "error", "detail": "Backend not connected."},
            status_code=400,
        )

    app = request.app
    logger.info("=== Backend disconnection via /api/disconnect ===")

    errors = []

    if hasattr(app.state, "router") and app.state.router is not None:
        try:
            app.state.router.stop()
        except Exception as e:
            errors.append(f"router: {e}")
        app.state.router = None

    if hasattr(app.state, "mav_conn") and app.state.mav_conn is not None:
        try:
            app.state.mav_conn.stop()
        except Exception as e:
            errors.append(f"mav_conn: {e}")
        app.state.mav_conn = None

    api_srv.telemetry_store = None
    api_srv.dispatcher = None
    api_srv.connection = None
    api_srv.rtk_forwarder_stats = None
    api_srv.f9p_fix_state = None

    logger.info("=== Backend disconnected ===")
    return {"status": "disconnected", "errors": errors if errors else None}


# ==========================================================================
# GET /api/status
# ==========================================================================

@router.get("/status")
async def get_status():
    """Get connection status and drone info (works even when not connected)."""
    import gcs.app.api.server as api_srv

    # ── Connection status ────────────────────────────────────────────
    conn = api_srv.connection
    if conn is None:
        conn_status = {"is_connected": False, "connection_type": "none"}
    else:
        try:
            conn_status = conn.get_connection_status()
        except Exception as e:
            logger.error("Failed to get connection status: %s", e)
            conn_status = {"is_connected": False, "error": str(e)}

    # ── Drone info ───────────────────────────────────────────────────
    ts = api_srv.telemetry_store
    drone_ids = ts.get_all_drone_ids() if ts else []

    return {
        "status": "ok",
        "server": {"uptime_seconds": round(time.monotonic(), 1)},
        "connection": {
            "is_connected": conn_status.get("is_connected", False),
            "type": conn_status.get("connection_type", "unknown"),
            "packets_received": conn_status.get("packet_received", 0),
            "packets_lost": conn_status.get("packet_loss", 0),
            "last_error": conn_status.get("last_error", None),
        },
        "drones_connected": len(drone_ids),
        "drone_ids": drone_ids,
    }


# ==========================================================================
# POST /api/arm
# ==========================================================================

@router.post("/arm")
async def cmd_arm(req: SystemIdsRequest):
    disp = _get_disp()
    for sysid in req.system_ids:
        logger.info("ARM → drone %d", sysid)
        disp.arm(sysid, component_id=req.component_id)
    return {"status": "ok", "command": "arm", "system_ids": req.system_ids}


# ==========================================================================
# POST /api/disarm
# ==========================================================================

@router.post("/disarm")
async def cmd_disarm(req: SystemIdsRequest):
    disp = _get_disp()
    for sysid in req.system_ids:
        logger.info("DISARM → drone %d", sysid)
        disp.disarm(sysid, component_id=req.component_id)
    return {"status": "ok", "command": "disarm", "system_ids": req.system_ids}


# ==========================================================================
# POST /api/force_arm
# ==========================================================================

@router.post("/force_arm")
async def cmd_force_arm(req: ForceArmRequest):
    if not req.confirmed:
        raise HTTPException(
            status_code=400,
            detail="Force-arm requires 'confirmed: true'.",
        )
    disp = _get_disp()
    for sysid in req.system_ids:
        logger.warning("FORCE ARM → drone %d", sysid)
        disp.force_arm(sysid, component_id=req.component_id)
    return {
        "status": "ok", "command": "force_arm",
        "system_ids": req.system_ids,
        "warning": "Pre-arm checks disabled. Use restore_arm_params to re-enable.",
    }


# ==========================================================================
# POST /api/takeoff
# ==========================================================================

@router.post("/takeoff")
async def cmd_takeoff(req: TakeoffRequest):
    disp = _get_disp()
    ts = _get_ts()
    results = []
    for sysid in req.system_ids:
        hb = ts.get_heartbeat(sysid)
        armed = False
        if hb is not None:
            try:
                armed = (hb.base_mode & 0x80) != 0
            except Exception:
                pass
        if not armed:
            results.append({
                "system_id": sysid, "status": "skipped",
                "reason": "Drone is not armed. Arm first.",
            })
            continue
        logger.info("TAKEOFF → drone %d alt=%.1f", sysid, req.altitude)
        disp.takeoff(sysid, component_id=req.component_id, altitude=req.altitude)
        results.append({"system_id": sysid, "status": "sent"})
    all_ok = all(r["status"] == "sent" for r in results)
    return {
        "status": "ok" if all_ok else "partial",
        "command": "takeoff", "altitude": req.altitude, "results": results,
    }


# ==========================================================================
# POST /api/land
# ==========================================================================

@router.post("/land")
async def cmd_land(req: LandRequest):
    disp = _get_disp()
    for sysid in req.system_ids:
        logger.info("LAND → drone %d rate=%.1f", sysid, req.descent_rate)
        disp.land(sysid, component_id=req.component_id,
                  descent_rate=req.descent_rate)
    return {
        "status": "ok", "command": "land",
        "system_ids": req.system_ids, "descent_rate": req.descent_rate,
    }


# ==========================================================================
# POST /api/guided/position
# ==========================================================================

def _require_guided():
    disp = _get_disp()
    guided = getattr(disp, "guided", None)
    if guided is None:
        raise HTTPException(status_code=503, detail="Guided control unavailable")
    return guided


@router.post("/guided/position")
async def cmd_guided_position(req: GuidedPositionRequest):
    guided = _require_guided()
    for sysid in req.system_ids:
        logger.info("GUIDED POS → drone %d NED=(%.1f,%.1f,%.1f) yaw=%.1f",
                    sysid, req.north, req.east, req.down, req.yaw)
        guided.set_position_target_local_ned(
            sysid, req.component_id,
            x=req.north, y=req.east, z=req.down, yaw=req.yaw,
        )
    return {
        "status": "ok", "command": "guided_position",
        "system_ids": req.system_ids,
        "position": {"north": req.north, "east": req.east, "down": req.down},
        "yaw": req.yaw,
    }


# ==========================================================================
# POST /api/set_mode — Set flight mode for a single drone
# ==========================================================================

class SetModeRequest(BaseModel):
    system_id: int = Field(..., ge=1)
    mode: str = Field(..., min_length=1)


# ArduPilot Copter custom mode number lookup
_COPTER_MODE_NUMBERS = {v: k for k, v in COPTER_MODES.items()}


@router.post("/set_mode")
async def cmd_set_mode(req: SetModeRequest):
    disp = _get_disp()
    mode_num = _COPTER_MODE_NUMBERS.get(req.mode.upper())
    if mode_num is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown mode '{req.mode}'. Available: {', '.join(sorted(_COPTER_MODE_NUMBERS.keys()))}",
        )
    logger.info("SET_MODE → drone %d → %s (%d)", req.system_id, req.mode, mode_num)
    # MAV_CMD_DO_SET_MODE (176): param1=1 (custom mode), param2=mode_number
    disp._send_command(req.system_id, 1, 176, param1=1, param2=float(mode_num))
    return {
        "status": "ok",
        "command": "set_mode",
        "system_id": req.system_id,
        "mode": req.mode.upper(),
        "mode_number": mode_num,
    }


# ==========================================================================
# POST /api/guided/velocity
# ==========================================================================

@router.post("/guided/velocity")
async def cmd_guided_velocity(req: GuidedVelocityRequest):
    guided = _require_guided()
    for sysid in req.system_ids:
        logger.info("GUIDED VEL → drone %d vel=(%.1f,%.1f,%.1f) yaw=%.1f",
                    sysid, req.vx, req.vy, req.vz, req.yaw)
        guided.set_velocity_target_local_ned(
            sysid, req.component_id,
            vx=req.vx, vy=req.vy, vz=req.vz, yaw=req.yaw,
        )
    return {
        "status": "ok", "command": "guided_velocity",
        "system_ids": req.system_ids,
        "velocity": {"vx": req.vx, "vy": req.vy, "vz": req.vz},
        "yaw": req.yaw,
    }


# ==========================================================================
# POST /api/rtl — Return To Launch for one or more drones
# ==========================================================================

# MAV_CMD_NAV_RETURN_TO_LAUNCH
_MAV_CMD_NAV_RETURN_TO_LAUNCH = 20


@router.post("/rtl")
async def cmd_rtl(req: SystemIdsRequest):
    """Command Return-To-Launch (RTL) for the given drones."""
    disp = _get_disp()
    for sysid in req.system_ids:
        logger.info("RTL \u2192 drone %d", sysid)
        # MAV_CMD_NAV_RETURN_TO_LAUNCH (20): no parameters required.
        disp._send_command(sysid, req.component_id, _MAV_CMD_NAV_RETURN_TO_LAUNCH)
    return {"status": "ok", "command": "rtl", "system_ids": req.system_ids}


# ==========================================================================
# POST /api/param/request — Request a parameter from the drone
# ==========================================================================

@router.post("/param/request")
async def cmd_param_request(req: ParamRequest):
    """Send PARAM_REQUEST_READ to the drone."""
    conn = _get_conn()
    
    msg = conn.mav.param_request_read_encode(
        req.system_id, req.component_id,
        req.param_id.encode('utf-8'), -1
    )
    frame = msg.pack(conn.mav)
    conn.send(req.system_id, frame)
    logger.info(f"PARAM_REQUEST sent: {req.param_id} to sys={req.system_id}")
    
    return {
        "status": "sent",
        "param_id": req.param_id,
        "system_id": req.system_id
    }


# ==========================================================================
# POST /api/param/request_list — Request all parameters from a component
# ==========================================================================

class ParamListRequest(BaseModel):
    system_id: int = Field(default=1)
    component_id: int = Field(default=1)


@router.post("/param/request_list")
async def cmd_param_request_list(req: ParamListRequest):
    """Send PARAM_REQUEST_LIST to a component (get all parameters)."""
    conn = _get_conn()

    msg = conn.mav.param_request_list_encode(req.system_id, req.component_id)
    frame = msg.pack(conn.mav)
    conn.send(req.system_id, frame)
    logger.info(
        "PARAM_REQUEST_LIST sent: sys=%d comp=%d",
        req.system_id, req.component_id,
    )

    return {
        "status": "sent",
        "system_id": req.system_id,
        "component_id": req.component_id,
        "note": "PARAM_VALUE responses will appear in GCS logs / message router",
    }
