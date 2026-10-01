# gcs/accuracy — 機体間相対測位精度の実測（Phase 2.5）

協調搬送に向けた **Phase 2.5** として、2 台のローバーを既知距離に置き、
**RTK 基線長**（タスク63504 の RELPOSNED iTOW ペアリング結果を利用）と
**メジャー実測値**を比較し、**PPK 後処理結果**（独立正解値）とクロスチェックして、
協調搬送が要求する相対測位精度を満たすかをレポートするモジュール群です。

## 目的（4 要件）

| # | 要件 | 実装 |
|---|------|------|
| (1) | 既知距離（メジャー実測）との比較 | `compare_to_reference()` / `evaluate_known_distance()` |
| (2) | RTK 基線長の算出（63504 ペアリング結果を利用） | `load_relpos_csv()` + `compute_baseline_stats()` |
| (3) | PPK 後処理結果とのクロスチェック | `load_ppk_baseline_csv()` / `baseline_from_position_files()` + `align_series()` + `evaluate_crosscheck()` |
| (4) | 協調搬送の要求精度を満たすかのレポート | `AccuracySpec`（想定精度・要定義）+ `AccuracyReport` |

> **依存**: タスク63504（`gcs/relpos/`）に依存します。本モジュールは 63504 が
> 出力する**ペアリング後 CSV**（`distance_3d_m` 等）を入力として再利用します。
> PPK 後処理の正解値は `archive/windows/ppk_logger.py` / `raspberrypi/ppk_logger.py` の
> RAWX を RTKLIB 等で後処理した結果を想定します。

## 位置づけ（既存資産との関係）

- タスク63504（`gcs/relpos/monitor.py`）が 2 ローバーの RELPOSNED を同一 iTOW で
  ペアリングし、機体間相対位置（`distance_3d_m` = 基線長）を CSV に記録する。
- 本モジュールはその CSV を「RTK 基線長」として読み込み、**既知距離**と**PPK 正解値**
  の 2 系統で精度検証する。
- 既存ファイル（`gcs/relpos/`・`gcs/config/`・`gcs/integration/` 等）は**無改変**。
  本成果物は `gcs/accuracy/` 配下に完結する。

## ファイル構成

```
gcs/accuracy/
├── README.md           # このファイル
├── __init__.py         # パッケージ定義
├── baseline.py         # 中核ロジック（統計・比較・合否判定。標準ライブラリのみ）
├── loader.py           # 入力読み込み（63504 CSV / 実測距離 / PPK 正解値）
├── report.py           # レポート組立（JSON / テキスト）
├── runner.py           # CLI（--selftest 付き）
├── test_baseline.py    # ユニットテスト（実ハードウェア不要）
├── reports/            # runner.py の出力先（.gitignore 済み）
└── .gitignore
```

## 使い方

### 1. データ取得（タスク63504 → 本モジュール）

```bash
cd ~/rtk-pipeline

# タスク63504: 2 ローバーの RELPOSNED をペアリングして CSV に記録
python3 gcs/relpos/monitor.py \
    --rover-a-port /dev/cu.usbmodem101 \
    --rover-b-port /dev/cu.usbmodem102 \
    --csv gcs/accuracy/reports/relpos_1m.csv
```

- 2 台のローバーをメジャーで測った既知距離（例: 1.000 m）に置く。
- 静止状態で数十秒〜数分記録し、`distance_3d_m` の時系列を得る。
- 高低差がほぼ 0 なら `distance_3d_m ≈ distance_2d_m ≈ メジャー実測（水平距離）`。

### 2. 精度レポートの生成

```bash
# 単一の既知距離（1.003 m）で比較（PPK なしの最小構成）
python3 gcs/accuracy/runner.py \
    --relpos-csv gcs/accuracy/reports/relpos_1m.csv \
    --distance 1.003

# PPK 基線長 CSV（独立正解値）を加えてクロスチェック
python3 gcs/accuracy/runner.py \
    --relpos-csv gcs/accuracy/reports/relpos_1m.csv \
    --distance 1.003 \
    --ppk-baseline-csv ppk_baseline.csv

# 2 ローバーの PPK 位置 CSV から基線長を内部計算してクロスチェック
python3 gcs/accuracy/runner.py \
    --relpos-csv gcs/accuracy/reports/relpos_1m.csv \
    --distance 1.003 \
    --ppk-pos-a ppk_a.csv --ppk-pos-b ppk_b.csv

# 複数の既知距離を時間帯で区切って比較（マニフェスト JSON）
python3 gcs/accuracy/runner.py \
    --relpos-csv gcs/accuracy/reports/relpos_all.csv \
    --measurements measurements.json \
    --ppk-baseline-csv ppk_baseline.csv
```

- 終了時にコンソールへレポートを表示し、`gcs/accuracy/reports/` に
  `accuracy_report_YYYYMMDD_HHMMSS.json` / `.txt` を保存します。
- 総合判定 PASS なら exit 0、FAIL なら exit 1。

### 3. 自己検証（実機なし）

```bash
python3 gcs/accuracy/runner.py --selftest
```

合成データ（既知距離 1.000 m に一致する系列と、10.0 m に不一致の系列）で
PASS / FAIL の両方を検証します。

## 入力フォーマット

### ペアリング後 CSV（`--relpos-csv`）

タスク63504 の `PAIRED_CSV_FIELDS` スキーマ。本モジュールは主に
`utc_time` / `itow_ms` / `distance_2d_m` / `distance_3d_m` / `acc_3d_m` /
`valid` / `matched` を使用します。既定で `valid != "1"`（relPosValid 未確定）と
`matched != "1"`（エポック不整合）の行を除外します
（`--no-require-valid` / `--no-require-matched` で含められます）。

