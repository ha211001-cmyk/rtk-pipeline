# gcs/ekf_failsafe — Phase 3（RTK→EKF 取り込み・フェイルセーフ）飛行試験準備

Phase 3（飛行試験準備）の成果物です。**RTK-FIXED を ArduPilot の EKF に正しく
取り込み、飛行中も測位精度を維持しつつ、測位劣化時にフェイルセーフ（FS）が
正しく働く**よう、**ArduPilot パラメータの Golden 管理・照合・自動修正**と
**RTK 喪失時挙動の検証**を 1 コマンドで行います。

- 依存: **43d9f（GCS GUI 統合・飛行前セルフテスト）** と **52eb5（F9P config 照合）**。
  - 52eb5 の `F9pConfigGuard`（`gcs/backend/f9p_configurator.py`）を import して、
    **F9P レジスタ golden と ArduPilot パラメータ golden の「二層 golden 照合」**を行う。
  - 43d9f の `CheckItem`（`gcs/preflight/checklist.py`）を再利用し、既存の飛行前
    セルフテスト（`PreflightReport`）と同一スキーマのチェックリストを出力する。

---

## 1. 要件との対応

| # | 要件 | 実装 | 判定内容 |
|---|---|---|---|
| (1) | RTK 測位を EKF に取り込むパラメータ設定 | `golden.py`（`ekf_sources` 群）+ `ArduPilotParamGuard` | `GPS_TYPE` / `EK3_SRC1_POSXY/POSZ/VELXY/VELZ/YAW` / `AHRS_EKF_TYPE` / `EK3_ENABLE` 等の golden 照合・自動修正 |
| (2) | RTK FLOAT/FIXED 喪失時の EKF 挙動と FS 設定の検証 | `golden.py`（`failsafe` 群）+ `evaluate_rtk_loss_behavior` | `GPS_GNSS_MODE` 復元・`FS_GCS_ENABLE`・`FS_EKF_*`・`FS_GPS_ENABLE`・GPS ロック品質ゲートの照合 + fix_type/EKF フラグの動的観測 |
| (3) | 設定値の golden 管理と 52eb5 連携 | `golden.py` + `param_guard.py` | F9pConfigGuard と同じ戻り値スキーマ（status/checked/fixed/fix_failed…）で二層 golden を統合 |
| (4) | 43d9f（飛行前セルフテスト）への組み込み | `checklist.py` + `runner.py` | `CheckItem` を再利用し、`Phase3Report` が同一スキーマのチェックリストを出力 |

---

## 2. Golden 値

### 2-1. RTK→EKF ソース（`ekf_sources` 群 / 要件 (1)）

| パラメータ | Golden | 意味 |
|---|---|---|
| `AHRS_EKF_TYPE` | `3` | EKF3 を姿勢・位置推定に使用 |
| `EK3_ENABLE` | `1` | EKF3 有効化 |
| `EK3_SRC1_POSXY` | `3` | 水平位置ソース = GPS（RTK-FIXED を投入） |
| `EK3_SRC1_POSZ` | `3` | 高度ソース = GPS（RTK の高精度高度を投入）※ |
| `EK3_SRC1_VELXY` | `3` | 水平速度ソース = GPS |
| `EK3_SRC1_VELZ` | `3` | 垂直速度ソース = GPS |
| `EK3_SRC1_YAW` | `1` | 方位ソース = コンパス（単一 F9P のため GPS 移動基線は不使用） |
| `GPS_TYPE` | `9` | DroneCAN（`GPS_TYPE_UAVCAN`）。`GPS1_TYPE` に自動フォールバック |
| `GPS_AUTO_CONFIG` | `2` | 全自動設定（DroneCAN AutoConfig） |
| `GPS_PRIMARY` | `0` | プライマリ GPS = 1 番目（DroneCAN F9P） |
| `GPS_AUTO_SWITCH` | `0` | GPS 自動切替無効（RTK 劣化時に勝手に切り替えない） |

