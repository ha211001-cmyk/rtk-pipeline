#!/bin/bash

# ==============================================================================
# ローカルの変更を GitHub にプッシュし、Raspberry Pi でデプロイ・実行・検証を行うスクリプト。
# ==============================================================================

# 引数の初期値
SCRIPT=""
TIMEOUT_SEC=30
COMMIT_MESSAGE="update: auto deploy"

# ヘルプ表示関数
usage() {
    echo "Usage: $0 -s <script_name> [-t <timeout_sec>] [-m <commit_message>]"
    echo "Example: $0 -s gps_display.py -t 30 -m 'fix: バグ修正'"
    exit 1
}

# 引数のパース
while getopts "s:t:m:h" opt; do
    case $opt in
        s) SCRIPT="$OPTARG" ;;
        t) TIMEOUT_SEC="$OPTARG" ;;
        m) COMMIT_MESSAGE="$OPTARG" ;;
        h) usage ;;
        \?) usage ;;
    esac
done

if [ -z "$SCRIPT" ]; then
    echo "Error: -s <script_name> is required."
    usage
fi

REPO_ROOT="/Users/taitai0123/rtk-pipeline"
RASPI_HOST="taki@172.20.10.2"
RASPI_REPO="~/rtk-pipeline"
RASPI_SCRIPT="$RASPI_REPO/raspberrypi/$SCRIPT"
VENV_PYTHON="$RASPI_REPO/.venv/bin/python3"

# ログ出力関数
write_step() {
    echo ""
    echo -e "\033[1;36m=== Step $1: $2 ===\033[0m"
}
write_success() { echo -e "\033[1;32m[OK] $1\033[0m"; }
write_fail() { echo -e "\033[1;31m[NG] $1\033[0m"; }
write_info() { echo -e "\033[1;33m[..] $1\033[0m"; }

# ============================================================
# Step 1: ローカルの変更をコミット・プッシュ
# ============================================================
write_step 1 "ローカル変更を GitHub へプッシュ"

cd "$REPO_ROOT" || { write_fail "Directory $REPO_ROOT not found"; exit 1; }

if [ -n "$(git status --porcelain)" ]; then
    write_info "変更ファイルを検出。コミットします..."
    git add .
    git commit -m "$COMMIT_MESSAGE"
    if [ $? -ne 0 ]; then write_fail "git commit に失敗しました"; exit 1; fi
else
    write_info "作業ツリーはクリーン。プッシュのみ実行します。"
fi

git push
if [ $? -ne 0 ]; then write_fail "git push に失敗しました"; exit 1; fi
write_success "プッシュ完了"

# ============================================================
# Step 2: Raspberry Pi で git pull
# ============================================================
write_step 2 "Raspberry Pi で git pull"

PULL_OUTPUT=$(ssh "$RASPI_HOST" "cd $RASPI_REPO && git pull 2>&1")
echo "$PULL_OUTPUT"

if echo "$PULL_OUTPUT" | grep -Eq "error:|fatal:"; then
    write_fail "git pull 中にエラーが発生しました"
    exit 1
fi
write_success "git pull 完了"

# ============================================================
# Step 3: 仮想環境でスクリプトを実行
# ============================================================
write_step 3 "仮想環境を有効化してスクリプトを実行 (timeout: ${TIMEOUT_SEC}s)"

write_info "実行コマンド: timeout $TIMEOUT_SEC $VENV_PYTHON $RASPI_SCRIPT"

echo ""
echo -e "\033[1;35m--- 実行出力 ---\033[0m"
# timeout 終了時のステータスコードをキャプチャするために set -e は無効のまま実行
RUN_OUTPUT=$(ssh "$RASPI_HOST" "cd $RASPI_REPO/raspberrypi && timeout $TIMEOUT_SEC $VENV_PYTHON $SCRIPT 2>&1")
RUN_EXIT_CODE=$?
echo "$RUN_OUTPUT"
echo -e "\033[1;35m--- 出力終了 ---\033[0m"

# ============================================================
# Step 4: 結果を検証
# ============================================================
write_step 4 "実行結果の検証"

HAS_ERROR=$(echo "$RUN_OUTPUT" | grep -E "Traceback|Error:|Exception:|CRITICAL")
HAS_WARNING=$(echo "$RUN_OUTPUT" | grep -E "Warning:|WARN")
# SSH経由のtimeout終了コードは124になることが多い
IS_TIMEOUT=$([ $RUN_EXIT_CODE -eq 124 ] || echo "$RUN_OUTPUT" | grep -q "Killed" && echo "true" || echo "false")

if [ "$IS_TIMEOUT" = "true" ]; then
    write_info "タイムアウト終了 (正常動作の可能性あり。出力を確認してください)"
fi

if [ -n "$HAS_ERROR" ]; then
    write_fail "エラーが検出されました。出力を確認してコードを修正してください。"
    echo ""
    echo -e "\033[1;31m検出エラー行:\033[0m"
    echo "$RUN_OUTPUT" | grep -E "Traceback|Error:|Exception:|CRITICAL" | while read -r line; do
        echo -e "\033[1;31m  $line\033[0m"
    done
    exit 2
elif [ -n "$HAS_WARNING" ]; then
    write_info "警告が検出されました (実行は継続できる可能性があります)"
    write_success "デプロイ・実行完了 (警告あり)"
    exit 0
else
    write_success "エラーなし。デプロイ・実行完了"
    exit 0
fi
