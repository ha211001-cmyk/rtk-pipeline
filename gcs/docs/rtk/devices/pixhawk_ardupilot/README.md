# Pixhawk 6C + ArduPilot（RTK 取り込み・EKF・フェイルセーフ）

機体側フライトコントローラ **Pixhawk 6C（ArduPilot）** における、
**RTK 測位の EKF 取り込み・フェイルセーフ・パラメータ golden 管理**の資料です。

- 索引: [`../../README.md`](../../README.md)
- 条件の実値: [`../../common/fix_conditions.md`](../../common/fix_conditions.md)
- 移動局 F9P: [`../f9p_rover/README.md`](../f9p_rover/README.md)
- EKF モジュール詳細: [`../../../../ekf_failsafe/README.md`](../../../../ekf_failsafe/README.md)

> **出典ポリシー**: 本資料は `gcs/` パッケージ内のみを出典とします。

---

## 1. 役割

| 項目 | 内容 |
|---|---|
| RTCM の受け渡し | GCS/機体側から `GPS_RTCM_DATA` で受け取り、移動局 F9P へ転送 |
| RTK の取り込み | `fix_type = 6` の高精度位置・速度を **EKF3 の観測**として融合 |
| 品質ゲート | HDOP によりアーム可否・GPS フェイルセーフを判定 |
| フェイルセーフ | 測位喪失・EKF 不健全・GCS 断絶時に RTL / Land |
| golden 管理 | パラメータの退行を照合・自動修正（`ArduPilotParamGuard`） |

出典: [`../../../../ekf_failsafe/README.md`](../../../../ekf_failsafe/README.md) §1 / §4。

---

## 2. 二層 golden 構成

本システムの golden 照合は **2 層**です。

| 層 | 対象 | 実装 |
|---|---|---|
| **レジスタ層** | 移動局 F9P（`CFG-NAVHPG-DGNSSMODE` 等） | [`../../../../backend/f9p_configurator.py`](../../../../backend/f9p_configurator.py) |
| **パラメータ層** | Pixhawk 6C（`GPS_TYPE` / `EK3_SRC1_*` / `FS_*` 等） | [`../../../../ekf_failsafe/param_guard.py`](../../../../ekf_failsafe/param_guard.py) |

両者は同じ結果スキーマ（`status` / `checked` / `fixed` / `fix_failed` / `messages` /
`transport` / `timestamp`）を返すため、GCS GUI では同一コードパスで表示できます。

出典: [`../../../../ekf_failsafe/README.md`](../../../../ekf_failsafe/README.md) §8。

---

## 3. RTK→EKF ソース（`ekf_sources` 群）11 パラメータ

要件 (1)「RTK 測位を EKF に取り込む」に対応します。

| パラメータ | Golden | 意味 |
|---|---|---|
| `AHRS_EKF_TYPE` | `3` | EKF3 を姿勢・位置推定に使用 |
| `EK3_ENABLE` | `1` | EKF3 を有効化 |
| `EK3_SRC1_POSXY` | `3` | 水平位置ソース = GPS（RTK-FIXED を投入） |
| `EK3_SRC1_POSZ` | `3` | 高度ソース = GPS（RTK の高精度高度を投入） |
| `EK3_SRC1_VELXY` | `3` | 水平速度ソース = GPS |
| `EK3_SRC1_VELZ` | `3` | 垂直速度ソース = GPS |
| `EK3_SRC1_YAW` | `1` | 方位ソース = コンパス（単一 F9P のため移動基線は不使用） |
| `GPS_TYPE` | `9` | DroneCAN（`GPS_TYPE_UAVCAN`） |
| `GPS_AUTO_CONFIG` | `2` | 全自動設定（DroneCAN AutoConfig） |
| `GPS_PRIMARY` | `0` | プライマリ GPS = 1 番目（DroneCAN F9P） |
| `GPS_AUTO_SWITCH` | `0` | GPS 自動切替**無効**（劣化時に勝手に切り替えない） |

出典: [`../../../../ekf_failsafe/golden.py`](../../../../ekf_failsafe/golden.py) の
`PARAM_GROUPS[GROUP_EKF_SOURCES]` と `GOLDEN_PARAMS`。

### 3.1 `GPS_TYPE` と `GPS1_TYPE`

