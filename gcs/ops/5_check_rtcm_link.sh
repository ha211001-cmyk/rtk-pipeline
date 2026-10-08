#!/usr/bin/env bash
# gcs/ops/5_check_rtcm_link.sh -- 基地局 TCP の疎通と RTCM3 受信確認（Mac）
# 実体: gcs/rtk_tools/verify_rtcm_tcp.py
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

if [ -f .venv/bin/activate ]; then
  . .venv/bin/activate
fi

exec python3 -m gcs.rtk_tools.verify_rtcm_tcp \
  --host "${RTK_BASE_IP:-192.168.2.1}" \
  --port "${RTK_TCP_PORT:-2101}" \
  --duration "${RTK_CHECK_SECONDS:-30}" \
  "$@"