> ※ `EK3_SRC1_POSZ` は RTK の cm 級高度を取り込むため `3`（GPS）を既定としています。
> 気圧高度（`1`=BARO）を使いたい環境では `--config`（YAML）で上書きできます。

### 2-2. フェイルセーフ（`failsafe` 群 / 要件 (2)）

| パラメータ | Golden | 意味 |
|---|---|---|
| `FS_GCS_ENABLE` | `1` | GCS 喪失時 Always RTL |
| `FS_EKF_ACTION` | `1` | EKF フェイルセーフ動作 = Land |
| `FS_EKF_THRESH` | `0.8` | EKF 整合性閾値（低いほど敏感） |
| `FS_GPS_ENABLE` | `1` | GPS 喪失時 Land |
| `GPS_HDOP_GOOD` | `140` | GPS 良好 HDOP（1.4m）= アームに必要な GPS ロック品質 |
| `GPS_HDOP_MAX` | `200` | GPS フェイルセーフ発動 HDOP（2.0m） |
| `GPS_GNSS_MODE` | `47` | GLONASS(bit6) 無効の復元値（GPS+SBAS+Galileo+BeiDou+QZSS） |

---

## 3. 用語対応（要件の「GPS_LOCK」について）

ArduPilot には `GPS_LOCK` という名前のパラメータは存在しません。要件 (2) の
「GPS_LOCK」は「**GPS ロックを要求する設定**」を指すものと解釈し、以下にマッピングしています:

| 要件の表記 | 実パラメータ | 役割 |
|---|---|---|
| `GPS_LOCK` | `GPS_HDOP_GOOD`（=140） | アームに必要な GPS ロック品質（HDOP 1.4m 以下） |
| （同上） | `GPS_HDOP_MAX`（=200） | GPS フェイルセーフ発動の HDOP 上限（2.0m） |
| （同上） | `ARMING_CHECK`（GPS ビット） | アーム前チェックで GPS ロックを要求 |

---

## 4. RTK 喪失時の EKF / FS 挙動（要件 (2) の考え方）

- **RTK 取り込み**: `EK3_SRC1_* = 3`（GPS）により、RTK-FIXED（fix_type=6）の高精度
  位置・速度が EKF3 の観測として融合されます。
- **RTK 喪失（FIXED/FLOAT → DGPS/3D 等）**: EKF3 は GPS を使い続けるため、RTK 解の
  喪失は「精度劣化」として扱われ、即座に制御が暴走することはありません。
  - 継続的な位置喪失（GPS ロック喪失）は `FS_GPS_ENABLE`（Land）が、
  - EKF の位置信頼度低下は `FS_EKF_ACTION`/`FS_EKF_THRESH`（Land）が、
  - GCS 断絶は `FS_GCS_ENABLE`（RTL）が、それぞれ受け持ちます。
- **動的検証**: `evaluate_rtk_loss_behavior()` が fix_type 時系列と
  `EKF_STATUS_REPORT.flags` から「RTK 喪失回数・最長継続時間・EKF 測位維持」を判定し、
  FS golden が有効であることを前提条件として含めます。

---

## 5. 接続仕様（二系統）

```
[GCS / PC] --TCP(DroneCAN Serial Forwarding)--> [ローバー F9P]  … 52eb5 golden（F9P レジスタ）
        │
        └--MAVLink(シリアル / tcp: / udp:)----> [Pixhawk6C]     … ArduPilot パラメータ golden + RTK 観測
```

- F9P golden（52eb5）: `--f9p-host 192.168.1.100 --f9p-port 5001`。
- ArduPilot golden / RTK 観測: `--device /dev/ttyAMA0 --baud 921600`（シリアル）または
  `--mavlink tcp:192.168.1.100:5760` / `--mavlink udpin:0.0.0.0:14550`。

---

## 6. ディレクトリ構成

