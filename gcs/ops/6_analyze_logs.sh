#!/usr/bin/env bash
# gcs/ops/6_analyze_logs.sh -- 取得済み CSV の事後解析（Mac）
# 実体: gcs/analyze_fix_log.py
# 使い方: bash gcs/ops/6_analyze_logs.sh <CSV> [--json out.json]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

if [ -f .venv/bin/activate ]; then
  . .venv/bin/activate
fi

if [ "$#" -eq 0 ]; then
  echo "usage: $0 <fix_type CSV> [--json out.json]" >&2
  exit 2
fi

exec python3 -m gcs.analyze_fix_log "$@"
