#!/bin/bash

# エラーが発生した時点でスクリプトを終了する
set -e

echo "======================================"
echo "  RTK Data Analysis Pipeline Started  "
echo "======================================"

echo "[1/4] Running analyze_rtk.py..."
python3 analyze_rtk.py

echo "[2/4] Running evaluate_rtk.py..."
python3 evaluate_rtk.py

echo "[3/4] Running generate_report.py..."
python3 generate_report.py

echo "[4/4] Running plot_histograms.m via MATLAB..."
# MATLABをCUIでバッチ実行する (R2019a以降でサポート)
if command -v matlab &> /dev/null; then
    matlab -batch "plot_histograms"
    echo "[Success] MATLAB script completed."
else
    echo "[Warning] 'matlab' コマンドが見つかりませんでした。"
    echo "          パスが通っていないか、MATLABがインストールされていません。"
    echo "          Macの場合、例: /Applications/MATLAB_R2023b.app/bin/matlab のように"
    echo "          フルパスを指定するか、環境変数にパスを追加してください。"
fi

echo "======================================"
echo "   Pipeline Completed Successfully!   "
echo "======================================"
