# gcs/flight_test — Phase 4 実飛行試験

Phase 4（実飛行試験）の成果物です。**地上で確立した RTK-FIXED を飛行中も維持できるか**を、
**EKF/フェイルセーフ設定（2e8a3）が有効な状態**で検証し、飛行試験結果をレポートとして残します。

- **依存: 2e8a3（EKF/フェイルセーフ golden 設定）**。
  本チェックアウトでは `gcs/ekf_failsafe/`（`ArduPilotParamGuard` / `evaluate_failsafe`）として
  実装されており、本モジュールはその FS golden の有効性を前提条件として再利用します。
  - FS 有効性は `--check-failsafe`（MAVLink 照合）または `--failsafe-ok/--failsafe-ng` で与えます。

---

## 1. 要件との対応

| # | 要件 | 実装 | 判定内容 |
|---|---|---|---|
| (1) | 飛行中（移動局を機体に搭載）の fix_type 時系列・位置精度の記録 | `recorder.py`（`FlightRecorder`） | MAVLink `GPS_RAW_INT`（fix_type/hdop/vdop/sats）+ `EKF_STATUS_REPORT`（flags/位置分散）を CSV に記録 |
| (2) | RTK-FIXED 維持率・FLOAT 遷移・EKF 整合性の評価 | `metrics.py`（`compute_ekf_consistency`）+ `gcs.fix_metrics.compute_metrics` 再利用 | FIXED 維持率・FLOAT 遷移・TTFF、fix_type と EKF フラグ/位置精度の整合性 |
| (3) | 測位劣化時のフェイルセーフ動作確認 | `metrics.py`（`detect_degradations` / `confirm_failsafe`）+ `STATUSTEXT`/`HEARTBEAT` 証跡 | 重度劣化（GPS 喪失 / EKF 不健全）と FS 発動（Failsafe STATUSTEXT / RTL・LAND）の対応 |
| (4) | 飛行試験結果のレポート出力と次フェーズ課題整理 | `report.py`（`FlightReport`）+ `metrics.py`（`next_phase_issues`） | JSON / Markdown 出力 + 定量乖離・定性的検討項目の課題化 |

---

## 2. 評価モデル（fix_type とフェイルセーフの関係）

- `fix_type` は MAVLink `GPS_FIX_TYPE` に正規化（`gcs.fix_metrics.FIX_NAMES` 準拠）。
  `5 = RTK_FLOAT`, `6 = RTK_FIXED`。
- **RTK-FIXED 維持率**は「初回 FIXED 以降」の時間割合（`fixed_rate_after_first_pct`）で判定します。
- **EKF 整合性**は「`fix_type == 6` のサンプルで EKF 位置・速度・姿勢が健全（`EKF_STATUS_REPORT.flags`）である割合」
  と「FIXED 時の EKF 水平位置誤差(1σ)（`sqrt(pos_horiz_variance)`）」で判定します。
- **フェイルセーフ（FS）** は ArduPilot の挙動に合わせ、次を「重度劣化（FS 対象）」とみなします：
  - `gps_loss`（`fix_type` が 0/1 = No Fix）→ `FS_GPS_ENABLE`
  - `ekf_unhealthy`（EKF フラグ喪失）→ `FS_EKF_ACTION`
  - ※ RTK→DGPS/3D への脱落（`rtk_loss`）や HDOP 上昇（`hdop_high`）は「精度劣化」であり、
    位置は残るため FS 対象外として区別します。

---

## 3. 接続仕様

```
[GCS / PC] --MAVLink(シリアル / tcp: / udpin:)--> [Pixhawk6C]  … GPS_RAW_INT / EKF_STATUS_REPORT
                                                     │          … STATUSTEXT / HEARTBEAT（FS 証跡）
                                                     v
                                              [移動局 F9P（機体搭載）]
```

- シリアル: `--device /dev/ttyAMA0 --baud 921600`
- ネットワーク: `--mavlink tcp:192.168.1.100:5760` / `--mavlink udpin:0.0.0.0:14550`

