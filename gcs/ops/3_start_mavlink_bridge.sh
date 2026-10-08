#!/usr/bin/env bash
# gcs/ops/3_start_mavlink_bridge.sh -- MAVLink 中継・RTCM 注入の起動（Raspberry Pi 5）
# 実体: gcs/rtk_tools/mavlink_bridge.py
# 注: 実体の CSV / .rtcm3 書き出しは現在コメントアウトされています（Logging Disabled）。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

PY=python3
if [ -x "$HOME/Mavlink_venv/bin/python3" ]; then
  PY="$HOME/Mavlink_venv/bin/python3"
fi

echo "[ops] python : $PY"
echo "[ops] 実体   : gcs/rtk_tools/mavlink_bridge.py"
exec "$PY" gcs/rtk_tools/mavlink_bridge.py \
  --serial "${RTK_SERIAL:-/dev/ttyAMA0}" \
  --baud "${RTK_BAUD:-921600}" \
  --target-host "${GCS_HOST_IP:-192.168.2.1}" \
  --rtcm-host "${RTK_BASE_IP:-192.168.2.1}" \
  "$@"
