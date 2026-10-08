# 座学① GNSS 測位の基礎と RTK の原理

本資料は、本システムが採用する **RTK-GNSS** の原理を、一般文献に基づいて解説します。
本リポジトリ固有の実装（`fix_type` の扱い等）には `gcs/` 配下の出典を併記します。

- 索引: [`../README.md`](../README.md)
- 次: [`coordinate_systems.md`](coordinate_systems.md)

---

## 1. GNSS 測位の基礎

### 1.1 測距の原理

GNSS 衛星は自身の位置（軌道情報＝エフェメリス）と時刻を電波で放送します。
受信機は

```
擬似距離 ρ = c × (受信時刻 − 衛星送信時刻)
```

で衛星までの距離を測ります（`c` = 光速）。受信機の時計は衛星時計ほど正確ではないため、
この距離は時計誤差を含む「擬似（pseudo）」距離です。

未知数は **3 次元位置（X, Y, Z）＋ 受信機時計誤差**の 4 つなので、
**最低 4 基の衛星**が必要です（高度を既知とする等の制約があれば 3 基でも可）。

### 1.2 コード測位と搬送波位相測位

| 方式 | 観測量 | 波長の目安 | 精度の目安 |
|---|---|---|---|
| **コード測位**（単独測位） | コード（疑似ランダム信号）の相関による遅延 | GPS L1 C/A のチップ長 ≒ 293 m | 数 m |
| **搬送波位相測位**（RTK 等） | 搬送波の位相 | GPS L1 ≒ 19 cm / L2 ≒ 24 cm / L5 ≒ 25 cm | cm 級 |

搬送波（正弦波）の位相はコードより 2 桁以上細かい分解能を持ちます。
その代わり、位相は **波長ごとに折り返す** ため、観測値には

```
Φ = ρ / λ + N + ε        （N は整数、ε は各種誤差）
```

の **整数アンビギュイティ N** が入ります。N を正しく決められれば高精度、
決められなければ「浮動解（float）」です。この N の決定を **整数アンビギュイティ解決**と呼びます。

> 代表的な周波数: GPS L1 = 1575.42 MHz、L2 = 1227.60 MHz、L5 = 1176.45 MHz、
> GLONASS L1 = 1602 MHz 帯（FDMA）、Galileo E1/E5a、BeiDou B1/B2。
> 周波数の実値は一般文献（u-blox 受信機のデータシート等）を参照。

---

## 2. 測位方式の分類

| 方式 | 仕組み | リアルタイム性 | 精度の目安 | 本システム |
|---|---|---|---|---|
| **単独測位** | 衛星のみで測位 | — | 数 m | `3D_FIX` |
| **SBAS** | 静止衛星の補正情報 | リアルタイム | ≒ 1 m | — |
| **DGPS** | 基準局のコード補正 | リアルタイム | サブ m 〜 m | `DGPS` (4) |
| **RTK** | 基準局との二重差＋搬送波位相 | リアルタイム | cm 級 | `RTK_FLOAT` (5) / `RTK_FIXED` (6) |
| **PPK** | RTK と同じ計算を後処理 | 後処理 | cm 級 | ログ（RAWX/SFRBX）を保存 |

精度段階の一般的な目安（ArduPilot 公式ドキュメント）:

> 「通常の GPS は 3〜5 m の精度。SBAS で約 1 m。RTK を使うと cm 級になる」

