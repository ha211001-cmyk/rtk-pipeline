---
name: raspi-debug
description: "コードを編集してRaspberry Piでデバッグするワークフロー。使用するとき: コードに変更を加えた後にRaspberry Pi (taki@172.20.10.2) へデプロイして実行・検証したいとき。gh cli でプッシュ → SSH でgit pull → 仮想環境(.venv)で実行 → 結果を検証 → エラーがあれば再編集してループというサイクルを自動化する。'デプロイ', 'ラズパイで実行', 'Raspberry Piでテスト', 'raspi debug', 'deploy and test' などのフレーズで呼び出される。"
argument-hint: "実行するPythonスクリプト名 (例: gps_display.py)"
---

# raspi-debug スキル

Raspberry Pi 5 (taki@172.20.10.2) へのデプロイ・実行・検証サイクルを自動化するスキルです。

## 対象環境

| 項目 | 値 |
|------|-----|
| Raspberry Pi ホスト | `taki@172.20.10.2` |
| リポジトリパス (raspi) | `~/rtk-pipeline` |
| 仮想環境 | `~/rtk-pipeline/.venv` |
| 対象スクリプトディレクトリ | `~/rtk-pipeline/raspberrypi/` |
| ローカルリポジトリ | `/Users/taitai0123/rtk-pipeline` |

## 確認済み環境情報

| 項目 | 値 |
|------|-----|
| F9P デバイス | `/dev/ttyACM0` (USB接続) |
| ボーレート | `38400` |
| `dialout` グループ | `taki` 所属済み（権限OK） |
| 仮想環境状態 | `~/rtk-pipeline/.venv` 作成済み |
| インストール済みパッケージ | pyserial, pynmeagps, pyubx2, pyrtcm, numpy |
| 単独測位（gps_display.py） | **動作確認済み** - DGPS Fix、衛星12個、HDOP:0.57 |
| NTRIP（イチミル:2101） | **ポートブロック中** - ラズパイ・Windows両方からタイムアウト |
| NTRIP キャスター（ntrip_caster.py） | **動作確認済み** - ローカル NTRIP 配信成功、172.20.10.2:2101 |
| RTCM3 基地局（base_station.py） | **動作確認済み** - MSG 1005/1077/1087/1097/1127/1230 全出力 |

## NTRIP ポートブロック問題

### 現状
- `ntrip.ales-corp.co.jp:2101` (IP: 52.199.90.201) への接続が **タイムアウト**
- `rtk2go.com:2101` も同様にNG → ポート2101自体がブロックされている
- ルーター: `192.168.11.1`、デフォルトゲートウェイ

### ローカル NTRIP キャスター（解決策・実装済み）

`raspberrypi/ntrip_caster.py` でラズパイ自体が NTRIP サーバーとして機能:
- 接続先: `172.20.10.2:2101 / F9P_BASE`（認証不要）
- RTCM3 配信: MSG 1005(1Hz), 1077/1087/1097/1127(5Hz), 1230(1Hz)
- 起動コマンド: `python3 ntrip_caster.py`

### TMODE3 Fixed Mode の注意点
- **TMODE3 payload は 40 bytes 必須**（32 bytes だと NAK される）
- **2 ステップ設定が必要**: `Disabled(mode=0)` → `Fixed(mode=2)` の順に送る
- **3 秒の安定待ち** が必要（F9P が内部モード切替に時間がかかる）
- **CFG-CFG で Flash 保存** すること（RAM のみだと接続切断後に MSG 1005 が出なくなる）
- CFG-TMODE3 ポールで `Fixed / LLH` 確認済み

## 初回セットアップ（.venv 未作成の場合）

```bash
ssh taki@172.20.10.2 "cd ~/rtk-pipeline && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
```

> **注意**: ログイン時に `(Mavlink_venv)` が有効になっていても、rtk-pipeline 実行時は `~/rtk-pipeline/.venv` を使う。Mavlink_venv への `deactivate` は SSH 経由実行では不要。

## ワークフロー手順

### ステップ 1: 変更をプッシュ

```bash
cd /Users/taitai0123/rtk-pipeline
git add .
git commit -m "<変更内容を簡潔に記述>"
git push
```

> **注意**: `gh pr create` は main ブランチへの直接プッシュなので不要。`git push` のみで OK。

### ステップ 2: Raspberry Pi で git pull

以下のコマンドを `run_in_terminal` で実行:

```bash
ssh taki@172.20.10.2 "cd ~/rtk-pipeline && git pull"
```

出力に `Already up to date.` または変更ファイルのリストが表示されることを確認。

### ステップ 3: Raspberry Pi で仮想環境を有効化してスクリプトを実行

```bash
ssh taki@172.20.10.2 "cd ~/rtk-pipeline/raspberrypi && source ../.venv/bin/activate && timeout 30 python3 <スクリプト名>.py 2>&1"
```

- `timeout 30` は30秒間実行して終了（通信系スクリプトは無限ループのため）
- 実行時間が長い場合は `timeout` の秒数を調整
- 常時稼働スクリプトは `timeout` を外して `Ctrl+C` で手動停止

### ステップ 4: 結果を検証

出力を解析して以下を確認:

1. **Pythonエラー** (`Traceback`, `Error:`, `Exception`) → エラー箇所を特定
2. **接続エラー** (`Connection refused`, `timeout`, `No such file`) → 設定値を確認
3. **正常動作の確認** (期待するログ・データが出力されているか)
4. **警告** (`Warning`, `DeprecationWarning`) → 必要に応じて対処

### ステップ 5: 判定

- **問題なし** → ワークフロー完了
- **コードのバグ** → ローカルでコードを修正してステップ1に戻る
- **環境の問題** → Raspberry Pi 側の設定を確認（パッケージ不足など）

---

## 全自動デプロイスクリプト

より手軽に実行する場合は [deploy_and_run.sh](./scripts/deploy_and_run.sh) を使用:

```bash
./scripts/deploy_and_run.sh -s gps_display.py -t 30 -m "fix: バグ修正"
```

---

## よくある問題と対処法

| エラー | 原因 | 対処 |
|--------|------|------|
| `Permission denied (publickey)` | SSH鍵未設定 | `ssh-copy-id taki@172.20.10.2` を実行 |
| `ModuleNotFoundError` | パッケージ未インストール | `ssh taki@172.20.10.2 "cd ~/rtk-pipeline && .venv/bin/pip install <pkg>"` |
| `No such file or directory` | スクリプト名の誤り | `raspberrypi/` ディレクトリ内のファイル名を確認 |
| `serial.SerialException` | F9P未接続 | USB接続を確認、`/dev/ttyACM0` の存在を確認 |
| `git pull` で競合 | ローカル変更あり | raspi側で `git stash` してから `git pull` |
| `.venv` が存在しない | 初回セットアップ未実施 | 「初回セットアップ」セクションのコマンドを実行 |

## ループ制御

エラーが3回以上連続する場合:
1. より根本的な原因を調査する
2. Raspberry Pi 上のログを確認: `ssh taki@172.20.10.2 "cat ~/rtk-pipeline/log/*.csv | tail -50"`
3. 仮想環境の再構築を検討: `ssh taki@172.20.10.2 "cd ~/rtk-pipeline && rm -rf .venv && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"`
