# RTK-FIXED 確立・維持の条件（実値まとめ）

本資料は、**RTK-FIXED（`fix_type = 6`）に到達し、それを維持するための条件**を、
`gcs/` 内の実装値・設定値に基づいて列挙するものです。

> **出典ポリシー**: `gcs/` パッケージ内のみ。`パス:行` を根拠として併記します。

- 索引: [`../README.md`](../README.md)
- 実装定義: [`rtk_details.md`](rtk_details.md)
- 手順: [`../../RTK_PROCEDURES_MANUAL.md`](../../RTK_PROCEDURES_MANUAL.md)

---

## 1. 到達条件チェックリスト

FIXED に到達するには、**全リンクが同時に成立**している必要があります。
どれか 1 つでも欠けると `3D_FIX` のまま昇格しません。

### A. 基地局側

| # | 条件 | 実値 / 根拠 |
|---|---|---|
| A-1 | F9P が **TMODE3 Fixed Mode** で動作 | `CFG_TMODE_MODE = 2` |
| A-2 | 固定座標が **LLA（緯度経度楕円体高）** で設定 | `CFG_TMODE_POS_TYPE = 0` |
| A-3 | 固定座標の精度表示 | `CFG_TMODE_FIXED_POS_ACC = 10.0` m |
| A-4 | 固定座標が **実アンテナ位置と数メートル以内** | 数十〜数百 m ずれるとローバーが RTK 計算を拒否 |
| A-5 | **RTCM3 を出力**（UART1 7 件 / USB 7 件） | 1005 / 1006 / 1074 / 1084 / 1094 / 1124 / 1230 |
| A-6 | RTCM3 を **TCP:2101** で配信 | `Config.tcp_port = 2101` |

出典: [`../../../rtk_tools/f9p_config_all.py`](../../../rtk_tools/f9p_config_all.py) の
`_build_key_table()`、[`../../../rtk_tools/rtk_base_station_v2.py`](../../../rtk_tools/rtk_base_station_v2.py)
の `Config` / 起動フロー、[`../../RTK_PROCEDURES_MANUAL.md`](../../RTK_PROCEDURES_MANUAL.md) §2 Step 1。

### B. 配送経路

| # | 条件 | 実値 / 根拠 |
|---|---|---|
| B-1 | **MAVLink 2.0** を使用 | `os.environ["MAVLINK20"] = "1"` |
| B-2 | **RTS/CTS ハードウェアフロー制御**を有効化 | `serial.Serial(..., rtscts=True)`（既定 True） |
| B-3 | Pixhawk シリアルは **`/dev/ttyAMA0` @ 921600 bps** | `--serial` / `--baud` の既定値 |
| B-4 | RTCM を **180 バイト以下**に分割して `GPS_RTCM_DATA` で送出 | `MAX_SIZE = 180` / `MAX_FRAGS = 4` |

出典: [`../../../rtk_tools/mavlink_bridge.py`](../../../rtk_tools/mavlink_bridge.py)
（モジュール冒頭、`--serial` / `--baud` / `--rtscts`、`rtcm_tcp_to_mavlink()`）、
[`../../RTK_PROCEDURES_MANUAL.md`](../../RTK_PROCEDURES_MANUAL.md) §6 トラブルシューティング。

> ⚠️ **既知の落とし穴**（手順書 §6）: MAVLink 1.0 やフロー制御なしでは
> 921600 bps でパケット欠損／破壊が発生し、RTK になりません。

### C. 移動局（ローバー）側

