# gcs/preflight — Phase 3 飛行前セルフテスト（飛行試験準備）

Phase 3（飛行試験準備）の成果物です。**静的照合（Item 2 の golden 差分）** と
**動的健全性（Item 1 の FIXED 率・Item 3 の RTCM CRC/age・基地局レート）** を
**1 コマンド**で走らせ、**PASS/FAIL の一括レポート（飛行前チェックリスト）** を
出力します。

依存: **5100f（②③ RTK ステータス・RTCM リンク監視の TCP 化）** が完了している前提です
（Phase 1〜2.5 完了後に着手）。

---

## 1. 判定項目（Item 対応）

| 項目 | 種別 | 再利用モジュール | 判定内容 |
|---|---|---|---|
| **Item 2 コンフィグ照合** | 静的 | `gcs/backend/f9p_configurator.py`（`F9pConfigGuard`） | Golden 値の退行差分（`DGNSSMODE` / `DYNMODEL` / `RATE` / `UART1 RTCM3 入力`） |
| **Item 1 RTK FIXED 率** | 動的 | `gcs/fix_metrics.py`（`compute_metrics`） | FIXED 到達・FIXED 率・FLOAT 遷移・TTFF |
| **Item 3 RTCM リンク健全性** | 動的 | `gcs/rtcm_monitor.py`（`CorrectionMonitor`） | RTCM 到達・RTK age・CRC エラー率・msgUsed |
| **基地局レート** | 動的 | `CorrectionMonitor` の `rxm_rtcm` 集計 | ローバー `UBX-RXM-RTCM` の到達レート（msg/s） |

Item 1 / Item 3 / 基地局レートは、いずれも**ローバー F9P の UBX ストリーム**
（`NAV-PVT` / `UBX-RXM-RTCM`）から取得します。基地局レートは「基地局からローバーへ
実際に届いた RTCM 補正メッセージの到達レート」として評価します。

---

## 2. 接続仕様（単一 TCP エンドポイント）

5100f で ②③ が TCP 化されているため、接続設定は**シリアルポートではなく
Wi-Fi の IP アドレス + TCP ポート**に統一します（シリアルポート選択は不要）。

```
[GCS / PC] --TCP(DroneCAN Serial Forwarding / 単一エンドポイント)--> [F9P シリアル]
      │
      ├─ Item 2: UBX-CFG-VALGET/VALSET（golden 照合）
      ├─ Item 1: UBX-NAV-PVT（fix_type / FIXED 率）
      └─ Item 3 / 基地局レート: UBX-RXM-RTCM（CRC / msgUsed / RTK age / 到達レート）
```

- 既定: `host=192.168.1.100`, `port=5001`（環境に合わせて変更）。

---

## 3. ディレクトリ構成

```
gcs/preflight/
├── README.md              # このファイル
├── __init__.py            # パッケージ定義
├── checklist.py           # Item 判定（純粋関数）と飛行前チェックリスト整形
├── session.py             # TCP セッション管理（切断検知・再接続・自動リトライ）
├── runner.py              # PreflightRunner（オーケストレータ）+ CLI
├── test_checklist.py      # ユニットテスト（実機不要）
├── test_runner.py         # ユニットテスト（実機不要 / セッション切断検知含む）
└── .gitignore             # reports/ 等の出力を除外
```

---

## 4. 使い方

### 4-1. コマンドライン（1 コマンド実行）

```bash
cd ~/rtk-pipeline
source .venv/bin/activate

# 実機（機体 Wi-Fi IP + ポートへ接続）
python3 gcs/preflight/runner.py --host 192.168.1.100 --port 5001

# 観測時間を 120 秒に上書き
python3 gcs/preflight/runner.py --host 192.168.1.100 --duration 120

# Item 2 で golden 退行を検知したら自動修正する（既定は照合のみ）
python3 gcs/preflight/runner.py --host 192.168.1.100 --auto-fix

# 実機なしの自己検証（合成データでフルパイプラインを検証 / 約4秒）
python3 gcs/preflight/runner.py --self-test
```

終了時にコンソールへ飛行前チェックリストを表示し、`gcs/preflight/reports/` に
JSON レポートを保存します（`--report-dir` で変更可）。

### 4-2. GUI（接続設定 UI + 再接続）— 退避済み

旧 Tkinter GUI（`gcs/preflight/gui.py`）は Phase 0 統合計画（§6）に基づき
`gcs/_retired/preflight_gui_tkinter/` へ退避しました。接続設定（IP+TCP）と
再接続の機能は、CLI（`runner.py`）と `session.py`（`TcpSession`）で引き続き利用できます。
将来は Web ダッシュボード（`python3 -m gcs.server`）へプレフライトパネルとして追加予定です。

