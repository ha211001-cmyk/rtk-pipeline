#!/usr/bin/env bash
# gcs/ops/2_start_web_gcs.sh -- Web GCS ダッシュボードの起動（Mac）
# 実体: gcs/server.py（uvicorn で gcs.app.server:app を起動）
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

if [ -f .venv/bin/activate ]; then
  . .venv/bin/activate
fi

PORT="${GCS_PORT:-9000}"
echo "[ops] Web GCS: http://localhost:$PORT"
exec python3 -m gcs.server --port "$PORT" "$@"
