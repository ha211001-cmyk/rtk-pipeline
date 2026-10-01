#!/usr/bin/env python3
"""test_manager.py — OperationManager のユニットテスト（ハードウェア不要）。"""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gcs.app.operations.manager import (  # noqa: E402
    OperationManager,
    OperationStopped,
    STATUS_PASS,
    STATUS_FAIL,
    STATUS_STOPPED,
    STATUS_RUNNING,
)


def _wait(job_id, predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = _MGR.get(job_id)
        if predicate(job):
            return job
        time.sleep(0.02)
    return _MGR.get(job_id)


_MGR = None


class TestOperationManager(unittest.TestCase):
    def setUp(self):
        global _MGR
        _MGR = OperationManager()
        _MGR.register(
            "ok_op", lambda ctx, p: {"done": True},
            category="test", label="OK op",
        )
        _MGR.register(
            "fail_op", lambda ctx, p: (_ for _ in ()).throw(RuntimeError("boom")),
            category="test", label="Fail op",
        )
        _MGR.register(
            "stop_op",
            lambda ctx, p: _blocking(ctx, p),
            category="test", label="Stop op", mode="service",
        )

    def test_catalog(self):
        cat = _MGR.catalog()
        self.assertEqual(len(cat), 3)
        self.assertTrue(all("handler" not in c for c in cat))

    def test_success(self):
        jid = _MGR.start("ok_op", {"a": 1})
        job = _wait(jid, lambda j: j["status"] in (STATUS_PASS, STATUS_FAIL))
        self.assertEqual(job["status"], STATUS_PASS)
        self.assertEqual(job["result"], {"done": True})

    def test_failure(self):
        jid = _MGR.start("fail_op", {})
        job = _wait(jid, lambda j: j["status"] == STATUS_FAIL)
        self.assertEqual(job["status"], STATUS_FAIL)
        self.assertIn("boom", job["error"])

    def test_stop(self):
        jid = _MGR.start("stop_op", {})
        job = _wait(jid, lambda j: j["status"] == STATUS_RUNNING)
        self.assertEqual(job["status"], STATUS_RUNNING)
        self.assertTrue(_MGR.stop(jid))
        job = _wait(jid, lambda j: j["status"] == STATUS_STOPPED)
        self.assertEqual(job["status"], STATUS_STOPPED)

    def test_unknown_op(self):
        with self.assertRaises(KeyError):
            _MGR.start("nope", {})

    def test_clear(self):
        jid = _MGR.start("ok_op", {})
        _wait(jid, lambda j: j["status"] == STATUS_PASS)
        self.assertTrue(_MGR.clear(jid))
        self.assertIsNone(_MGR.get(jid))


def _blocking(ctx, params):
    while not ctx.stop_requested():
        time.sleep(0.02)
    raise OperationStopped()


if __name__ == "__main__":
    unittest.main()