出典: [ArduPilot — RTK Correction](https://ardupilot.org/copter/docs/common-rtk-correction.html)

### 2.1 RTK が誤差を消す仕組み

基準局（基地局）と移動局（ローバー）は**同じ衛星を同時に見ています**。
そこで 2 地点の観測から**二重差**を取ると、

- 衛星時計誤差
- 衛星軌道誤差
- 電離層遅延
- 対流圏遅延

のうち **空間的に相関の高い成分が相殺**されます。残るのは主に
**マルチパスや受信機雑音**、そして **基線長に比例して残る残差**です。

### 2.2 PPK との違い

| 項目 | RTK | PPK |
|---|---|---|
| 通信 | 基準局 → ローバーへ**リアルタイム**補正リンクが必要 | 不要（両者のログを後で結合） |
| 用途 | 飛行中の機体制御 | 事後解析・正解値の生成 |
| 本リポジトリ | RTCM を TCP/MAVLink で配送 | `RAWX`/`SFRBX` ログを保存 |

本リポジトリの PPK ログ取得は運用タブの `ppk_logger` から実行します
（出典: [`../../OPERATIONS.md`](../../OPERATIONS.md) の操作カタログ）。

---

## 3. NTRIP と補正データ配送

### 3.1 NTRIP

NTRIP（Networked Transport of RTCM via Internet Protocol）は、
RTCM 補正データを **HTTP ベースのストリーム**として配信/受信するプロトコルです。
認証はベーシック認証で、マウントポイント（配信点）を指定します。

本リポジトリは NTRIP にも対応していますが、**認証情報は設定ファイルに平文で書かず、
環境変数（`${NTRIP_USER}` / `${NTRIP_PASSWORD}`）で渡します**（出典:
[`../../../rtk_tools/README.md`](../../../rtk_tools/README.md) の「認証情報・シークレットの扱い」、
[`../../../config/README.md`](../../../config/README.md)）。

### 3.2 補正データの配送経路（本システム）

本システムは **自前の基地局**（NTRIP ではなくローカル配信）を主経路とします。

```text
基地局 F9P ──RTCM3──► Mac (gcs/rtk_tools/rtk_base_station_v2.py) ──TCP:2101──►
   ──► Raspberry Pi (gcs/rtk_tools/mavlink_bridge.py) ──MAVLink GPS_RTCM_DATA──►

   ──► Pixhawk (ArduPilot) ──RTCM3──► 移動局 F9P ──RTK 解算──► fix_type 昇格
```

ArduPilot 公式では、RTCM 補正の配送手段として次の 3 方式が整理されています。

1. **基地局を GCS に接続**し、GCS が MAVLink 経由で補正を転送する（**本システムの方式**）
2. 機体に RTK 対応のテレメトリ無線を積み、直接 RTCM を送る
3. インターネット越しの NTRIP サービスを使う

出典: [ArduPilot — RTK Correction](https://ardupilot.org/copter/docs/common-rtk-correction.html)

---

## 4. 本リポジトリにおける RTK 状態の表現

RTK-GNSS の「解の状態」は、受信機内部では **搬送波位相解の種別（carrSoln）** として
表現されます。本リポジトリはこれを MAVLink の `GPS_FIX_TYPE`（0〜6）に正規化して扱います。

| 内部表現 | 値 | 意味 |
|---|---|---|
| UBX `flags.carrSoln` | 0 / 1 / 2 | 搬送波位相なし / float / fixed |
| MAVLink `fix_type` | 5 / 6 | `RTK_FLOAT` / `RTK_FIXED` |

- 正規化の実装: [`../../../fix_metrics.py`](../../../fix_metrics.py) の `FIX_NAMES` と `ubx_to_fix_type()`
- RELPOSNED の `carrSoln` 読み取り: [`../../../rtk_tools/f9p_relposned_monitor.py`](../../../rtk_tools/f9p_relposned_monitor.py)

詳細は [`rtk_details.md`](rtk_details.md) を参照してください。

---

## 5. 出典

### 一般文献（座学編）

| 文献 | 内容 |
|---|---|
| [ArduPilot — RTK Correction](https://ardupilot.org/copter/docs/common-rtk-correction.html) | 精度段階（3〜5 m / SBAS ≒1 m / RTK cm 級）、RTCM 配送方式、RTCM 解析オプション |
| [ArduPilot — GPS for Yaw (Moving Baseline)](https://ardupilot.org/copter/docs/common-gps-for-yaw.html) | 移動基線による方位推定（FW 要件・アンテナ間隔・fix type 検証） |
| [u-blox — ZED-F9P 製品ページ](https://www.u-blox.com/en/product/zed-f9p-module) | ZED-F9P Integration Manual（UBX-18010802）/ Interface Description（UBX-18010854）の入手先 |
| RTCM STANDARD 10403.x | RTCM3 のメッセージ体系（MSM 等） |

### 本リポジトリ（実装の根拠）

| ファイル | 参照箇所 |
|---|---|
| `gcs/fix_metrics.py` | `FIX_NAMES`、`ubx_to_fix_type()` |
| `gcs/rtk_tools/f9p_relposned_monitor.py` | `carrSoln` ビット定義 |
| `gcs/rtk_tools/rtk_base_station_v2.py` | 基地局の起動フロー・TCP:2101 |
| `gcs/rtk_tools/mavlink_bridge.py` | RTCM → MAVLink `GPS_RTCM_DATA` 注入 |
| `gcs/docs/RTK_PROCEDURES_MANUAL.md` | 昇格シーケンス（§2 Step 3） |
| `gcs/docs/OPERATIONS.md` | 運用操作カタログ |

> 次に読む: [`coordinate_systems.md`](coordinate_systems.md)（座標系と高さ）
