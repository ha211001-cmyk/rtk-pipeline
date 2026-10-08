# 座学③ 誤差要因・補正データ・精度指標

本資料は、RTK の精度を決める **誤差要因**、それを伝える **RTCM3 補正データ**、
および結果を定量化する **精度指標**を、一般文献と本リポジトリの実装の両面から解説します。

- 前: [`coordinate_systems.md`](coordinate_systems.md)
- 実値（条件・閾値）: [`fix_conditions.md`](fix_conditions.md)

---

## 1. 誤差要因の分類

| 分類 | 要因 | 単独測位への影響 | RTK 二重差後 |
|---|---|---|---|
| **衛星** | 衛星軌道（エフェメリス）誤差 | 数 m | ほぼ相殺（残差は基線長比例） |
| **衛星** | 衛星時計誤差 | 数 m | ほぼ相殺 |
| **伝搬路** | 電離層遅延 | 数 m（最大 数十 m） | 相殺（ただし周波数・距離依存） |
| **伝搬路** | 対流圏遅延 | 〜2.5 m（天頂） | 相殺（高度差があると残る） |
| **伝搬路** | **マルチパス** | 数 m | **相殺されない**（局所環境） |
| **伝搬路** | **サイクルスリップ** | — | **アンビギュイティが飛ぶ** |
| **受信機** | 受信機雑音 | cm 級 | 残る |
| **受信機** | アンテナ位相中心変動 | cm 級 | 一部残る |
| **幾何** | **DOP**（配置） | 悪いと全誤差が増幅 | 同様 |

### 1.1 RTK で消えない 2 大要因

1. **マルチパス** … 建物・地面・機体自身での反射。反射ごとに遅延量が違うため、
   基準局とローバーで共通になりません。**低仰角衛星をマスクする**、アンテナに
   **グラウンドプレーン**を付ける等が対策です。
2. **サイクルスリップ** … 何らかの原因で位相の連続性（整数カウント）が飛ぶ現象。
   発生するとアンビギュイティを解き直す必要があり、`RTK_FIXED → RTK_FLOAT` の
   脱落として観測されます。

本リポジトリは、この脱落を **FLOAT 遷移回数**として定量化します
（出典: [`../../../fix_metrics.py`](../../../fix_metrics.py) の `compute_metrics()`）。

---

## 2. 補正で消えるもの・残るもの

### 2.1 基線長と精度の関係

二重差で相殺しきれない残差（電離層・対流圏の空間勾配）は **基線長に比例**して増えます。

ArduPilot 公式ドキュメントの記述:

> 「補正源から 10 km 離れるごとに、不正確さの限界はおよそ 1〜1.5 cm 増加する」

