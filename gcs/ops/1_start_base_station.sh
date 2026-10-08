#!/usr/bin/env bash
# gcs/ops/1_start_base_station.sh -- 基地局 RTCM 配信の起動（Mac）
# 実体: gcs/rtk_tools/rtk_base_station_v2.py
# 追加引数はそのまま実体へ渡されます（例: --tcp-port 2102 --skip-f9p-config）
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

CONFIG="${RTK_BASE_CONFIG:-gcs/config/base_station.json}"

if [ -f .venv/bin/activate ]; then
  . .venv/bin/activate
fi

echo "[ops] repo   : $REPO_ROOT"
echo "[ops] config : $CONFIG"
echo "[ops] 実体   : gcs/rtk_tools/rtk_base_station_v2.py"

if [ -n "${RTK_SERIAL_PORT:-}" ]; then
  exec python3 gcs/rtk_tools/rtk_base_station_v2.py --config "$CONFIG" --serial-port "$RTK_SERIAL_PORT" "$@"
fi

exec python3 gcs/rtk_tools/rtk_base_station_v2.py --config "$CONFIG" "$@"
