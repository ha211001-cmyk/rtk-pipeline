"""gcs/app/api/operations.py — 運用操作の REST API + WebSocket。

``OperationManager`` をシングルトンとして保持し、以下を提供する:

- ``GET  /api/ops``                 操作カタログ（カテゴリ・パラメータ・危険フラグ）
- ``POST /api/ops/{op_id}/start``   操作開始（job_id を返す）
- ``GET  /api/ops/jobs``            ジョブ一覧
- ``GET  /api/ops/jobs/{job_id}``   ジョブ詳細（PASS/FAIL/進捗/ログ）
- ``POST /api/ops/jobs/{job_id}/stop``   停止要求
- ``DELETE /api/ops/jobs/{job_id}`` 終了済みジョブの除去
- ``WS   /ws/ops``                  ジョブ状態の 1Hz ブロードキャスト

制御系（アーム/離陸/Guided/RTL 等）は ``routes.py`` の既存エンドポイントが担当。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional, Set

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from gcs.app.operations.handlers import register_operations
from gcs.app.operations.manager import OperationManager

logger = logging.getLogger("api.operations")

router = APIRouter(prefix="/api/ops", tags=["operations"])
ws_router = APIRouter()  # /ws/ops（prefix なし）

# シングルトン（モジュール import 時に構築）
_manager = OperationManager()
register_operations(_manager)

# WebSocket クライアント管理
_active_clients: Set[WebSocket] = set()


def get_manager() -> OperationManager:
    return _manager


# ---------------------------------------------------------------------------
# REST: カタログ・ジョブ
# ---------------------------------------------------------------------------
@router.get("")
async def list_operations():
    return {"operations": _manager.catalog()}


class StartRequest(BaseModel):
    params: Dict[str, Any] = Field(default_factory=dict)


@router.post("/{op_id}/start")
async def start_operation(op_id: str, req: StartRequest):
    if not _manager.has(op_id):
        raise HTTPException(status_code=404, detail="unknown operation: %s" % op_id)
    try:
        job_id = _manager.start(op_id, req.params)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "started", "job_id": job_id, "op_id": op_id}


@router.get("/jobs")
async def list_jobs():
    return {"jobs": _manager.list_jobs()}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = _manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found: %s" % job_id)
    return job


@router.post("/jobs/{job_id}/stop")
async def stop_job(job_id: str):
    ok = _manager.stop(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="job not running: %s" % job_id)
    return {"status": "stop_requested", "job_id": job_id}


@router.delete("/jobs/{job_id}")
async def clear_job(job_id: str):
    ok = _manager.clear(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="job not finished: %s" % job_id)
    return {"status": "cleared", "job_id": job_id}


# ---------------------------------------------------------------------------
# WebSocket: /ws/ops（1Hz ブロードキャスト）
# ---------------------------------------------------------------------------
@ws_router.websocket("/ws/ops")
async def ops_websocket(ws: WebSocket):
    await ws.accept()
    _active_clients.add(ws)
    logger.info("WS client connected (ops). Total: %d", len(_active_clients))
    try:
        while True:
            try:
                await asyncio.wait_for(ws.receive_text(), timeout=1.0)
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        logger.info("WS client disconnected (ops)")
    except Exception as e:  # noqa: BLE001
        logger.error("WS ops error: %s", e)
    finally:
        _active_clients.discard(ws)


async def broadcast_ops_loop():
    """1Hz で操作ジョブ状態を全クライアントへ配信する。"""
    global _active_clients
    while True:
        await asyncio.sleep(1.0)
        if not _active_clients:
            continue
        try:
            payload = json.dumps({"type": "ops", **_manager.snapshot()}, default=str)
            dead: Set[WebSocket] = set()
            for ws in _active_clients:
                try:
                    await ws.send_text(payload)
                except Exception:  # noqa: BLE001
                    dead.add(ws)
            _active_clients -= dead
        except Exception as e:  # noqa: BLE001
            logger.error("ops broadcast error: %s", e)
