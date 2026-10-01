"""gcs.app.operations.manager — 運用操作のバックグラウンド実行・状態管理。

操作（設定・監視・ロギング・基地局/注入）をバックグラウンドスレッドで実行し、
PASS/FAIL/進捗/ログ/停止要求をスレッドセーフに管理する。

設計方針:
- 各操作は ``Job`` に紐づき、``handlers`` が ``JobContext`` を通じて
  進捗（``progress``）とログ（``log``）を報告する。
- 停止要求は ``Job.stop_event``（``threading.Event``）で伝搬し、
  ハンドラは ``stop_requested()`` を定期チェックして ``OperationStopped`` を
  送出する（またはサービス系は停止フラグを監視して正常復帰する）。
- 実行は ``OperationManager`` が生成する daemon スレッドで行い、
  REST 層（``gcs.app.api.operations``）からは ``start/stop/get/snapshot``
  を呼ぶだけで良い。
"""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional

STATUS_PENDING = "PENDING"
STATUS_RUNNING = "RUNNING"
STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_STOPPED = "STOPPED"

_TERMINAL_STATUSES = {STATUS_PASS, STATUS_FAIL, STATUS_STOPPED}

# ジョブあたりのログ保持行数（画面反映用・無限増加を防ぐ）
_MAX_LOG_LINES = 500

# ハンドラ関数シグネチャ: Callable[[JobContext, Dict[str, Any]], Any]
Handler = Callable[["JobContext", Dict[str, Any]], Any]


class OperationStopped(Exception):
    """停止要求により操作が中断されたことを表す内部例外。"""


class JobContext:
    """ハンドラへ渡す実行コンテキスト（進捗報告・ログ・停止要求の受け口）。"""

    def __init__(self, job: "Job") -> None:
        self._job = job

    @property
    def stop_event(self) -> threading.Event:
        return self._job.stop_event

    def stop_requested(self) -> bool:
        return self._job.stop_event.is_set()

    def log(self, message: Any) -> None:
        self._job.add_log(message)

    def progress(self, percent: Optional[float], message: Optional[str] = None) -> None:
        """進捗（0..100、None なら不定）と任意メッセージを更新する。"""
        self._job.set_progress(percent, message)


class Job:
    """1 回の操作実行を表す。"""

    def __init__(self, job_id: str, op_id: str, params: Dict[str, Any]) -> None:
        self.id = job_id
        self.op_id = op_id
        self.params = dict(params or {})
        self.status = STATUS_PENDING
        self.progress: Optional[float] = None
        self.message: str = ""
        self.result: Any = None
        self.error: Optional[str] = None
        self.started_at: Optional[float] = None
        self.finished_at: Optional[float] = None
        self.stop_event = threading.Event()
        self._logs: Deque[Dict[str, Any]] = deque(maxlen=_MAX_LOG_LINES)
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    def add_log(self, message: Any) -> None:
        with self._lock:
            self._logs.append({
                "t": time.strftime("%H:%M:%S"),
                "msg": str(message),
            })

    def set_progress(self, percent: Optional[float], message: Optional[str] = None) -> None:
        with self._lock:
            self.progress = percent
            if message is not None:
                self.message = str(message)

    def is_terminal(self) -> bool:
        return self.status in _TERMINAL_STATUSES

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "id": self.id,
                "op_id": self.op_id,
                "status": self.status,
                "progress": self.progress,
                "message": self.message,
                "result": self.result,
                "error": self.error,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "logs": list(self._logs),
            }



