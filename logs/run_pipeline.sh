#!/bin/bash

set -e

if [ -z "$1" ]; then
  echo "使い方: ./run_pipeline.sh <ターゲットフォルダ名>"
  echo "例: ./run_pipeline.sh 20261001_181637"
  exit 1
fi

TARGET_DIR="$1"

if [ ! -d "$TARGET_DIR" ]; then
  echo "エラー: フォルダ '$TARGET_DIR' が見つかりません。"
  exit 1
fi

export TARGET_DIR

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
export TIMESTAMP


echo "======================================"
echo "  RTK Data Analysis Pipeline Started  "
echo "  Target: $TARGET_DIR"
echo "======================================"

echo "[1/4] Running analyze_rtk.py..."
python3 analyze_rtk.py "$TARGET_DIR" "$TIMESTAMP"

echo "[2/4] Running evaluate_rtk.py..."
python3 evaluate_rtk.py "$TARGET_DIR" "$TIMESTAMP"

echo "[3/4] Running generate_report.py..."
python3 generate_report.py "$TARGET_DIR" "$TIMESTAMP"

echo "[4/4] Running plot_histograms.m via MATLAB..."
if command -v matlab &> /dev/null; then
    matlab -batch "plot_histograms"
    echo "[Success] MATLAB script completed."
elif [ -x "/Applications/MATLAB_R2026b.app/bin/matlab" ]; then
    /Applications/MATLAB_R2026b.app/bin/matlab -batch "plot_histograms"
    echo "[Success] MATLAB script completed."
else
    echo "[Warning] 'matlab' コマンドが見つかりませんでした。"
fi

echo "======================================"
echo "   Pipeline Completed Successfully!   "
echo "======================================"

