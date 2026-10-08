# 移動局 F9P（ZED-F9P / Rover）

RTCM3 補正を受信して **RTK 解**（`RTK_FLOAT` / `RTK_FIXED`）を出し、その状態を
RELPOSNED で監視する**移動局**としての u-blox ZED-F9P の設定と運用手順です。

- 索引: [`../../README.md`](../../README.md)
- 条件の実値: [`../../common/fix_conditions.md`](../../common/fix_conditions.md)
- 基地局側: [`../f9p_base/README.md`](../f9p_base/README.md)

> **出典ポリシー**: 本資料は `gcs/` パッケージ内のみを出典とします。

---

## 1. 役割

| 項目 | 内容 |
|---|---|
| 役割 | 基地局の RTCM3 を適用し、**搬送波位相**で高精度測位を行う |
| 入力 | RTCM3（`CFG_UART2INPROT_RTCM3X = 1`） |
| 出力 | UBX（`CFG_UART2OUTPROT_UBX = 1`、RELPOSNED 等） |
| 接続 | 機体側。DroneCAN H-RTK F9P の場合は `GPS_TYPE = 9`（DroneCAN） |
| 監視 | `UBX-NAV-RELPOSNED` の `carrSoln` |

出典: [`../../../../rtk_tools/f9p_config_all.py`](../../../../rtk_tools/f9p_config_all.py) の
`_UART2_ROVER_CFG_KEYS` / `_GNSS_SIGNAL_CFG_KEYS`、
[`../../../../ekf_failsafe/golden.py`](../../../../ekf_failsafe/golden.py)（`GPS_TYPE = 9`）。

---

## 2. 設定される 19 キー

移動局ロール（`--role rover`）で write-verify されるキーは **19 件**です
（出典: [`../../../../rtk_tools/f9p_config_all.py`](../../../../rtk_tools/f9p_config_all.py)）。

### 2.1 UART2（RTCM3 入力・UBX 出力）11 キー

| キー | 期待値 | 意味 |
|---|---|---|
| `CFG_UART2_BAUDRATE` | `115200` | UART2 ボーレート |
| `CFG_UART2INPROT_UBX` | `1` | UBX 入力許可 |
| `CFG_UART2INPROT_NMEA` | `0` | NMEA 入力**無効** |
| **`CFG_UART2INPROT_RTCM3X`** | **`1`** | **RTCM3 入力許可（RTK の要）** |
| `CFG_UART2OUTPROT_UBX` | `1` | UBX 出力許可（RELPOSNED 監視用） |
| `CFG_UART2OUTPROT_NMEA` | `0` | NMEA 出力無効（帯域節約） |
| `CFG_NAVHPG_DGNSSMODE` | `0` | DGNSS モード（※§5-1 の矛盾参照） |
| `CFG_RATE_MEAS` | `200` | 測位間隔 200 ms（5 Hz） |
| `CFG_RATE_NAV` | `1` | ナビレート比 1 |
| `CFG_MSGOUT_UBX_NAV_PVT_UART2` | `0` | NAV-PVT 出力無効（MAVLink を使用） |
| **`CFG_MSGOUT_UBX_NAV_RELPOSNED_UART2`** | **`1`** | **RELPOSNED 出力有効（RTK 監視）** |

### 2.2 GNSS 信号 6 キー

| キー | 期待値 | 意味 |
|---|---|---|
| `CFG_SIGNAL_GPS_ENA` | `1` | GPS L1 有効 |
| `CFG_SIGNAL_GPS_L5_ENA` | `0` | GPS L5 無効 |
| `CFG_SIGNAL_GAL_ENA` | `1` | Galileo E1 有効 |
| `CFG_SIGNAL_GAL_E5A_ENA` | `0` | Galileo E5a 無効 |
| `CFG_SIGNAL_BDS_ENA` | `1` | BeiDou 有効 |
| `CFG_SIGNAL_GLO_ENA` | `1` | GLONASS L1 有効 |

> 基地局は **MSM4** を配信するため、ローバー側も対応する信号のみを有効化する構成です。

### 2.3 UART1（機体側ブリッジ）2 キー

