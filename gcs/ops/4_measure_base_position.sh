#!/usr/bin/env bash
# gcs/ops/4_measure_base_position.sh -- 基地局アンテナ位置の実測（Mac）
# 実体: single_unit_test/run_survey.py
# 出力の「平均高度（楕円体高 HAE）」を gcs/config/base_station.json の fixed_alt に使います。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

if [ -f .venv/bin/activate ]; then
  . .venv/bin/activate
fi

echo "[ops] 実体: single_unit_test/run_survey.py（--set-rover --duration 120 --save）"
exec python3 single_unit_test/run_survey.py --set-rover --duration 120 --save "$@"