| # | 条件 | 実値 | 根拠 |
|---|---|---|---|
| C-1 | UART2 のボーレート | `115200` | `_UART2_ROVER_CFG_KEYS` |
| C-2 | UART2 に **UBX 入力**を許可 | `CFG_UART2INPROT_UBX = 1` | 同上 |
| C-3 | UART2 に **RTCM3 入力**を許可 | `CFG_UART2INPROT_RTCM3X = 1` | 同上 |
| C-4 | NMEA 入力は無効 | `CFG_UART2INPROT_NMEA = 0` | 同上 |
| C-5 | DGNSS モード | `CFG_NAVHPG_DGNSSMODE = 0` | 同上（※§6-1 の矛盾参照） |
| C-6 | 測位レート | `CFG_RATE_MEAS = 200`（5 Hz）、`CFG_RATE_NAV = 1` | 同上 |
| C-7 | GPS 信号有効 | `CFG_SIGNAL_GPS_ENA = 1` | `_GNSS_SIGNAL_CFG_KEYS` |
| C-8 | Galileo 信号有効 | `CFG_SIGNAL_GAL_ENA = 1` | 同上 |
| C-9 | BeiDou 信号有効 | `CFG_SIGNAL_BDS_ENA = 1` | 同上 |
| C-10 | GLONASS 信号有効 | `CFG_SIGNAL_GLO_ENA = 1` | 同上 |
| C-11 | L5 / E5a は無効 | `CFG_SIGNAL_GPS_L5_ENA = 0` / `CFG_SIGNAL_GAL_E5A_ENA = 0` | 同上 |
| C-12 | RELPOSNED 出力有効（監視用） | `CFG_MSGOUT_UBX_NAV_RELPOSNED_UART2 = 1` | 同上 |
| C-13 | NAV-PVT 出力は無効（MAVLink を併用） | `CFG_MSGOUT_UBX_NAV_PVT_UART2 = 0` | 同上 |

出典: [`../../../rtk_tools/f9p_config_all.py`](../../../rtk_tools/f9p_config_all.py) の
`_UART2_ROVER_CFG_KEYS` / `_GNSS_SIGNAL_CFG_KEYS`。

### D. ローバー F9P の golden（退行監視対象）

F9P の設定は、飛行コントローラの自動設定などで**意図せず退行**することがあります。
そのため 4 キーを golden 値として常時照合します。

| キー | Golden 値 | 意味 |
|---|---|---|
| `CFG_NAVHPG_DGNSSMODE` | `3` | RTK Fixed（※§6-1 の矛盾参照） |
| `CFG_NAVSPG_DYNMODEL` | `7` | Airborne <2g |
| `CFG_RATE_MEAS` | `200` | 5 Hz（200 ms） |
| `CFG_UART1INPROT_RTCM3X` | `1` | UART1 RTCM3 入力許可 |

出典: [`../../../backend/f9p_configurator.py`](../../../backend/f9p_configurator.py) の `GOLDEN_VALUES`、
[`../../../backend/README.md`](../../../backend/README.md) §2。
照合・自動修正は `python3 gcs/backend/f9p_configurator.py --host <機体IP> --port 5001`
（`--no-fix` で確認のみ）で実行できます。

### E. Pixhawk / ArduPilot 側（`ekf_sources`）

| パラメータ | Golden | 意味 |
|---|---|---|
| `AHRS_EKF_TYPE` | 3 | EKF3 |
| `EK3_ENABLE` | 1 | EKF3 有効 |
| `EK3_SRC1_POSXY` | 3 | 水平位置 = GPS（RTK を投入） |
| `EK3_SRC1_POSZ` | 3 | 高度 = GPS |
| `EK3_SRC1_VELXY` | 3 | 水平速度 = GPS |
| `EK3_SRC1_VELZ` | 3 | 垂直速度 = GPS |
| `EK3_SRC1_YAW` | 1 | 方位 = コンパス（単一 F9P） |
| `GPS_TYPE` | 9 | DroneCAN（`GPS_TYPE_UAVCAN`） |
| `GPS_AUTO_CONFIG` | 2 | 全自動設定（DroneCAN AutoConfig） |
| `GPS_PRIMARY` | 0 | プライマリ GPS = 1 番目 |
| `GPS_AUTO_SWITCH` | 0 | GPS 自動切替**無効**（劣化時に勝手に切り替えない） |

出典: [`../../../ekf_failsafe/golden.py`](../../../ekf_failsafe/golden.py) の `GOLDEN_PARAMS`、
[`../../../ekf_failsafe/README.md`](../../../ekf_failsafe/README.md) §2-1。

---

## 2. 昇格シーケンスと観測

補正リンクが成立すると、次の順に昇格します
（出典: [`../../RTK_PROCEDURES_MANUAL.md`](../../RTK_PROCEDURES_MANUAL.md) §2 Step 3）。