---

## 5. TCP 切断（Wi-Fi 瞬断等）のハンドリング（要件 6）

5100f のリーダー（`RoverUbxReader`）は**自動再接続しない前提**のため、GUI /
セッション層（`gcs/preflight/session.py` の `TcpSession`）で復旧を実装しています。

- **切断検知**: リーダースレッドの死亡（TCP 完全断絶）に加え、**RTK age の stale 検知
  （Wi-Fi 瞬断等で補正データが途切れた＝データ断絶）と連動**して検出します。
  ※ 一度も受信していない `no_data` は「未受信」であり切断と区別します。
- **再接続ボタン（手動）**: GUI の「再接続」ボタンで `session.reconnect()` を呼び、
  5100f リーダーを破棄して新規 TCP 接続を張り直します。
- **自動再接続（バックグラウンドリトライループ）**: 「自動再接続」チェックボックス
  （既定 ON）で、切断検知後に指数関数的でない一定間隔のリトライループが動作します
  （`reconnect.check_interval_sec` / `retry_interval_sec` / `max_attempts`）。

`TcpSession` は GUI に依存しないため、CLI（`--no-auto-reconnect` で無効化）や他の
GCS からも再利用できます。

---

## 6. 判定基準（既定値）

`runner.py` の `DEFAULT_CONFIG` に集約し、`--config`（YAML）で上書きできます。

| キー | 既定値 | 説明 |
|---|---|---|
| `connection.host` | `192.168.1.100` | DroneCAN Serial Forwarding のホスト |
| `connection.port` | `5001` | TCP ポート |
| `monitor.duration_sec` | `60.0` | 動的観測時間 |
| `monitor.age_alert_threshold` | `10.0` | RTK age アラート閾値 [秒] |
| `criteria.fixed_rate_pct_min` | `80.0` | FIXED 率の下限 [%] |
| `criteria.max_float_transitions` | `5` | FLOAT 遷移回数の上限 |
| `criteria.ttff_sec_max` | `120.0` | TTFF の上限 [秒] |
| `criteria.base_rate_min_fps` | `1.0` | 基地局 RTCM 補正到達レートの下限 [msg/s] |
| `reconnect.auto` | `true` | バックグラウンド自動再接続 |
| `report.json` | `true` | JSON レポート出力 |

---

## 7. 既存資産の再利用マップ（既存ファイルは無改変）

| 既存資産 | 再利用方法 | 用途 |
|---|---|---|
| `gcs/backend/f9p_configurator.py` | `F9pConfigGuard` / `TcpTransport` | Item 2 golden 照合 / TCP トランスポート |
| `gcs/fix_metrics.py` | `compute_metrics` / `fix_name` | Item 1 FIXED 率 |
| `gcs/rtcm_monitor.py` | `CorrectionMonitor` | Item 3 CRC/age + 基地局レート |
| `gcs/integration/sources.py` | `RoverUbxReader` / `SyntheticRoverSource` / `run_phase1_offline` | 5100f の TCP リーダー / 自己検証 |

> 本成果物は `gcs/preflight/` 配下に新規格納し、既存ファイルは**無断改変していません**。

---

## 8. テスト

```bash
cd ~/rtk-pipeline
python3 -m unittest gcs.preflight.test_checklist gcs.preflight.test_runner -v

# 既存テストとの一括実行
python3 -m unittest gcs.test_fix_metrics gcs.test_rtcm_monitor \
    gcs.integration.test_runner gcs.preflight.test_checklist gcs.preflight.test_runner
```

---

## 9. 前提・注意

- **依存ライブラリ**: `pyubx2`（UBX / コンフィグ）、`pyserial`（直接シリアル時のみ）。
  `checklist.py` / `session.py` の判定ロジックは標準ライブラリのみで動作します。
- **ハードウェア前提**: ローバー F9P が `UBX-NAV-PVT` と `UBX-RXM-RTCM` を出力している
  こと（`CFG-MSGOUT-UBX-RXM-RTCM-*` を有効化）。基地局レートは UBX-RXM-RTCM の到達件数
  で評価するため、基地局 F9P は RTCM3 を出力している前提です。
- **シリアル排他**: 同一 TCP エンドポイントへ複数クライアントを同時接続しないこと。
- **TCP 瞬断と stale の関係**: Wi-Fi 瞬断時は TCP 断（リーダー死亡）と RTK age の
  stale（データ途切れ）の両方で検出し、いずれも切断として扱います。
