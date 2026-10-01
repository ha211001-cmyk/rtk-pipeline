#!/usr/bin/env python3
"""test_operations_ws.py — /ws/ops ブロードキャストループの退行テスト（実機不要）。

broadcast_ops_loop が module 変数 _active_clients を参照する際、augmented
assignment（-=）によりローカル変数扱いになり UnboundLocalError になる退行を
防止する（global 宣言の有無を動作で確認する）。
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gcs.app.api.operations import broadcast_ops_loop  # noqa: E402


def _run_briefly() -> None:
    async def _inner() -> None:
        task = asyncio.create_task(broadcast_ops_loop())
        await asyncio.sleep(2.5)  # ループを 2 回以上回す
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(_inner())


class TestBroadcastOpsLoop(unittest.TestCase):
    def test_loop_runs_without_unbound_error(self):
        # 例外が発生しなければ OK（UnboundLocalError はここで捕捉される）
        try:
            _run_briefly()
        except UnboundLocalError as exc:  # pragma: no cover - 退行検知
            self.fail(f"broadcast_ops_loop で UnboundLocalError: {exc}")


if __name__ == "__main__":
    unittest.main()