```
gcs/ekf_failsafe/
├── README.md              # このファイル
├── __init__.py            # パッケージ定義
├── golden.py              # Golden 値（EKF ソース群 / フェイルセーフ群）+ 型・ラベル
├── param_guard.py         # ArduPilotParamGuard（MAVLink 照合・自動修正・RTK 観測）
├── checklist.py           # Item 判定（純粋関数）と Phase3Report
├── runner.py              # Phase3Runner（52eb5 + ArduPilot golden + RTK 喪失挙動）
├── test_golden.py         # ユニットテスト（実機不要）
├── test_checklist.py      # ユニットテスト（実機不要）
├── test_param_guard.py    # ユニットテスト（MAVLink モック）
└── .gitignore             # reports/ 等の出力を除外
```

---

## 7. 使い方

### 7-1. コマンドライン（1 コマンド実行）

```bash
cd ~/EVK-F9P
source ~/Mavlink_venv/bin/activate        # pymavlink を使う場合

# 実機（F9P は DroneCAN Serial Forwarding / FC は MAVLink シリアル）
python3 gcs/ekf_failsafe/runner.py \
    --f9p-host 192.168.1.100 --f9p-port 5001 \
    --device /dev/ttyAMA0 --baud 921600

# MAVLink を TCP で接続（GCS 統合時）
python3 gcs/ekf_failsafe/runner.py \
    --f9p-host 192.168.1.100 --f9p-port 5001 \
    --mavlink tcp:192.168.1.100:5760

# 観測時間を 120 秒に上書き
python3 gcs/ekf_failsafe/runner.py --device /dev/ttyAMA0 --duration 120

# 退行を検知したら自動修正する（既定は照合のみ）
python3 gcs/ekf_failsafe/runner.py --device /dev/ttyAMA0 --auto-fix

# 実機なしの自己検証（合成データでフルパイプラインを検証 / 約4秒）
python3 gcs/ekf_failsafe/runner.py --self-test
```

終了時にコンソールへチェックリストを表示し、`gcs/ekf_failsafe/reports/` に
JSON レポートを保存します（`--report-dir` で変更可、`--json` で標準出力にも）。

### 7-2. Python API（GCS 統合用）

```python
from gcs.ekf_failsafe.param_guard import ArduPilotParamGuard
from gcs.ekf_failsafe.checklist import evaluate_ekf_sources, evaluate_failsafe

guard = ArduPilotParamGuard(device="/dev/ttyAMA0", baud=921600)
result = guard.run_check_and_fix(fix=False)   # 照合のみ / fix=True で自動修正
print(result["status"])   # PASS / FIXED / FAIL

ekf_item = evaluate_ekf_sources(result)       # CheckItem（43d9f と同一クラス）
fs_item = evaluate_failsafe(result)
```

`run_check_and_fix()` の戻り値は `gcs/backend/f9p_configurator.py` の
`F9pConfigGuard.run_check_and_fix()` と同じキー（`status` / `summary` /
`checked` / `fixed` / `fix_failed` / `messages` / `transport` / `timestamp`）です。

---

## 8. 52eb5（config 照合）との連携

`runner.py` は以下の **二層 golden 照合** を 1 コマンドで実行します:

| 層 | 対象 | 再利用モジュール | 備考 |
|---|---|---|---|
| レジスタ | ローバー F9P（`CFG-NAVHPG-DGNSSMODE` 等） | `gcs/backend/f9p_configurator.py`（`F9pConfigGuard` / 52eb5） | `evaluate_item2` で合否 |
| パラメータ | Pixhawk6C（`GPS_TYPE` / `EK3_SRC1_*` / `FS_*` 等） | `gcs/ekf_failsafe/param_guard.py`（`ArduPilotParamGuard`） | `evaluate_ekf_sources` / `evaluate_failsafe` で合否 |

両者は同じ結果スキーマのため、GCS GUI（43d9f）側では同一コードパスで表示できます。