```text
3D_FIX → DGPS → RTK_FLOAT → RTK_FIXED
```

| 段階 | 目安 | 備考 |
|---|---|---|
| `3D_FIX` 到達 | 衛星捕捉後 | 補正なし |
| `DGPS` 到達 | RTCM 到達直後 | コード補正 |
| `RTK_FLOAT` 到達 | 数秒〜 | 搬送波位相は使えている |
| `RTK_FIXED` 到達（TTFF） | **上限 120 秒** | `ttff_sec_max = 120.0` |

TTFF の上限は [`../../../config/config.yaml`](../../../config/config.yaml) の
`pass_criteria.ttff_sec_max` です。

監視は Web ダッシュボードの RTK Fix バッジ、または
`gcs/preflight/runner.py`（Item 1）で定量化します。

---

## 3. PASS / FAIL の判定基準（実値）

### 3.1 統合テスト（`config.yaml` の `pass_criteria`）

| キー | 既定値 | 意味 |
|---|---|---|
| `fixed_rate_pct_min` | `80.0` | FIXED 維持率の**下限** [%] |
| `max_float_transitions` | `5` | FLOAT 遷移回数の**上限** |
| `ttff_sec_max` | `120.0` | TTFF の**上限** [秒] |
| `require_phase1` | `true` | ① が FAIL なら全体も FAIL |

出典: [`../../../config/config.yaml`](../../../config/config.yaml) の `pass_criteria`。

### 3.2 飛行前セルフテスト（preflight）

| キー | 既定値 | 意味 |
|---|---|---|
| `connection.host` / `port` | `192.168.1.100` / `5001` | DroneCAN Serial Forwarding |
| `monitor.duration_sec` | `60.0` | 動的観測時間 [秒] |
| `monitor.age_alert_threshold` | `10.0` | RTK age アラート [秒] |
| `criteria.fixed_rate_pct_min` | `80.0` | FIXED 率の下限 [%] |
| `criteria.max_float_transitions` | `5` | FLOAT 遷移回数の上限 |
| `criteria.ttff_sec_max` | `120.0` | TTFF の上限 [秒] |
| `criteria.base_rate_min_fps` | `1.0` | 基地局 RTCM 到達レートの下限 [msg/s] |
| `reconnect.auto` | `true` | 自動再接続 |

出典: [`../../../preflight/README.md`](../../../preflight/README.md) §6。

### 3.3 実飛行試験（`FlightSpec`・仮置き）

| パラメータ | 既定値（仮） | 意味 |
|---|---|---|
| `fixed_rate_pct_min` | `80.0` | FIXED 維持率（初回 FIXED 以降）下限 [%] |
| `max_float_transitions` | `5` | FLOAT 遷移回数 上限 |
| `ekf_consistency_pct_min` | `95.0` | FIXED 時に EKF 位置健全である割合 下限 [%] |
| `ekf_horiz_err_max_m` | `0.10` | FIXED 時の EKF 水平位置誤差(1σ) 上限 [m] |
| `ekf_vert_err_max_m` | `0.20` | FIXED 時の EKF 垂直位置誤差(1σ) 上限 [m] |
| `hdop_max_m` | `1.4` | HDOP 上限 [m] |
| `max_severe_degradations` | `3` | 重度劣化（FS 対象）の許容回数 |
| `require_failsafe_evidence` | `True` | 重度劣化時に FS 発動の証跡を必須とする |

出典: [`../../../flight_test/README.md`](../../../flight_test/README.md) §7。
> これらの値は **仮置き・要定義**です（同 §7 および §10）。

---

## 4. 補正リンク健全性の条件

| 指標 | 警告 / 基準 | 出典 |
|---|---|---|
| RTK age | warn `5.0` s / alert `10.0` s | [`../../../config/config.yaml`](../../../config/config.yaml) |
| CRC エラー率 | alert `5.0` % | 同上 |
| msgUsed 比率 | 下限 `50.0` % | 同上 |
| 基地局到達レート | 下限 `1.0` msg/s | [`../../../preflight/README.md`](../../../preflight/README.md) |