### 既知距離（`--distance` / `--measurements`）

- `--distance 1.003` : 単一の実測距離（全系列を対象）。
- `--measurements measurements.json` : 複数配置。時間範囲でサンプルを区切る。

```json
{
  "measurements": [
    {"label": "D=1m", "distance_m": 1.003, "uncertainty_m": 0.002,
     "start_utc": "2026-09-27T10:00:00Z", "end_utc": "2026-09-27T10:01:00Z"},
    {"label": "D=2m", "distance_m": 2.001, "uncertainty_m": 0.002,
     "start_utc": "2026-09-27T10:01:10Z", "end_utc": "2026-09-27T10:02:00Z"}
  ]
}
```

### PPK 基線長 CSV（`--ppk-baseline-csv`）

PPK 後処理で得た「機体間基線長」の時系列。`utc_time`（または `time` /
`datetime` / `recv_utc`）と `baseline_length_m`（または `baseline_m` /
`distance_3d_m`）のカラムを持つ CSV を想定。

```csv
utc_time,baseline_length_m
2026-09-27T10:00:00.000Z,1.001
2026-09-27T10:00:00.200Z,1.002
```

### PPK 位置 CSV（`--ppk-pos-a` / `--ppk-pos-b`）

2 ローバーそれぞれの PPK 位置（`utc_time,lat_deg,lon_deg,alt_m`）。本モジュールが
時刻対応させて 3D 基線長を内部計算します（WGS84 回転楕円体近似。近距離では十分）。

```csv
utc_time,lat_deg,lon_deg,alt_m
2026-09-27T10:00:00.000Z,36.0751418,136.2133477,44.80
```

## 想定精度（要定義）

`AccuracySpec`（`gcs/accuracy/baseline.py`）に協調搬送の**想定精度を仮置き**しています。
プロジェクト要件が確定したら CLI 引数（`--tolerance` / `--rmse-max` /
`--bias-max` / `--pass-rate` / `--crosscheck-*`）または `AccuracySpec` の既定値で
見直してください。

| パラメータ | 既定値（仮） | 説明 |
|---|---|---|
| `tolerance_m` | `0.10` | 単一サンプルの許容絶対誤差 [m] |
| `pass_rate_pct_min` | `95.0` | 許容誤差内に収まる割合 [%] |
| `rmse_m_max` | `0.05` | RMSE 上限 [m] |
| `bias_m_max` | `0.03` | 平均誤差（バイアス）絶対値上限 [m] |
| `crosscheck_rmse_m_max` | `0.05` | RTK vs PPK の RMSE 上限 [m] |
| `crosscheck_bias_m_max` | `0.03` | RTK vs PPK のバイアス絶対値上限 [m] |
| `crosscheck_max_abs_m_max` | `0.15` | RTK vs PPK の最大絶対差上限 [m] |

> 上記は F9P RTK（1cm + 1ppm 級）と機体間近接運用を前提とした**仮の想定値**です。
> 協調搬送が実際に要求する精度（想定精度）は本タスクの責任範囲で定義してください。

## PASS/FAIL 判定

- **① 既知距離との比較**: `RMSE <= rmse_m_max`、`|bias| <= bias_m_max`、
  `合格率 >= pass_rate_pct_min` の 3 条件を全て満たせば PASS。
- **② RTK基線長の算出**: 有効サンプルが 1 件以上あれば算出成功（PASS）。
- **③ PPK クロスチェック**: `RMSE`・`|bias|`・`最大絶対差` が各上限以下なら PASS。
  PPK 未指定の場合は SKIP（総合判定に影響しない）。
- **総合**: いずれかのセクションが FAIL なら FAIL、それ以外は PASS。

## 出力物

```bash
gcs/accuracy/reports/
├── accuracy_report_YYYYMMDD_HHMMSS.json  # GCS 統合用（spec/inputs/sections）
└── accuracy_report_YYYYMMDD_HHMMSS.txt   # 人間可読レポート
```

## テスト

```bash
cd ~/rtk-pipeline
python3 -m unittest gcs.accuracy.test_baseline -v
# または
python3 gcs/accuracy/test_baseline.py
```

`baseline.py` / `loader.py` / `report.py` は**標準ライブラリのみ**で動作し、
ハードウェア・pandas・numpy を必要としません。

## 既存資産の再利用マップ（既存ファイルは無改変）

| 既存資産 | 再利用方法 | 用途 |
|---|---|---|
| `gcs/relpos/monitor.py`（タスク63504） | 出力 CSV を入力として参照 | RTK 基線長の元データ |
| `archive/windows/ppk_logger.py` / `raspberrypi/ppk_logger.py` | 出力 RAWX を RTKLIB 後処理 | PPK 独立正解値 |
| `gcs/relpos/pairing.py` の `PAIRED_CSV_FIELDS` | CSV カラム名の規約を踏襲 | 入力スキーマ |

## 注意点

- **基線長の定義**: `distance_3d_m` を基線長として採用（`distance_2d_m` も併記）。
  メジャー実測は通常「水平距離」のため、ローバーを同一平面（高低差 ≈ 0）に置くこと。
- **時刻対応**: PPK クロスチェックは `utc_time` の最近傍（`--align-tolerance`、既定 1 s）
  で対応付けます。ペアリング CSV の `utc_time` が正しいことを確認してください。
- **静止前提**: 実測はローバーを静止させた状態で行う。移動中はエポック差が誤差に
  直結するため対象外とします。
- **シリアル排他**: 実測時に各 F9P ポートを他スクリプトと同時に開かないこと
  （`gcs/relpos/README.md` と同様）。
