# 基地局 F9P（ZED-F9P / Base）

RTK 補正データ（RTCM3）を生成・配信する**基地局**としての u-blox ZED-F9P の
設定と運用手順です。

- 索引: [`../../README.md`](../../README.md)
- 条件の実値: [`../../common/fix_conditions.md`](../../common/fix_conditions.md)
- 手順書: [`../../../RTK_PROCEDURES_MANUAL.md`](../../../RTK_PROCEDURES_MANUAL.md) §2 Step 1

> **出典ポリシー**: 本資料は `gcs/` パッケージ内のみを出典とします。

---

## 1. 役割

| 項目 | 内容 |
|---|---|
| 役割 | 既知の**固定座標**に置き、全 GNSS 衛星の観測を基準として **RTCM3 補正**を生成 |
| 動作モード | **TMODE3 Fixed Mode**（固定座標モード） |
| 出力 | RTCM3（1005 / 1006 / 1074 / 1084 / 1094 / 1124 / 1230） |
| 配信 | TCP **2101**（＋任意で UDP ブロードキャスト） |
| 接続 | Mac に USB 接続（例: `/dev/cu.usbmodem112301`） |

出典: [`../../../../rtk_tools/rtk_base_station_v2.py`](../../../../rtk_tools/rtk_base_station_v2.py)
（モジュール docstring の起動フロー、`Config`）、
[`../../../RTK_PROCEDURES_MANUAL.md`](../../../RTK_PROCEDURES_MANUAL.md) §1。

---

## 2. 設定される 20 キー

基地局ロール（`--role base`）で write-verify されるキーは **20 件**です
（出典: [`../../../../rtk_tools/f9p_config_all.py`](../../../../rtk_tools/f9p_config_all.py)
の `_build_key_table()` と `_RTCM_MSG_KEYS_UART1` / `_RTCM_MSG_KEYS_USB`）。

### 2.1 TMODE3（固定座標）6 キー

| # | キー | 期待値 | 意味 |
|---|---|---|---|
| 1 | `CFG_TMODE_MODE` | `2` | FIXED Mode（2=Fixed） |
| 2 | `CFG_TMODE_POS_TYPE` | `0` | 位置タイプ（0=LLA） |
| 3 | `CFG_TMODE_LAT` | `lat × 1e7`（I4） | 緯度（1e-7 度単位） |
| 4 | `CFG_TMODE_LON` | `lon × 1e7`（I4） | 経度（1e-7 度単位） |
| 5 | `CFG_TMODE_HEIGHT` | `alt × 100`（I4） | 楕円体高（**cm 単位**） |
| 6 | `CFG_TMODE_FIXED_POS_ACC` | `10.0`（R8） | 固定座標の精度表示 [m] |

> **単位に注意**: 緯度経度は **1e-7 度**、高さは **cm** で書き込まれます。
> 高さは**楕円体高（HAE）**です（[`../../common/coordinate_systems.md`](../../common/coordinate_systems.md) §2）。

### 2.2 RTCM3 出力（UART1 → 機体側）7 キー

| # | キー | 期待値 | 内容 |
|---|---|---|---|
| 7 | `CFG_MSGOUT_RTCM_3X_TYPE1005_UART1` | 1 | Station ARP |
| 8 | `CFG_MSGOUT_RTCM_3X_TYPE1006_UART1` | 1 | Station ARP + アンテナ |
| 9 | `CFG_MSGOUT_RTCM_3X_TYPE1074_UART1` | 1 | GPS MSM4 |
| 10 | `CFG_MSGOUT_RTCM_3X_TYPE1084_UART1` | 1 | GLONASS MSM4 |
| 11 | `CFG_MSGOUT_RTCM_3X_TYPE1094_UART1` | 1 | Galileo MSM4 |
| 12 | `CFG_MSGOUT_RTCM_3X_TYPE1124_UART1` | 1 | BeiDou MSM4 |
| 13 | `CFG_MSGOUT_RTCM_3X_TYPE1230_UART1` | 1 | GLONASS バイアス |

### 2.3 RTCM3 出力（USB → Mac 側）7 キー

キー名の接尾辞が `_USB` になる以外は 2.2 と同一です
（`CFG_MSGOUT_RTCM_3X_TYPE1005_USB` … `..._1230_USB`）。

> USB 側のキー ID は実機確認済みの値が `_KEY_MSGOUT_RTCM3_TYPE*_USB` として
> 実装されています（例: 1005 → `0x209102C0`）。

### 2.4 MSM 形式について

本システムが実際に有効化するのは **MSM4（1074 / 1084 / 1094 / 1124）** です。
MSM7 を使う場合はキー定義の変更が必要です（
[`../../common/fix_conditions.md`](../../common/fix_conditions.md) §6-2 の矛盾項目参照）。

---

## 3. 起動（Mac 側）

```bash
cd ~/rtk-pipeline-local
source .venv/bin/activate
python3 gcs/rtk_tools/rtk_base_station_v2.py \
    --config gcs/config/base_station.json \
    --serial-port /dev/cu.usbmodem112301
```