| キー | 期待値 | 意味 |
|---|---|---|
| `CFG_UART1OUTPROT_UBX` | `1` | UART1 から UBX を出力（AP_Periph 向け） |
| `CFG_UART1_BAUDRATE` | `230400` | UART1 ボーレート（ArduPilot 既定） |

---

## 3. golden（退行監視対象）4 キー

飛行コントローラの自動設定などで意図せず退行しないよう、次の 4 キーを常時照合します
（出典: [`../../../../backend/f9p_configurator.py`](../../../../backend/f9p_configurator.py)
の `GOLDEN_VALUES` / `GOLDEN_LABELS`）。

| キー | Golden | ラベル |
|---|---|---|
| `CFG_NAVHPG_DGNSSMODE` | `3` | DGNSSモード (RTK Fixed) |
| `CFG_NAVSPG_DYNMODEL` | `7` | 動的モデル (Airborne <2g) |
| `CFG_RATE_MEAS` | `200` | 測位レート (5 Hz) |
| `CFG_UART1INPROT_RTCM3X` | `1` | UART1 RTCM3 入力許可 |

- `status` は `PASS`（一致）/ `FIXED`（退行を自動修正）/ `FAIL`（失敗）。
- 自動修正時は **`layer=7`（RAM + BBR + Flash）** で書き込み、再起動後も維持します。

実行例:

```bash
# 確認のみ
python3 gcs/backend/f9p_configurator.py --host 192.168.1.100 --port 5001 --no-fix

# 退行があれば自動修正
python3 gcs/backend/f9p_configurator.py --host 192.168.1.100 --port 5001

# 直接シリアル
python3 gcs/backend/f9p_configurator.py --serial /dev/ttyACM2 --baud 115200
```

出典: [`../../../../backend/README.md`](../../../../backend/README.md) §5 / §7。

> ⚠️ **`CFG_NAVHPG_DGNSSMODE` の矛盾**: 一括設定は `0`、golden 照合は `3` を期待します
> （[`../../common/fix_conditions.md`](../../common/fix_conditions.md) §6-1）。

---

## 4. RELPOSNED による RTK 状態監視

`UBX-NAV-RELPOSNED` の `carrSoln` を直接読む、最も**解像度の高い** RTK 状態監視です
（出典: [`../../../../rtk_tools/f9p_relposned_monitor.py`](../../../../rtk_tools/f9p_relposned_monitor.py)）。

### 4.1 CLI

```bash
# 単発
python3 -m gcs.rtk_tools.f9p_relposned_monitor --port /dev/ttyAMA4 --once

# バッチ（既定: 30 秒間隔 × 10 回）
python3 -m gcs.rtk_tools.f9p_relposned_monitor --interval 15 --count 20

# CSV 出力先を指定
python3 -m gcs.rtk_tools.f9p_relposned_monitor --csv logs/relposned_monitor_<ts>.csv
```

| オプション | 既定値 | 意味 |
|---|---|---|
| `--port` | `/dev/ttyAMA4` | F9P 接続 RPi UART4 |
| `--baud` | `115200` | ボーレート |
| `--interval` | `30.0` | ポーリング間隔 [秒] |
| `--count` | `10` | ポーリング回数 |
| `--once` | — | 単発ポーリングして終了 |
| `--csv` | `logs/relposned_monitor_<ts>.csv` | CSV 出力先 |
| `--log-level` | `INFO` | `DEBUG`/`INFO`/`WARNING`/`ERROR` |

### 4.2 判定（verdict）と終了コード

| 判定 | 条件 | 終了コード |
|---|---|---|
| `SUCCESS` | 最高到達 `carrSoln == 2`（FIXED） | 0 |
| `SEMI-SUCCESS` | 最高到達 `carrSoln == 1`（FLOAT まで・FIXED 未達） | 1 |
| `NEED_DIAGNOSIS` | FIXED / FLOAT 未達 | 2 |
| （`--once` の NO_RESPONSE） | 応答なし | 3 |

出力サマリには `carrSoln=FIXED(2) / FLOAT(1) / NONE(0)` の回数、
**最高到達 `carrSoln`**、**初回 FIXED 到達ポーリング番号**、CSV パスが含まれます。

