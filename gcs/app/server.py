"""
GCS-UmemotoLab FastAPI Server Entry Point.

Startup (lightweight):
  1. Configure logging
  2. Start WebSocket broadcast loops (no-op until backend connected)

Backend components (MavlinkConnection, TelemetryStore, etc.) are initialized
on-demand via POST /api/connect and torn down via POST /api/disconnect.

Bind address: 0.0.0.0:8000
"""

import asyncio
import logging
import os

from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn

# -- Import the existing FastAPI app from api.server ---------------------
from gcs.app.api.server import app, init_api, broadcast_telemetry

# -- Import the enhanced WebSocket router --------------------------------
from gcs.app.api.websocket import router as ws_router, broadcast_loop

# -- Import the REST API command router ----------------------------------
from gcs.app.api.routes import router as cmd_router

# -- Import the operations (settings/monitoring/logging/base) router -----
from gcs.app.api.operations import (
    router as ops_router,
    ws_router as ops_ws_router,
    broadcast_ops_loop,
)

# -- Static files mount --------------------------------------------------
# 本ファイルは gcs/app/server.py にあるため、2 階層上が gcs/ になる。
# Web UI の静的ファイルは gcs/web/static/ に配備する（Phase 0 統合計画 §5）。
_GCS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STATIC_DIR = os.path.join(_GCS_ROOT, "web", "static")

# -- CORS middleware (allow Tailscale + local access) ---------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if os.path.isdir(_STATIC_DIR):
    try:
        app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
    except RuntimeError:
        pass  # Already mounted


# -- WebSocket router ----------------------------------------------------
app.include_router(ws_router)

# -- REST API command router ---------------------------------------------
app.include_router(cmd_router)

# -- Operations router (settings/monitoring/logging/base/injection) -------
app.include_router(ops_router)
app.include_router(ops_ws_router)  # /ws/ops

logger = logging.getLogger("server")


# =========================================================================
#  Startup / Shutdown lifecycle
# =========================================================================

@app.on_event("startup")
async def on_startup():
    """Lightweight startup: logging only. Backend initialized via /api/connect."""
    from gcs.app.logging_config import setup_logging
    setup_logging()
    global logger
    logger = logging.getLogger("server")
    logger.info("=== GCS Web Server starting (lightweight) ===")

    # Start broadcast loops immediately (they no-op when backend is None)
    asyncio.create_task(broadcast_telemetry())   # existing 0.5s loop
    asyncio.create_task(broadcast_loop())         # enhanced 1s loop
    asyncio.create_task(broadcast_ops_loop())     # operations 1s loop

    logger.info("=== GCS Web Server started (0.0.0.0:8000) ===\n"
                "    Backend not connected. Use POST /api/connect to connect.")


@app.on_event("shutdown")
async def on_shutdown():
    """Cleanup all components."""
    logger.info("Shutting down...")

    if hasattr(app.state, "router"):
        try:
            app.state.router.stop()
        except Exception as e:
            logger.warning(f"router.stop() failed: {e}")
    if hasattr(app.state, "mav_conn"):
        try:
            app.state.mav_conn.stop()
        except Exception as e:
            logger.warning(f"mav_conn.stop() failed: {e}")
    logger.info("=== Server shutdown complete ===")


# =========================================================================
#  Main
# =========================================================================

if __name__ == "__main__":
    uvicorn.run(
        "gcs.app.server:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
        reload=False,
    )