- 待機完了の確認: **`TCP listening on 0.0.0.0:2101`** が表示される
- ポート名は環境に応じて変更

出典: [`../../../RTK_PROCEDURES_MANUAL.md`](../../../RTK_PROCEDURES_MANUAL.md) §2 Step 1。

### 3.1 起動時の処理フロー

```text
1. JSON 設定ファイルを読み込み（base_station.json）
2. F9P を基地局モードに設定（毎回実行・CFG-VALSET で冪等）
     STEP1: TMODE3 Fixed Mode 設定
     STEP2: RTCM3 出力メッセージ有効化
     STEP3: 設定確認（check_tmode3）
3. シリアルポートを開いて RTCM 受信開始
4. TCP サーバー起動（ポート 2101）
5. UDP ブロードキャスト（オプション）
```

出典: [`../../../../rtk_tools/rtk_base_station_v2.py`](../../../../rtk_tools/rtk_base_station_v2.py)
のモジュール docstring。

### 3.2 主な設定値（`Config`）

| キー | 既定値 | 意味 |
|---|---|---|
| `serial_port` | `COM8` | 実運用では JSON で上書き |
| `baudrate` | `115200` | RTCM 読み取り用 |
| `f9p_baudrate` | `38400` | 設定時のボーレート |
| `mode` | `manual` | `manual` / `auto`（未実装）/ `time` |
| `fixed_lat/lon/alt` | `None` | JSON で指定（未設定なら F9P 設定をスキップ） |
| `skip_f9p_config` | `False` | `True` で F9P 設定を丸ごとスキップ |
| `save_to_flash` | `True` | Flash 保存 |
| `tcp_host` / `tcp_port` | `0.0.0.0` / `2101` | RTCM 配信 |
| `enable_udp` | `False` | UDP ブロードキャストの有効化 |
| `udp_broadcast_host` / `port` | `255.255.255.255` / `50010` | 同ブロードキャスト先 |

出典: 同上の `Config` データクラス、および `_merge_config()`（優先順位: CLI > JSON > 既定）。

### 3.3 `mode` の使い分け

| 値 | 挙動 |
|---|---|
| `manual` | JSON の `fixed_lat/lon/alt` で TMODE3 を設定（**標準**） |
| `auto` | 自動測量（Survey-In）は**未実装**。警告を出して F9P 設定をスキップ |
| `time` | F9P が **TIME モードで事前設定済み**を前提とし、再設定しない |

出典: 同上の `_run_f9p_configuration()`。

---

## 4. 固定座標の決め方

### 4.1 設定ファイル

| ファイル | 用途 |
|---|---|
| [`../../../../config/base_station.json`](../../../../config/base_station.json) | 実運用の基地局設定（`fixed_lat` / `fixed_lon` / `fixed_alt`） |
| [`../../../../config/config.yaml`](../../../../config/config.yaml) | 統合テスト用の既定値（`base_station.fixed_*`） |

`base_station.json` の現在値（例）:

```json
{
    "mode": "manual",
    "serial_port": "/dev/cu.usbmodem112301",
    "baudrate": 115200,
    "fixed_lat": 36.0756835,
    "fixed_lon": 136.2135045,
    "fixed_alt": 45.72,
    "save_to_flash": false,
    "auto_obs_duration": 300
}
```

`config.yaml` 側のコメントには `fixed_alt` が **楕円体高 HAE [m]** であることが
明記されています（`fixed_alt: 44.80  # 楕円体高 HAE [m]`）。

> ⚠️ **`fixed_pos` というキーは存在しません。**
> 手順書に `fixed_pos` と書かれている箇所がありますが、実装（`Config` / JSON 読み込み）が
> 参照するのは `fixed_lat` / `fixed_lon` / `fixed_alt` の 3 キーです
> （[`../../common/fix_conditions.md`](../../common/fix_conditions.md) §6-3）。

### 4.2 アンテナ移動時の再測量

アンテナ設置場所を変更した場合、**その場で実測**して座標を更新します。

```bash
python3 single_unit_test/run_survey.py --set-rover --duration 30
```

> `single_unit_test/run_survey.py` は手順書が参照する **`gcs/` 外のスクリプト**
> （リポジトリ直下）です。出典:
> [`../../../RTK_PROCEDURES_MANUAL.md`](../../../RTK_PROCEDURES_MANUAL.md) §2 Step 1。

- 出力された**緯度・経度・楕円体高 HAE** を `base_station.json` に書き込みます。
- 数十〜数百メートルのズレがあると、幾何学的な位相差の矛盾により
  ローバー F9P が RTK 計算を拒否し、`3D_FIX` のまま昇格しません。

出典: [`../../../RTK_PROCEDURES_MANUAL.md`](../../../RTK_PROCEDURES_MANUAL.md) §2 Step 1 の注意、
および同 §6 トラブルシューティング表。

---

## 5. 検証・監視