---

## 4. ディレクトリ構成

```
gcs/flight_test/
├── README.md              # このファイル
├── __init__.py            # パッケージ定義
├── metrics.py             # 定量評価（純粋関数・標準ライブラリのみ）
├── recorder.py            # MAVLink 観測 + CSV / イベント JSONL 入出力
├── report.py              # FlightReport（JSON / Markdown）
├── runner.py              # FlightTestRunner / CLI（--observe / --csv / --self-test）
├── test_metrics.py        # ユニットテスト（実機不要）
├── reports/               # レポート出力先（.gitignore 済み）
├── logs/                  # 飛行ログ出力先（.gitignore 済み）
└── .gitignore
```

---

## 5. 使い方

### 5-1. 実飛行の観測（記録＋評価）

```bash
cd ~/rtk-pipeline
source ~/Mavlink_venv/bin/activate        # pymavlink を使う場合

# MAVLink シリアルで 300 秒観測
python3 gcs/flight_test/runner.py --observe --device /dev/ttyAMA0 --duration 300

# MAVLink TCP で観測し、2e8a3 golden も同時に照合
python3 gcs/flight_test/runner.py --observe --mavlink tcp:192.168.1.100:5760 \
    --check-failsafe
```

- 観測中は 1 秒ごとに `fix_type` / EKF フラグを進捗表示します。
- 終了時にコンソールへ評価レポートを表示し、以下を保存します：
  - `gcs/flight_test/logs/flight_YYYYMMDD_HHMMSS.csv`（サンプル時系列）
  - `gcs/flight_test/logs/flight_YYYYMMDD_HHMMSS.events.jsonl`（FS / モードイベント）
  - `gcs/flight_test/reports/flight_report_YYYYMMDD_HHMMSS.json` / `.md`

### 5-2. 記録済み CSV の後処理評価

```bash
python3 gcs/flight_test/runner.py \
    --csv gcs/flight_test/logs/flight_YYYYMMDD_HHMMSS.csv \
    --events gcs/flight_test/logs/flight_YYYYMMDD_HHMMSS.events.jsonl
```

### 5-3. 自己検証（実機なし）

```bash
python3 gcs/flight_test/runner.py --self-test
```

合成データで「正常系フライト（PASS）」と「劣化系フライト（FS 証跡なし → FAIL）」の両方を検証します。

### 5-4. Python API（GCS 統合用）

```python
from gcs.flight_test.runner import evaluate_flight

report = evaluate_flight(series, failsafe_ok=True,
                         failsafe_events=fs_events, mode_events=mode_events)
print(report.format_markdown())
print(report.to_json())
```

---

## 6. CSV スキーマ（`FlightRecorder` / `write_flight_csv` 出力）

```
timestamp, elapsed_sec, fix_type, fix_name,
hdop_m, vdop_m, sats,
ekf_flags, ekf_pos_horiz_m, ekf_pos_vert_m, ekf_vel_var
```

| カラム | 内容 |
|---|---|
| `fix_type` | MAVLink `GPS_RAW_INT.fix_type`（0..6） |
| `hdop_m` / `vdop_m` | HDOP / VDOP（`GPS_RAW_INT.hdop/vdop` を 100 で除したメートル値） |
| `sats` | `GPS_RAW_INT.satellites_visible` |
| `ekf_flags` | `EKF_STATUS_REPORT.flags`（位置・速度・姿勢の健全ビット） |
| `ekf_pos_horiz_m` / `ekf_pos_vert_m` | EKF 位置分散の 1σ（`sqrt(pos_horiz_variance / pos_vert_variance)`） |
| `ekf_vel_var` | EKF 速度分散 |

イベント JSON Lines（`.events.jsonl`）は 1 行 1 イベント：
```json
{"type": "failsafe", "t": 12.3, "ts": "10:00:12.300", "kind": "gps", "text": "GPS glitch"}
{"type": "mode", "t": 12.4, "ts": "10:00:12.400", "mode": "RTL"}
```