`GPS_TYPE` は「1 番目 GPS の正準名」です。ArduPilot のマイナーアップデートで
`GPS1_TYPE` に改名された経緯があり、実装は **`GPS1_TYPE` に自動フォールバック**します。

> ⚠️ 矛盾項目 6-4 として [`../../common/fix_conditions.md`](../../common/fix_conditions.md) §6-4
> に整理しています。出典: [`../../../../ekf_failsafe/README.md`](../../../../ekf_failsafe/README.md) §2-1。

### 3.2 パラメータ値の根拠

`golden.py` は値の根拠をコメントで明記しています。

- `GPS_TYPE = 9` は `AP_GPS.h` の `GPS_TYPE_UAVCAN`（DroneCAN）に対応。
- EKF3 ソース値: `0=NONE / 1=BARO / 3=GPS / 4=BEACON / 5=OPTFLOW / 6=EXTNAV / 7=WHEELENCODER`。
  YAW は `1=コンパス / 2=GPS(移動基線)`。

出典: [`../../../../ekf_failsafe/golden.py`](../../../../ekf_failsafe/golden.py) の docstring。

---

## 4. フェイルセーフ（`failsafe` 群）7 パラメータ

要件 (2)「RTK FLOAT/FIXED 喪失時の EKF 挙動と FS 設定の検証」に対応します。

| パラメータ | Golden | 意味 |
|---|---|---|
| `FS_GCS_ENABLE` | `1` | GCS 喪失時 Always RTL |
| `FS_EKF_ACTION` | `1` | EKF フェイルセーフ動作 = Land |
| `FS_EKF_THRESH` | `0.8` | EKF 整合性閾値（低いほど敏感。既定 0.8） |
| `FS_GPS_ENABLE` | `1` | GPS 喪失時 Land |
| `GPS_HDOP_GOOD` | `140` | GPS 良好 HDOP（1.4 m）＝アームに必要な GPS ロック品質 |
| `GPS_HDOP_MAX` | `200` | GPS フェイルセーフ発動 HDOP（2.0 m） |
| `GPS_GNSS_MODE` | `47` | GLONASS 無効の復元値 |

出典: [`../../../../ekf_failsafe/golden.py`](../../../../ekf_failsafe/golden.py) の
`PARAM_GROUPS[GROUP_FAILSAFE]` と `GOLDEN_PARAMS`。

### 4.1 `GPS_GNSS_MODE = 47` の意味

```
47 = 0b0101111
   = bit0(GPS) + bit1(SBAS) + bit2(Galileo) + bit3(BeiDou) + bit5(QZSS)
   → bit6(GLONASS) を落とした値
```

| ビット | コンステレーション |
|---|---|
| 0 | GPS |
| 1 | SBAS |
| 2 | Galileo |
| 3 | BeiDou |
| 4 | IMES |
| 5 | QZSS |
| 6 | GLONASS |

**背景**: 本プロジェクトの基地局は GLONASS を配信しないため、ローバー側で GLONASS を
有効にしても測位に寄与せず、バイアス要因になり得ます。
GLONASS を落とした実験（`gcs/` 外の退避済みスクリプト）後の復元先がこの値です。

出典: [`../../../../ekf_failsafe/golden.py`](../../../../ekf_failsafe/golden.py) の
`GNSS_MODE_BITS` / `decode_gnss_mode()`、および同ファイルのコメント、
[`../../../../ekf_failsafe/README.md`](../../../../ekf_failsafe/README.md) §12。

`0` は「受信機デフォルト／全コンステレーション」を意味します
（出典: 同上の `decode_gnss_mode()`）。

> 基地局が GLONASS を配信する構成へ戻す場合は、`--config`（YAML）で golden を変更します。

### 4.2 「GPS_LOCK」の対応

ArduPilot に `GPS_LOCK` というパラメータは**存在しません**。要件上の「GPS_LOCK」は
「GPS ロックを要求する設定」と解釈し、次のようにマッピングされています。

