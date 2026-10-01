"""
gcs/app/api/rtk_state.py — Thread-safe shared state for RTK monitoring data.

Provides decoupling between RTK data producers (rtk_forwarder_service,
F9pFixMonitor, rtk_direct_inject) and the FastAPI WebSocket layer.

Producers update state via update_* functions (no FastAPI dependency).
Consumers read via get_* functions (thread-safe snapshots).

Usage:
    from gcs.app.api.rtk_state import update_fix_state, get_fix_state
    from gcs.app.api.rtk_state import update_forwarder_stats, get_forwarder_stats
"""

import threading
import time
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Forwarder statistics (rtk_forwarder_service serial output stats)
# ---------------------------------------------------------------------------
_forwarder_stats: Dict[str, Any] = {}
_forwarder_lock = threading.Lock()


def update_forwarder_stats(stats: Dict[str, Any]) -> None:
    """Update RTK forwarder statistics (thread-safe).

    Called by rtk_forwarder_service or rtk_direct_inject when it has
    new stats to report (e.g. total_packets, total_bytes, forward_type,
    serial_port).
    """
    global _forwarder_stats
    with _forwarder_lock:
        _forwarder_stats = dict(stats)
        _forwarder_stats["last_update"] = time.time()


def get_forwarder_stats() -> Optional[Dict[str, Any]]:
    """Return a snapshot of current forwarder stats, or None if never set."""
    with _forwarder_lock:
        if not _forwarder_stats:
            return None
        return dict(_forwarder_stats)


# ---------------------------------------------------------------------------
# F9P Fix state (UBX-NAV-PVT carrSoln, fixType, accuracy, position)
# ---------------------------------------------------------------------------
_fix_state: Dict[str, Any] = {}
_fix_lock = threading.Lock()


def update_fix_state(state: Optional[Dict[str, Any]]) -> None:
    """Update F9P fix state from NAV-PVT poll (thread-safe).

    Called by F9pFixMonitor.get_fix_status_stream() callback whenever
    a new NAV-PVT message is received. Pass None to clear the state.
    """
    global _fix_state
    with _fix_lock:
        if state is None:
            _fix_state = {}
        else:
            _fix_state = dict(state)
            _fix_state["last_update"] = time.time()


def get_fix_state() -> Optional[Dict[str, Any]]:
    """Return a snapshot of current F9P fix state, or None if never set."""
    with _fix_lock:
        if not _fix_state:
            return None
        return dict(_fix_state)