class OperationManager:
    """操作カタログと実行中ジョブのレジストリ。"""

    def __init__(self) -> None:
        self._ops: Dict[str, Dict[str, Any]] = {}
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Catalog
    # ------------------------------------------------------------------
    def register(
        self,
        op_id: str,
        handler: Handler,
        *,
        category: str,
        label: str,
        description: str = "",
        params: Optional[List[Dict[str, Any]]] = None,
        dangerous: bool = False,
        mode: str = "job",  # "job"（単発）| "service"（start 後も RUNNING を維持）
    ) -> None:
        self._ops[op_id] = {
            "id": op_id,
            "category": category,
            "label": label,
            "description": description,
            "params": params or [],
            "dangerous": dangerous,
            "mode": mode,
            "handler": handler,
        }

    def catalog(self) -> List[Dict[str, Any]]:
        """UI 描画用の操作カタログ（handler は含めない）。"""
        with self._lock:
            return [
                {k: v for k, v in meta.items() if k != "handler"}
                for meta in self._ops.values()
            ]

    def has(self, op_id: str) -> bool:
        return op_id in self._ops

    # ------------------------------------------------------------------
    # Job lifecycle
    # ------------------------------------------------------------------
    def start(self, op_id: str, params: Optional[Dict[str, Any]] = None) -> str:
        """操作を開始し、ジョブ ID を返す。"""
        with self._lock:
            if op_id not in self._ops:
                raise KeyError("unknown operation: %s" % op_id)
            job_id = uuid.uuid4().hex[:12]
            job = Job(job_id, op_id, params or {})
            self._jobs[job_id] = job

        job._thread = threading.Thread(
            target=self._run, args=(job,), daemon=True, name="op:%s" % op_id
        )
        job._thread.start()
        return job_id

    def _run(self, job: Job) -> None:
        meta = self._ops[job.op_id]
        handler: Handler = meta["handler"]
        job.started_at = time.time()
        job.status = STATUS_RUNNING
        job.add_log("[START] %s (%s)" % (meta["label"], job.op_id))

        ctx = JobContext(job)
        try:
            result = handler(ctx, dict(job.params))
            with job._lock:
                # 停止済みでなければ成功扱い（handler 内で停止は OperationStopped で表現）
                if job.status == STATUS_RUNNING:
                    job.status = STATUS_PASS
                job.result = result
            job.add_log("[DONE] %s" % (meta["label"]))
        except OperationStopped:
            with job._lock:
                job.status = STATUS_STOPPED
                job.result = {"stopped": True}
            job.add_log("[STOPPED] %s" % (meta["label"]))
        except Exception as exc:  # noqa: BLE001 - 実行時エラーはジョブへ集約
            with job._lock:
                job.status = STATUS_FAIL
                job.error = str(exc)
            job.add_log("[FAIL] %s: %s" % (meta["label"], exc))
            job.add_log(traceback.format_exc())
        finally:
            job.finished_at = time.time()

    def stop(self, job_id: str) -> bool:
        """実行中ジョブへ停止要求を送る。存在しない/終了済みなら False。"""
        job = self._jobs.get(job_id)
        if job is None or job.is_terminal():
            return False
        job.stop_event.set()
        job.add_log("[STOP] stop requested")
        return True

    def clear(self, job_id: str) -> bool:
        """終了済みジョブをレジストリから除去する。"""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            if not job.is_terminal():
                return False
            del self._jobs[job_id]
            return True

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        job = self._jobs.get(job_id)
        return job.to_dict() if job else None

    def list_jobs(self) -> List[Dict[str, Any]]:
        with self._lock:
            jobs = list(self._jobs.values())
        # 開始時刻の昇順で返す（古い順）
        jobs.sort(key=lambda j: j.started_at or 0)
        return [j.to_dict() for j in jobs]

    def snapshot(self) -> Dict[str, Any]:
        """WebSocket ブロードキャスト用の軽量スナップショット。"""
        jobs = self.list_jobs()
        return {
            "active": sum(1 for j in jobs if j["status"] == STATUS_RUNNING),
            "total": len(jobs),
            "jobs": [
                {
                    "id": j["id"],
                    "op_id": j["op_id"],
                    "status": j["status"],
                    "progress": j["progress"],
                    "message": j["message"],
                    "error": j["error"],
                }
                for j in jobs
            ],
        }