| 要件の表記 | 実パラメータ | 役割 |
|---|---|---|
| `GPS_LOCK` | `GPS_HDOP_GOOD`（=140） | アームに必要な GPS ロック品質（HDOP 1.4 m 以下） |
| （同上） | `GPS_HDOP_MAX`（=200） | GPS フェイルセーフ発動の HDOP 上限（2.0 m） |
| （同上） | `ARMING_CHECK`（GPS ビット） | アーム前チェックで GPS ロックを要求 |

出典: [`../../../../ekf_failsafe/README.md`](../../../../ekf_failsafe/README.md) §3。

---

## 5. RTK 喪失時の EKF / FS 挙動

| 事象 | 分類 | 担当 |
|---|---|---|
| RTK-FIXED → FLOAT / DGPS / 3D への脱落 | **精度劣化**（位置は残る） | 即時制御変化なし（要観測） |
| 継続的な位置喪失（`fix_type` 0/1） | **重度劣化** | `FS_GPS_ENABLE`（Land） |
| EKF の位置信頼度低下 | **重度劣化** | `FS_EKF_ACTION` / `FS_EKF_THRESH`（Land） |
| GCS 断絶 | — | `FS_GCS_ENABLE`（RTL） |

- `EK3_SRC1_* = 3`（GPS）により、`fix_type = 6` の位置・速度が EKF3 の観測として融合されます。
- RTK 解の喪失は **GPS そのものは使い続けられる**ため、直ちに制御が暴走することはありません。
- 動的検証は `evaluate_rtk_loss_behavior()` が fix_type 時系列と
  `EKF_STATUS_REPORT.flags` から「RTK 喪失回数・最長継続時間・EKF 測位維持」を判定します。

出典: [`../../../../ekf_failsafe/README.md`](../../../../ekf_failsafe/README.md) §4、
[`../../../../flight_test/README.md`](../../../../flight_test/README.md) §2。

---

## 6. EKF 整合性の評価指標

実飛行試験では、`fix_type = 6` のときの EKF 健全性を次で評価します。

| 指標 | 定義 | 基準（仮置き） |
|---|---|---|
| EKF 整合率 | `fix_type == 6` のサンプルで `EKF_STATUS_REPORT.flags` が健全な割合 [%] | `ekf_consistency_pct_min = 95.0` |
| 水平位置誤差(1σ) | `sqrt(pos_horiz_variance)` [m] | `ekf_horiz_err_max_m = 0.10` |
| 垂直位置誤差(1σ) | `sqrt(pos_vert_variance)` [m] | `ekf_vert_err_max_m = 0.20` |

出典: [`../../../../flight_test/README.md`](../../../../flight_test/README.md) §2 / §7。

記録は MAVLink `GPS_RAW_INT` と `EKF_STATUS_REPORT` から行い、CSV スキーマは
`timestamp, elapsed_sec, fix_type, fix_name, hdop_m, vdop_m, sats, ekf_flags,
ekf_pos_horiz_m, ekf_pos_vert_m, ekf_vel_var` です（同 §6）。

---

## 7. 確認・適用の方法

### 7.1 パラメータ golden の照合・自動修正（`runner.py`）

```bash
cd ~/rtk-pipeline-local

# MAVLink シリアル（機体直結）
python3 gcs/ekf_failsafe/runner.py --device /dev/ttyAMA0 --baud 921600

# MAVLink ネットワーク
python3 gcs/ekf_failsafe/runner.py --mavlink tcp:192.168.1.100:5760

# golden 退行を自動修正する
python3 gcs/ekf_failsafe/runner.py --device /dev/ttyAMA0 --auto-fix

# 実機なしの自己検証
python3 gcs/ekf_failsafe/runner.py --self-test
```

| オプション | 既定 | 意味 |
|---|---|---|
| `--f9p-host` / `--f9p-port` | `192.168.1.100` / `5001` | F9P golden 照合（レジスタ層）の TCP |
| `--device` | — | MAVLink シリアル（例: `/dev/ttyAMA0`） |
| `--baud` | `921600` | MAVLink シリアルボーレート |
| `--mavlink` | — | MAVLink 接続文字列（`tcp:host:port` / `udpin:...`） |
| `--duration` | — | 動的観測時間 |
| `--auto-fix` | — | golden 退行を自動修正 |
| `--config` | — | 上書き設定の YAML |
| `--report-dir` | — | JSON レポート出力先 |
| `--self-test` | — | 合成データで自己検証 |
| `--json` | — | チェックリストの JSON も標準出力 |

