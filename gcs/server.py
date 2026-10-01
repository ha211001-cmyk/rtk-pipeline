#!/usr/bin/env python3
"""gcs.server — Multi-Drone Dashboard（Web UI）の単一コマンド起動エントリポイント。

Phase 0 統合計画（§2 / §5）で確定した「GCS-UmemotoLab の Web ダッシュボードを
メイン UI とする」方針に基づき、FastAPI バックエンド（``gcs.app.server:app``）を
uvicorn で起動し、``gcs/web/static/`` の Web UI を配信する。

使い方:
    # 既定（0.0.0.0:8000）
    python3 -m gcs.server

    # ホスト / ポートを変更
    python3 -m gcs.server --host 127.0.0.1 --port 9000

起動後:
    1. ブラウザで http://<host>:<port>/ を開く。
    2. 右上の「Connect」でバックエンド（MAVLink 接続）を初期化する
       （POST /api/connect。設定は gcs/config/ の YAML から自動解決）。
    3. 4 スロットのカードグリッドで最大 4 機を監視し、下部の
       『ALL DRONES』パネルで一斉制御（ARM/DISARM/TAKEOFF/LAND）を行う。

> 注意: Force Arm は屋内テスト専用。実飛行では使用しないこと（README 参照）。
"""

from __future__ import annotations

import argparse
import os
import sys


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, ""))
    except (TypeError, ValueError):
        return default


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="GCS Multi-Drone Dashboard (Web UI) server",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--host", default=os.environ.get("GCS_HOST", "0.0.0.0"))
    p.add_argument("--port", type=int, default=_env_int("GCS_PORT", 8000))
    p.add_argument("--log-level", default=os.environ.get("GCS_LOG_LEVEL", "info"))
    p.add_argument("--reload", action="store_true", help="uvicorn auto-reload（開発用）")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    import uvicorn

    print(f"[gcs.server] starting Web dashboard on http://{args.host}:{args.port} ...")
    uvicorn.run(
        "gcs.app.server:app",
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        reload=args.reload,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