これらはすべて**ローバー F9P の UBX ストリーム**（`UBX-NAV-PVT` / `UBX-RXM-RTCM`）から
取得します。評価は `gcs/preflight/README.md` §1 の Item 3 および「基地局レート」です。

---

## 5. FIXED を「維持」する条件とフェイルセーフ

### 5.1 脱落（FIXED → FLOAT）の主因と対策

| 要因 | 対策 |
|---|---|
| マルチパス（建物・地面・機体の反射） | 開けた場所、アンテナ視界確保、低仰角マスク |
| サイクルスリップ | アンテナ・ケーブルの固定、振動低減 |
| 補正データの途絶（RTK age 上昇） | Wi-Fi/TCP の安定化、`reconnect.auto`（既定 ON） |
| CRC エラー多発 | シリアルのフロー制御（RTS/CTS）、ボーレート整合 |
| 急激な運動（動的モデル不整合） | `CFG_NAVSPG_DYNMODEL = 7`（Airborne <2g） |
| GLONASS 補正の不整合 | `GPS_GNSS_MODE = 47`（GLONASS 無効）で復元 |

脱落は `fixed_to_float_count` / `float_transition_count` として定量化されます
（出典: [`rtk_details.md`](rtk_details.md) §4）。

### 5.2 フェイルセーフ（`failsafe` 群）

| パラメータ | Golden | 意味 |
|---|---|---|
| `FS_GCS_ENABLE` | 1 | GCS 喪失時 Always RTL |
| `FS_EKF_ACTION` | 1 | EKF フェイルセーフ動作 = Land |
| `FS_EKF_THRESH` | 0.8 | EKF 整合性閾値（低いほど敏感） |
| `FS_GPS_ENABLE` | 1 | GPS 喪失時 Land |
| `GPS_HDOP_GOOD` | 140 | アームに必要な GPS ロック品質（HDOP 1.4 m） |
| `GPS_HDOP_MAX` | 200 | GPS フェイルセーフ発動 HDOP（2.0 m） |
| `GPS_GNSS_MODE` | 47 | GLONASS(bit6) 無効の復元値（GPS+SBAS+Galileo+BeiDou+QZSS） |

出典: [`../../../ekf_failsafe/golden.py`](../../../ekf_failsafe/golden.py) の `GOLDEN_PARAMS` および
`GNSS_MODE_BITS`、[`../../../ekf_failsafe/README.md`](../../../ekf_failsafe/README.md) §2-2。

### 5.3 「重度劣化（FS 対象）」と「精度劣化」の区別

| 事象 | 分類 | 対応する FS |
|---|---|---|
| `gps_loss`（`fix_type` 0/1） | **重度劣化（FS 対象）** | `FS_GPS_ENABLE` |
| `ekf_unhealthy`（EKF フラグ喪失） | **重度劣化（FS 対象）** | `FS_EKF_ACTION` |
| `rtk_loss`（FIXED/FLOAT → DGPS/3D） | 精度劣化（位置は残る） | — |
| `hdop_high` | 精度劣化 | — |

出典: [`../../../flight_test/README.md`](../../../flight_test/README.md) §2。

> **設計意図**: `GPS_AUTO_SWITCH = 0` により、RTK が劣化しても
> 自動で他 GPS へ切り替えず、劣化を**観測可能な状態に保つ**設計です
> （出典: [`../../../ekf_failsafe/golden.py`](../../../ekf_failsafe/golden.py)）。

---

## 6. 既知の矛盾と要確認事項（詳細）

`gcs/` 内で記述が割れている項目を、根拠付きで列挙します。
**運用時は「採用」に従ってください。**

### 6-1. `CFG_NAVHPG_DGNSSMODE`：`0` か `3` か