### 4.3 CSV に記録される項目

`timestamp` / `carrSoln` / `carrSoln_name` / `relPosValid` / `relPosN` / `relPosE` / `relPosD` /
`accN` / `accE` / `accD` / `refStationId` / `flags` / `verdict`

出典: 同上の `batch_poll()`。

> **注意**: RELPOSNED は本来「基準局からの相対位置」のメッセージです。
> 単一基準局構成でも `carrSoln` と `relPosValid` は搬送波位相解の状態を表すため、
> RTK 状態の監視に利用できます。

---

## 5. 適用方法

### 5.1 一括設定（19 キー write-verify）

```bash
python3 -m gcs.rtk_tools.f9p_config_all --role rover --port /dev/tty.usbmodemXXX
```

- 既存設定との**差分のみ**を書き込み、全キーを読み戻して検証します。
- `--no-flash` で RAM のみ（電源再投入で元に戻る）。

出典: [`../../../../rtk_tools/README.md`](../../../../rtk_tools/README.md)。

### 5.2 Web UI から

運用タブの `f9p_write_verify`（`base` / `rover` 選択）で実行できます。
Flash 書き込みを伴うため**確認モーダル**が表示されます。

出典: [`../../../OPERATIONS.md`](../../../OPERATIONS.md) §1。

### 5.3 飛行前の一括確認

```bash
python3 gcs/preflight/runner.py --host 192.168.1.100 --port 5001
```

Item 2（コンフィグ照合）が `CFG_NAVHPG_DGNSSMODE` / `CFG_NAVSPG_DYNMODEL` /
`CFG_RATE_MEAS` / `CFG_UART1INPROT_RTCM3X` の退行を検出します
（出典: [`../../../../preflight/README.md`](../../../../preflight/README.md) §1）。
`--auto-fix` で自動修正も可能です。

---

## 6. 品質指標との関係

| 指標 | 取得元 | 参照 |
|---|---|---|
| `fix_type`（0〜6） | MAVLink `GPS_RAW_INT` | [`../../common/rtk_details.md`](../../common/rtk_details.md) §2 |
| `carrSoln` | UBX `NAV-RELPOSNED` | 本資料 §4 |
| 水平/垂直標準偏差 | `GPS_RAW_INT` の緯度経度高度 | [`../../common/error_and_accuracy.md`](../../common/error_and_accuracy.md) §3.2 |
| RTCM 到達・age・CRC・msgUsed | UBX `RXM-RTCM` | 同上 §3.3 |

---

## 7. 出典（`gcs/` 内のみ）

| ファイル | 参照箇所 |
|---|---|
| `gcs/rtk_tools/f9p_config_all.py` | `_UART2_ROVER_CFG_KEYS` / `_GNSS_SIGNAL_CFG_KEYS` / キー表 #14〜#31 / `F9pAllConfigurator.write_and_verify(role="rover")` |
| `gcs/rtk_tools/f9p_relposned_monitor.py` | `flags` ビット定義 / `carrSoln` 抽出 / `batch_poll()` / `main()` の引数と終了コード |
| `gcs/rtk_tools/README.md` | ツール一覧 / layer / 復元手順 |
| `gcs/backend/f9p_configurator.py` | `GOLDEN_VALUES` / `GOLDEN_LABELS` / `STATUS_*` |
| `gcs/backend/README.md` | §2 監視対象 / §5 使い方 / §6 戻り値 / §7 Flash 永続化 |
| `gcs/preflight/README.md` | §1 判定項目 / §4 使い方 |
| `gcs/ekf_failsafe/golden.py` | `GPS_TYPE = 9`（DroneCAN） |
| `gcs/docs/OPERATIONS.md` | `f9p_write_verify` / `f9p_verify` 等 |
| `gcs/config/config.yaml` | `rover.mavlink_baud = 921600` 等 |

> 関連: [`../f9p_base/README.md`](../f9p_base/README.md)（基地局）／
> [`../pixhawk_ardupilot/README.md`](../pixhawk_ardupilot/README.md)（EKF への取り込み）