---

## 9. 43d9f（飛行前セルフテスト）への組み込み

本モジュールの `evaluate_*()` は `gcs.preflight.checklist.CheckItem`（43d9f）を
そのまま返すため、既存の `PreflightReport` に混ぜられます（既存ファイルは無改変）。

```python
from gcs.preflight.checklist import PreflightReport
from gcs.ekf_failsafe.checklist import evaluate_ekf_sources, evaluate_failsafe, evaluate_rtk_loss_behavior

# 既存の Item 1/2/3/基地局レートに加えて、本モジュールの Item を追加する例
report = PreflightReport([item2, item1, item3, base,
                          evaluate_ekf_sources(result),
                          evaluate_failsafe(result),
                          evaluate_rtk_loss_behavior(series, fs_ok)])
```

または本モジュール単体の `Phase3Report`（`checklist.py`）を使うと、F9P golden +
RTK→EKF + フェイルセーフ + RTK 喪失挙動の 4 項目を同一スキーマで一括出力します。

---

## 10. 既存資産の再利用マップ（既存ファイルは無改変）

| 既存資産 | 再利用方法 | 用途 |
|---|---|---|
| `gcs/backend/f9p_configurator.py` | `from gcs.backend.f9p_configurator import F9pConfigGuard` | 52eb5 F9P レジスタ golden 照合 |
| `gcs/preflight/checklist.py` | `CheckItem` / `evaluate_item2` / status 語彙 | 43d9f と同一スキーマの Item |
| `gcs/integration/sources.py` | `run_phase1_offline` | `--self-test` の F9P golden 検証 |
| `archive/dronecan_gps_rtk/gps_can_verify/README.md` | 知見の参照（EEPROM 保存不要 / GPS1_TYPE=9） | パラメータ型・保存仕様の根拠 |

> 本成果物は `gcs/ekf_failsafe/` 配下に新規格納し、既存ファイルは**無断改変していません**。

---

## 11. テスト

```bash
cd ~/EVK-F9P

# 本モジュールのユニットテスト（実機不要 / MAVLink モック）
python3 -m unittest gcs.ekf_failsafe.test_golden \
    gcs.ekf_failsafe.test_checklist \
    gcs.ekf_failsafe.test_param_guard -v

# 既存テストとの一括実行（回帰確認）
python3 -m unittest gcs.test_fix_metrics gcs.test_rtcm_monitor \
    gcs.integration.test_runner gcs.preflight.test_checklist gcs.preflight.test_runner \
    gcs.ekf_failsafe.test_golden gcs.ekf_failsafe.test_checklist \
    gcs.ekf_failsafe.test_param_guard
```

---

## 12. 前提・注意

- **依存ライブラリ**: `pymavlink`（MAVLink 通信）、`pyubx2`（52eb5 経由の F9P 照合）。
  `golden.py` / `checklist.py` の判定ロジックは標準ライブラリのみで動作します。
- **MAVLink ストリーム**: 動的検証（RTK 喪失挙動）は `GPS_RAW_INT` / `EKF_STATUS_REPORT` を
  観測します。`ArduPilotParamGuard.enable_streams()` が `MAV_CMD_SET_MESSAGE_INTERVAL`
  でストリームを要求します（ベストエフォート）。
- **保存仕様**: ArduPilot は `PARAM_SET` 受信時に自動で EEPROM へ保存するため、
  `MAV_CMD_PREFLIGHT_STORAGE` は使用しません。
- **シリアル排他**: MAVLink シリアルポートは `mavlink-router.service` や他ツールと
  同時に開かないこと。
- **GPS_GNSS_MODE 復元**: `GPS_GNSS_MODE = 47`（GLONASS 無効）は
  `archive/rtk_field_test/set_gnss_mode.py` の GLONASS 実験後の復元先です。基地局が GLONASS を
  配信する構成へ戻す場合は `--config`（YAML）で golden を変更してください。