| 出典 | 値 | 記述 |
|---|---|---|
| [`../../../rtk_tools/f9p_config_all.py`](../../../rtk_tools/f9p_config_all.py) の `_UART2_ROVER_CFG_KEYS` | **`0`** | `("CFG_NAVHPG_DGNSSMODE", 0)` |
| 同上（キー表 #20 の `desc`） | — | `"RTK Float+Fixed both (DGNSSMODE=3 blocks FLOAT→FIXED transition!)"` |
| [`../../../backend/f9p_configurator.py`](../../../backend/f9p_configurator.py) の `GOLDEN_VALUES` | **`3`** | `"CFG_NAVHPG_DGNSSMODE": 3,  # RTK Fixed` |
| [`../../../backend/README.md`](../../../backend/README.md) §2 | **`3`** | 意味: 「RTK Fixed」 |
| [`../../../ekf_failsafe/README.md`](../../../ekf_failsafe/README.md) §8 | — | レジスタ層の照合対象として `CFG-NAVHPG-DGNSSMODE` を挙げる |

- **採用（本資料）**: **両論併記**。
  - 移動局の一括設定（39 キー write-verify）は `0` を書き込みます。
  - レジスタ golden 照合（`F9pConfigGuard`）は `3` を期待値とします。
  - 同一受信機に対し **2 つの機構が異なる期待値を持つ**ため、
    golden 照合が「退行」を検出→自動修正（`3`）→ 一括設定（`0`）で戻る、
    という往復が起こり得ます。
- **要確認**: u-blox Interface Description（UBX-18010854）で
  `CFG-NAVHPG-DGNSSMODE` の定義を確認し、`gcs/` 内の期待値をどちらかに統一すること。

### 6-2. 基地局設定が 2 経路あり、RTCM 形式と `POS_TYPE` が食い違う

**経路 A（現行・正典）**: `gcs/rtk_tools/f9p_config_all.py` の
`F9pAllConfigurator.write_and_verify()` を `rtk_base_station_v2.py` が呼ぶ。

| 項目 | 値 | 出典 |
|---|---|---|
| `CFG_TMODE_POS_TYPE` | **`0`（LLA）** | [`../../../rtk_tools/f9p_config_all.py`](../../../rtk_tools/f9p_config_all.py) キー表 #2 |
| RTCM | **MSM4**（1074 / 1084 / 1094 / 1124） | 同 キー表 #9〜#12、`_RTCM_MSG_KEYS_*` |

**経路 B（旧・`--setup-base` 経由）**: `gcs/integration/runner.py --setup-base` →
`run_base_setup()` が再利用する**退避済みの旧コンフィギュレータ**（`gcs/` 外）の
`F9pConfiguratorV2.configure(lat, lon, alt, save)` による経路。

| 項目 | 値 | 出典 |
|---|---|---|
| `CFG_TMODE_POS_TYPE` | **`1`** | [`../../../hw_verify/README.md`](../../../hw_verify/README.md) |
| RTCM | **MSM7** | 同上（同 README は `--setup-base` の手順として案内） |

- **採用（本資料）**: **経路 A（MSM4 / `POS_TYPE=0`）**。
  実装が実際に書き込み・検証するキーは経路 A の側です。
- 補足: [`../../../selftest.py`](../../../selftest.py) の合成 RTCM3 データは
  **MSM7（1077）** を生成します（`SYNTH_MSG_TYPE = 1077`、テスト用フィクスチャ）。
  これは実機の出力形式ではなく、パーサのテスト入力です。
- MSM7（1077 / 1087 / 1097 / 1127）や `POS_TYPE=1` を使う場合は、
  キー定義（`_build_key_table()`）の変更が必要です。
- **要確認**: 経路 B の記述（[`../../../hw_verify/README.md`](../../../hw_verify/README.md)）が
  現行実装と一致していないため、README 側の更新が必要です。

### 6-3. 基地局座標キー：`fixed_lat/lon/alt` か `fixed_pos` か

| 出典 | 記述 |
|---|---|
| [`../../../config/base_station.json`](../../../config/base_station.json) | `fixed_lat` / `fixed_lon` / `fixed_alt` |
| [`../../../config/config.yaml`](../../../config/config.yaml) | `base_station.fixed_lat` / `fixed_lon` / `fixed_alt` |
| [`../../../rtk_tools/rtk_base_station_v2.py`](../../../rtk_tools/rtk_base_station_v2.py) の `Config` | `fixed_lat` / `fixed_lon` / `fixed_alt` |
| [`../../RTK_PROCEDURES_MANUAL.md`](../../RTK_PROCEDURES_MANUAL.md) | `fixed_pos` と記載 |