出典: [`../../../../ekf_failsafe/runner.py`](../../../../ekf_failsafe/runner.py) の argparse、
[`../../../../ekf_failsafe/README.md`](../../../../ekf_failsafe/README.md) §5。

### 7.2 Python API

```python
from gcs.ekf_failsafe.param_guard import ArduPilotParamGuard
from gcs.ekf_failsafe.checklist import evaluate_ekf_sources, evaluate_failsafe

guard = ArduPilotParamGuard(connection="serial:/dev/ttyAMA0", baud=921600)
result = guard.run_check_and_fix(fix=False)   # 照合のみ / fix=True で自動修正
print(result["status"])                        # PASS / FIXED / FAIL

ekf_item = evaluate_ekf_sources(result)
fs_item = evaluate_failsafe(result)
```

出典: [`../../../../ekf_failsafe/README.md`](../../../../ekf_failsafe/README.md) §7。

### 7.3 飛行試験での FS 照合込み観測

```bash
python3 gcs/flight_test/runner.py --observe --mavlink tcp:192.168.1.100:5760 --check-failsafe
```

出典: [`../../../../flight_test/README.md`](../../../../flight_test/README.md) §5-1。

---

## 8. 注意事項

1. **保存仕様**: ArduPilot は `PARAM_SET` 受信時に**自動で EEPROM へ保存**します。
   `MAV_CMD_PREFLIGHT_STORAGE` は使用しません
   （出典: [`../../../../ekf_failsafe/README.md`](../../../../ekf_failsafe/README.md) §12）。
2. **MAVLink ストリーム**: 動的検証は `GPS_RAW_INT` / `EKF_STATUS_REPORT` を観測します。
   `ArduPilotParamGuard.enable_streams()` が `MAV_CMD_SET_MESSAGE_INTERVAL` で
   ストリームを要求します（ベストエフォート）。
3. **シリアル排他**: MAVLink シリアルポートは `mavlink-router.service` や他ツールと
   同時に開かないこと。
4. **golden 修正は必ず照合から**: `run_check_and_fix(fix=False)` で現状確認 →
   `--no-fix` / `fix=False` を経てから修正すること。
5. **`EK3_SRC1_POSZ`**: RTK の cm 級高度を取り込むため `3`（GPS）を既定としています。
   気圧高度（`1` = BARO）を使いたい環境では `--config`（YAML）で上書きします
   （出典: [`../../../../ekf_failsafe/README.md`](../../../../ekf_failsafe/README.md) §2-1）。

---

## 9. 出典（`gcs/` 内のみ）

| ファイル | 参照箇所 |
|---|---|
| `gcs/ekf_failsafe/golden.py` | `PARAM_GROUPS` / `GOLDEN_PARAMS` / `GNSS_MODE_BITS` / `decode_gnss_mode()` / docstring |
| `gcs/ekf_failsafe/param_guard.py` | `ArduPilotParamGuard.run_check_and_fix()` / `enable_streams()` |
| `gcs/ekf_failsafe/checklist.py` | `evaluate_ekf_sources()` / `evaluate_failsafe()` / `evaluate_rtk_loss_behavior()` |
| `gcs/ekf_failsafe/runner.py` | argparse のオプション一覧 |
| `gcs/ekf_failsafe/README.md` | §1 / §2-1 / §2-2 / §3 / §4 / §5 / §7 / §8 / §12 |
| `gcs/backend/f9p_configurator.py` | `GOLDEN_VALUES`（レジスタ層） |
| `gcs/preflight/README.md` | §1（Item 2 はレジスタ層） |
| `gcs/flight_test/README.md` | §2 評価モデル / §5-1 / §6 / §7 `FlightSpec` |
| `gcs/rtk_tools/mavlink_bridge.py` | `GPS_RTCM_DATA` 注入 / `FS_GCS_ENABLE` 起動時チェック |
| `gcs/config/config.yaml` | `rover.mavlink_baud = 921600` |

> 関連: [`../f9p_rover/README.md`](../f9p_rover/README.md)（RTCM を受ける受信機）／
> [`../raspberrypi/README.md`](../raspberrypi/README.md)（MAVLink 中継・RTCM 注入）