---

## 7. 判定基準（`FlightSpec`、仮置き・要定義）

`gcs/flight_test/metrics.py` の `FlightSpec` に**仮の基準値**を置いています。運用要件が確定したら見直してください。

| パラメータ | 既定値（仮） | 説明 |
|---|---|---|
| `fixed_rate_pct_min` | `80.0` | FIXED 維持率（初回 FIXED 以降）下限 [%] |
| `max_float_transitions` | `5` | FLOAT 遷移回数 上限 |
| `ekf_consistency_pct_min` | `95.0` | FIXED 時に EKF 位置健全である割合 下限 [%] |
| `ekf_horiz_err_max_m` | `0.10` | FIXED 時の EKF 水平位置誤差(1σ) 上限 [m] |
| `ekf_vert_err_max_m` | `0.20` | FIXED 時の EKF 垂直位置誤差(1σ) 上限 [m] |
| `hdop_max_m` | `1.4` | HDOP（位置精度の代理指標）上限 [m] |
| `max_severe_degradations` | `3` | 重度劣化（FS 対象）の許容回数 上限 |
| `require_failsafe_evidence` | `True` | 重度劣化時に FS 発動の証跡を必須とするか |

---

## 8. 既存資産の再利用マップ（既存ファイルは無改変）

| 既存資産 | 再利用方法 | 用途 |
|---|---|---|
| `gcs/fix_metrics.py` | `from gcs.fix_metrics import compute_metrics, fix_name` | RTK-FIXED 維持率・FLOAT 遷移・TTFF（Phase 1） |
| `gcs/ekf_failsafe/checklist.py` | `from gcs.ekf_failsafe.checklist import ekf_position_healthy, evaluate_failsafe` | EKF 健全判定・FS golden 照合（2e8a3 相当） |
| `gcs/ekf_failsafe/param_guard.py` | `from gcs.ekf_failsafe.param_guard import ArduPilotParamGuard` | `--check-failsafe` の MAVLink golden 照合 |

> 本成果物は `gcs/flight_test/` 配下に新規格納し、既存ファイルは**無断改変していません**。

---

## 9. テスト

```bash
cd ~/rtk-pipeline

# 本モジュールのユニットテスト（実機不要）
python3 -m unittest gcs.flight_test.test_metrics -v

# 自己検証（合成データでフルパイプライン）
python3 gcs/flight_test/runner.py --self-test

# 既存テストとの一括実行（回帰確認）
python3 -m unittest gcs.test_fix_metrics gcs.test_rtcm_monitor \
    gcs.integration.test_runner gcs.preflight.test_checklist gcs.preflight.test_runner \
    gcs.ekf_failsafe.test_golden gcs.ekf_failsafe.test_checklist \
    gcs.ekf_failsafe.test_param_guard gcs.flight_test.test_metrics
```

---

## 10. 前提・注意

- **依存ライブラリ**: 実機観測は `pymavlink` が必要。`metrics.py` / `report.py` は標準ライブラリのみで動作します。
- **シリアル排他**: MAVLink シリアルポートは `mavlink-router.service` や他ツールと同時に開かないこと。
- **FS golden の前提**: 本モジュールは「2e8a3 golden が有効」を前提に FS 動作を評価します。実飛行前に
  `gcs/ekf_failsafe/runner.py` で golden 照合を済ませるか、`--check-failsafe` を併用してください。
- **判定基準は仮置き**: `FlightSpec` の基準値は要定義です。飛行実績が蓄積したら運用要件に合わせて更新してください。
- **FS 証跡の粒度**: `STATUSTEXT` / `HEARTBEAT` の観測はベストエフォートです。FS 発動の確実な記録が必要な場合は
  フライトログ（`.bin` の `STAT` / `MODE`）と突き合わせてください。