- **採用（本資料）**: **`fixed_lat` / `fixed_lon` / `fixed_alt`**。
  手順書の `fixed_pos` は実装に対応するキーが存在しないため、
  **手順書側の修正が必要**です。

### 6-4. `GPS_TYPE` か `GPS1_TYPE` か

| 出典 | 記述 |
|---|---|
| [`../../../ekf_failsafe/golden.py`](../../../ekf_failsafe/golden.py) | `"GPS_TYPE": 9`（`# DroneCAN（GPS_TYPE_UAVCAN）※ 1番目 GPS の正準名`） |
| [`../../../ekf_failsafe/README.md`](../../../ekf_failsafe/README.md) §2-1 | `GPS_TYPE`。**`GPS1_TYPE` に自動フォールバック** |

- **採用（本資料）**: `GPS_TYPE` を主とし、`GPS1_TYPE` は
  ArduPilot の改名に伴うフォールバック名として両論併記。
  フォールバック処理は `ArduPilotParamGuard` 側が担います
  （出典: [`../../../ekf_failsafe/README.md`](../../../ekf_failsafe/README.md) §2-1 / §10）。

---

## 7. トラブルシューティング

症状別の切り分けは、手順書の一覧が正典です。

- **RTCM を受信しているのに `3D_FIX` のまま昇格しない**
  → 基地局の固定座標と実位置の乖離を疑う（§1-A4）。
- **Pixhawk に補正が注入されない**
  → MAVLink 2.0 と RTS/CTS を確認（§1-B1, B2）。
- **RTCM 到達はあるのに FIXED にならない**
  → ローバー F9P の golden 退行を確認（§1-D）。

出典: [`../../RTK_PROCEDURES_MANUAL.md`](../../RTK_PROCEDURES_MANUAL.md) §6 の表、
[`../../../hw_verify/README.md`](../../../hw_verify/README.md)。

動的・静的の健全性は 1 コマンドでまとめて確認できます。

```bash
cd ~/rtk-pipeline-local
python3 gcs/preflight/runner.py --host 192.168.1.100 --port 5001
```

---

## 8. 出典（`gcs/` 内のみ）

| ファイル | 参照箇所 |
|---|---|
| `gcs/rtk_tools/f9p_config_all.py` | `_build_key_table()` / `_UART2_ROVER_CFG_KEYS` / `_GNSS_SIGNAL_CFG_KEYS` / `_RTCM_MSG_KEYS_*` |
| `gcs/rtk_tools/rtk_base_station_v2.py` | `Config`（`tcp_port` / `fixed_*`）／`_run_f9p_configuration()` |
| `gcs/rtk_tools/mavlink_bridge.py` | `MAVLINK20` / `rtscts` / `MAX_SIZE=180` / `MAX_FRAGS=4` |
| `gcs/backend/f9p_configurator.py` | `GOLDEN_VALUES` |
| `gcs/backend/README.md` | §2 監視対象（Golden 値） |
| `gcs/ekf_failsafe/golden.py` | `GOLDEN_PARAMS` / `PARAM_GROUPS` / `GNSS_MODE_BITS` |
| `gcs/ekf_failsafe/README.md` | §2-1 / §2-2 / §2-3 / §4 / §8 |
| `gcs/config/config.yaml` | `pass_criteria` / `monitor` |
| `gcs/preflight/README.md` | §6 判定基準 |
| `gcs/flight_test/README.md` | §2 評価モデル / §7 `FlightSpec` |
| `gcs/hw_verify/README.md` | MSM7 の記述（矛盾項目 6-2） |
| `gcs/docs/RTK_PROCEDURES_MANUAL.md` | §2 / §6 |

> 関連: [`../devices/f9p_base/README.md`](../devices/f9p_base/README.md) /
> [`../devices/f9p_rover/README.md`](../devices/f9p_rover/README.md) /
> [`../devices/pixhawk_ardupilot/README.md`](../devices/pixhawk_ardupilot/README.md)