出典: [ArduPilot — RTK Correction](https://ardupilot.org/copter/docs/common-rtk-correction.html)

同ページは、基準局を **100 km 以内**に置くことを推奨しています。
本システムは基地局と機体が同一敷地内（ローカルネットワーク）の運用を前提とするため、
**基線長は事実上数百 m 以下**で、この残差は支配的ではありません。

### 2.2 基地局座標の誤差は「そのまま全測位に載る」

基地局の固定座標が誤っていると、ローバーの解は**その分だけ平行移動**します。
これは共通誤差として全サンプルに同方向に現れるため、**標準偏差では検出できません**。

> ⚠️ 本リポジトリの運用注意: 基地局座標は**実際のアンテナ位置と数メートル以内**で
> 一致させること。数十〜数百メートルずれるとローバーが RTK 計算を拒否し、
> `3D_FIX` のまま昇格しません。
> 出典: [`../../RTK_PROCEDURES_MANUAL.md`](../../RTK_PROCEDURES_MANUAL.md) §2 Step 1、§6。

---

## 3. 精度指標

### 3.1 DOP（幾何的な劣化指標）

| 指標 | 意味 |
|---|---|
| HDOP | 水平方向の幾何劣化 |
| VDOP | 垂直方向の幾何劣化 |
| PDOP | 3 次元の幾何劣化 |

衛星が空に偏って配置されると DOP が悪化し、測位誤差が増幅されます。
HDOP は「水平誤差の目安（メートル換算）」としてもよく使われます。

- 本リポジトリの扱い: MAVLink `GPS_RAW_INT.hdop/vdop` は **1/100 単位**で、
  `hdop_m` として **100 で除したメートル値**を記録します
  （出典: [`../../../flight_test/README.md`](../../../flight_test/README.md) の CSV スキーマ）。
- 判定基準: `hdop_max_m = 1.4`（出典: 同上「判定基準」表）。

### 3.2 誤差の定量化（標準偏差 1σ）

本リポジトリは、ある区間の位置サンプルの重心からのばらつきを **1σ（標準偏差）**で
評価します。

```
水平標準偏差 (1σ) = sqrt(σ_lat² + σ_lon²)      [m]
垂直標準偏差 (1σ) = σ_alt                       [m]
```

実測例（出典: [`../../RTK_PROCEDURES_MANUAL.md`](../../RTK_PROCEDURES_MANUAL.md) §2 Step 4）:

```text
  [位置誤差の標準偏差 (RTK_FIXED 区間)]
  🎯 水平標準偏差 (1σ) : 0.8 cm (0.0078 m)
  🎯 垂直標準偏差 (1σ) : 1.3 cm (0.0131 m)
```

> **注意**: 1σ は「ばらつき」であり「真値からの誤差」ではありません。
> 真値からの誤差を評価するには、既知点での比較や PPK 正解値とのクロスチェックが必要です
> （出典: [`../../../accuracy/README.md`](../../../accuracy/README.md)）。

### 3.3 補正リンクの健全性指標

| 指標 | 意味 | 閾値（既定） | 出典 |
|---|---|---|---|
| **RTK age** | 補正データが何秒前のものか | warn 5.0 s / alert 10.0 s | [`../../../config/config.yaml`](../../../config/config.yaml) |
| **CRC エラー率** | RTCM3 フレームの破損率 | alert 5.0 % | 同上 |
| **msgUsed 比率** | 受信した RTCM のうち実際に使用された割合 | 下限 50.0 % | 同上 |
| **基地局到達レート** | ローバーに届いた補正のレート | 下限 1.0 msg/s | [`../../../preflight/README.md`](../../../preflight/README.md) |

これらは `gcs/rtcm_monitor.py` の `CorrectionMonitor` が収集します
（出典: [`../../../preflight/README.md`](../../../preflight/README.md) §7 再利用マップ）。

---

## 4. RTCM3 補正データのメッセージ体系

RTCM3 は、基準局がローバーへ渡す補正情報を**メッセージ番号**で体系化しています。
番号は大まかに次のように整理できます。

| 番号帯 | 種類 | 例 |
|---|---|---|
| 1001〜1012 | 旧世代（GPS/GLONASS のコード・位相） | — |
| **1005 / 1006** | **基準局の位置**（ARP / ARP+アンテナ） | 本システムで使用 |
| 1033 | 受信機・アンテナ記述子 | — |
| **1074〜1124** | **MSM（Multiple Signal Message）** | GPS / GLONASS / Galileo / BeiDou |
| **1230** | GLONASS のコード位相バイアス | 本システムで使用 |
| 1230 / 4090 等 | ベンダー固有・バイアス系 | — |

MSM は「同じタイミングの全衛星・全信号」を 1 メッセージにまとめる形式で、
衛星システムごとに番号が割り当てられます（先頭 3 桁がシステム、末尾が形式）。

| 衛星系 | MSM4 | MSM7 |
|---|---|---|
| GPS | 1074 | 1077 |
| GLONASS | 1084 | 1087 |
| Galileo | 1094 | 1097 |
| BeiDou | 1124 | 1127 |
| QZSS | 1114 | 1117 |

- **MSM4** … コード＋位相＋CNR（信号強度）。バイアスは別メッセージ（例: 1230）。
- **MSM7** … 上記に加え、**高分解能の位相バイアス**を内包する。

本システムは **MSM4 系（1074 / 1084 / 1094 / 1124）＋ 1005 / 1006 ＋ 1230** を出力します
（出典: [`../../../rtk_tools/f9p_config_all.py`](../../../rtk_tools/f9p_config_all.py) の
`_RTCM_MSG_KEYS_UART1` / `_RTCM_MSG_KEYS_USB`）。

> `CFG_MSGOUT_RTCM_3X_TYPE..._UART1` が **UART1 → 機体側**、
> `..._USB` が **USB → Mac 側（TCP 配信）**の出力設定です（出典: 同上）。

### 4.1 ArduPilot 側の RTCM 解析オプション（一般文献）

ArduPilot には RTCM の解析挙動を切り替える `GPS_DRV_OPTIONS` ビットがあります。

| ビット | 内容 |
|---|---|
| bit 6 | 拡張 RTCM パース／ロギングを有効化（RTCM 解析に余分な時間を割ける） |
| bit 7 | 自動フルパースを無効化（RTCM データが大きく、ループ負荷が問題になる場合） |

出典: [ArduPilot — RTK Correction](https://ardupilot.org/copter/docs/common-rtk-correction.html)

> 本リポジトリで `GPS_DRV_OPTIONS` を規定する golden 値はありません
> （出典: [`../../../ekf_failsafe/golden.py`](../../../ekf_failsafe/golden.py) の
> `PARAM_GROUPS` に含まれない）。必要時は ArduPilot 公式に従って個別に設定してください。

---

## 5. 出典

### 一般文献

| 文献 | 内容 |
|---|---|
| [ArduPilot — RTK Correction](https://ardupilot.org/copter/docs/common-rtk-correction.html) | 基線長と精度（10 km 毎に 1〜1.5 cm）、100 km 以内推奨、`GPS_DRV_OPTIONS` |
| RTCM STANDARD 10403.x | MSM を含む RTCM3 メッセージ体系 |
| u-blox ZED-F9P Interface Description（UBX-18010854） | `UBX-RXM-RTCM`（msgUsed / CRC）、`CFG-NAVHPG-*` |
| 電離層・対流圏遅延モデル（Klobuchar / SBAS / 各種マッピング関数） | 遅延の性質 |

### 本リポジトリ

| ファイル | 参照箇所 |
|---|---|
| `gcs/fix_metrics.py` | FLOAT 遷移回数・FIXED 維持率・TTFF |
| `gcs/rtcm_monitor.py` | `CorrectionMonitor`（CRC / age / msgUsed） |
| `gcs/config/config.yaml` | `monitor.*` / `pass_criteria.*` |
| `gcs/preflight/README.md` | 判定基準（基地局レート下限ほか） |
| `gcs/flight_test/README.md` | HDOP の取り扱い、`FlightSpec` |
| `gcs/rtk_tools/f9p_config_all.py` | RTCM メッセージキー一覧 |
| `gcs/ekf_failsafe/golden.py` | golden 対象パラメータ一覧 |
| `gcs/accuracy/README.md` | 既知距離・PPK とのクロスチェック |
| `gcs/docs/RTK_PROCEDURES_MANUAL.md` | 標準偏差の実測例、基地局座標の注意 |

> 次に読む: [`glossary.md`](glossary.md)（用語集）／ [`rtk_details.md`](rtk_details.md)（実装定義）