| 目的 | 手段 | 起動例 |
|---|---|---|
| **設定の write-verify**（正典） | `f9p_config_all.py --role base` | `python3 -m gcs.rtk_tools.f9p_config_all --role base --port /dev/tty.usbmodemXXX` |
| 設定ベースラインとの差分監視 | `f9p_config_monitor.py --role base` | `python3 -m gcs.rtk_tools.f9p_config_monitor --role base --port ...` |
| **RTCM3 ストリームの検証** | `verify_rtcm_tcp.py` | `python3 -m gcs.rtk_tools.verify_rtcm_tcp --host localhost --port 2101` |
| golden 照合（レジスタ 4 キー） | `gcs/backend/f9p_configurator.py` | `--host <機体IP> --port 5001` |
| Web UI から設定読み取り | 運用タブ `f9p_verify` | [`../../../OPERATIONS.md`](../../../OPERATIONS.md) |

出典: [`../../../../rtk_tools/README.md`](../../../../rtk_tools/README.md) のツール一覧、
[`../../../../OPERATIONS.md`](../../../OPERATIONS.md) の操作カタログ。

### 5.1 write-verify の原則

書込 → 読み戻し（`CFG-VALGET`）→ 一致確認、の順で実施します。
不一致が残る場合は `results["all_ok"]` が偽となり、警告がログに出ます
（出典: [`../../../../rtk_tools/rtk_base_station_v2.py`](../../../../rtk_tools/rtk_base_station_v2.py)
の `_run_f9p_configuration()`）。

---

## 6. RAM / Flash の扱い

| layer | 値 | 意味 |
|---|---|---|
| `LAYER_RAM` | 1 | 揮発（電源断で消える） |
| `LAYER_BBR` | 2 | Battery Backed RAM |
| `LAYER_FLASH` | 4 | 不揮発（再起動後も維持） |
| `LAYER_ALL` | 7 | RAM + BBR + Flash |

- `f9p_config_all.py` は**既定で `LAYER_ALL = 7`**（`save_to_flash=True`）。
- RAM のみで試す場合は **`--no-flash`**。
- 基地局サービス側は `save_to_flash`（JSON キー）で制御します。
  `base_station.json` の現在値は **`false`** です。

出典: [`../../../../rtk_tools/README.md`](../../../../rtk_tools/README.md)、
[`../../../../rtk_tools/f9p_config_all.py`](../../../../rtk_tools/f9p_config_all.py)、
[`../../../../config/base_station.json`](../../../../config/base_station.json)。

> ⚠️ **復元注意**: Flash まで書いた場合、元に戻すには正しい値で `f9p_config_all.py` を
> 再実行する必要があります（`--role base --lat <元の緯度> --lon <元の経度> --alt <元の楕円体高>`）。
> 基準座標は `gcs/config/config.yaml` の `base_station.fixed_lat/lon/alt` を参照。

---

## 7. 注意事項

1. **座標はアンテナ位置（APC）と数メートル以内で一致**させること（§4.2）。
2. **高さは楕円体高 HAE**（標高 MSL ではない）。
3. シリアルポートは**排他**。他ツールと同時に開かないこと。
4. 座標再設定・Flash 書込は**危険操作**として Web UI で確認モーダルが出ます
   （出典: [`../../../OPERATIONS.md`](../../../OPERATIONS.md) §1）。
5. 設定変更前に `f9p_verify`（読み取りのみ）で現在値を確認すること。

出典: [`../../../RTK_PROCEDURES_MANUAL.md`](../../../RTK_PROCEDURES_MANUAL.md) §3 / §4 / §6、
[`../../../OPERATIONS.md`](../../../OPERATIONS.md)。

---

## 8. 出典（`gcs/` 内のみ）

| ファイル | 参照箇所 |
|---|---|
| `gcs/rtk_tools/f9p_config_all.py` | `_build_key_table()`（基地局 20 キー）/ `_RTCM_MSG_KEYS_UART1` / `_RTCM_MSG_KEYS_USB` / `_KEY_*` / `F9pAllConfigurator.write_and_verify()` |
| `gcs/rtk_tools/rtk_base_station_v2.py` | docstring の起動フロー / `Config` / `_merge_config()` / `_run_f9p_configuration()` / `start()` |
| `gcs/rtk_tools/README.md` | ツール一覧 / layer の定義 / 復元手順 |
| `gcs/config/base_station.json` | `mode` / `fixed_lat` / `fixed_lon` / `fixed_alt` / `save_to_flash` |
| `gcs/config/config.yaml` | `base_station.*`（`fixed_alt` は楕円体高 HAE と明記） |
| `gcs/backend/f9p_configurator.py` | `GOLDEN_VALUES` |
| `gcs/backend/README.md` | §2 監視対象 / §5 使い方 |
| `gcs/docs/OPERATIONS.md` | 操作カタログ（`base_tmode3_set` 等） |
| `gcs/docs/RTK_PROCEDURES_MANUAL.md` | §2 Step 1 / §3 / §4 / §6 |

> 関連: [`../f9p_rover/README.md`](../f9p_rover/README.md)（移動局）／
> [`../mac_gcs/README.md`](../mac_gcs/README.md)（配信側ホスト）
