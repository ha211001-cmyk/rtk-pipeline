# 座学④ 用語集

本資料は、RTK-GNSS 関連の用語を **衛星系 / 測位 / 補正データ / 受信機・UART / 機体側 /
本リポジトリ固有** に分類してまとめたものです。
本リポジトリでの実装があるものは「実装」列に `file` を併記します。

- 索引: [`../README.md`](../README.md)
- 実装の全体像: [`rtk_details.md`](rtk_details.md)

---

## 1. 衛星系（コンステレーション）

| 用語 | 説明 |
|---|---|
| **GNSS** | Global Navigation Satellite System。全世界測位衛星システムの総称 |
| **GPS** | 米国。L1/L2/L5 |
| **GLONASS** | ロシア。L1/L2（FDMA が特徴） |
| **Galileo** | EU。E1/E5a/E5b |
| **BeiDou（BDS）** | 中国。B1/B2 |
| **QZSS** | 日本。準天頂衛星（GPS 互換信号＋補強） |
| **SBAS** | 静止衛星による補強システム（WAAS / EGNOS / MSAS 等） |
| **MSM** | Multiple Signal Message。RTCM3 の複数信号一括メッセージ形式 |
| **PRN** | 衛星の識別番号 |
| **エフェメリス** | 各衛星の精密な軌道・時刻情報（測位に直接使用） |
| **アルマナック** | 全衛星の概略軌道（捕捉の高速化に使用） |

---

## 2. 測位の原理

| 用語 | 説明 | 実装 |
|---|---|---|
| **擬似距離** | `c × (受信時刻 − 送信時刻)`。時計誤差を含む距離 | — |
| **コード測位** | コード相関による測距。単独測位で使用 | — |
| **搬送波位相** | 搬送波の位相観測。cm 級精度の源 | — |
| **整数アンビギュイティ** | 搬送波位相に含まれる未知の整数 `N` | — |
| **FLOAT（浮動解）** | `N` が未確定（実数推定） | `fix_type = 5` |
| **FIXED（固定解）** | `N` が整数に確定 | `fix_type = 6` |
| **carrSoln** | UBX の搬送波位相解種別（0=none / 1=float / 2=fixed） | [`../../../rtk_tools/f9p_relposned_monitor.py`](../../../rtk_tools/f9p_relposned_monitor.py) |
| **diffSoln** | 差動補正が適用されたか（UBX フラグ） | [`../../../fix_metrics.py`](../../../fix_metrics.py) |
| **gnssFixOk** | GNSS の測位が有効か（UBX フラグ） | 同上 |
| **サイクルスリップ** | 位相の連続性が飛ぶ現象。`FIXED→FLOAT` 脱落の主因 | `float_transition_count` で計測 |
| **TTFF** | Time To First Fix。記録開始から最初の `RTK_FIXED` までの秒数 | [`../../../fix_metrics.py`](../../../fix_metrics.py) |

---

## 3. 補正方式・補正データ

| 用語 | 説明 | 実装 |
|---|---|---|
| **DGPS** | コード補正による測位（メートル級） | `fix_type = 4` |
| **RTK** | 搬送波位相＋二重差によるリアルタイム測位（cm 級） | `fix_type = 5/6` |
| **PPK** | RTK と同じ計算を後処理で実施 | RAWX/SFRBX ログ |
| **NTRIP** | RTCM を HTTP 系ストリームで配信/受信するプロトコル | `rtk_forwarder_service.py` |
| **RTCM3** | 基準局補正データの標準フォーマット | [`../../../rtk_tools/f9p_config_all.py`](../../../rtk_tools/f9p_config_all.py) |
| **MSM4 / MSM7** | MSM の形式。本システムは **MSM4** | 同上 |
| **1005 / 1006** | 基準局 ARP / ARP+アンテナ高 のメッセージ | 同上 |
| **1230** | GLONASS コード位相バイアス | 同上 |
| **マウントポイント** | NTRIP の配信点識別子 | [`../../../config/README.md`](../../../config/README.md) |
| **RTK age** | 補正データの鮮度（古いほど精度・信頼性が低下） | `gcs/rtcm_monitor.py` |
| **msgUsed** | 受信した RTCM のうち使用された割合 | 同上 |

---

## 4. 座標・高さ・幾何

| 用語 | 説明 |
|---|---|
| **WGS84** | GNSS の測地基準（楕円体） |
| **ECEF** | 地球中心・地球固定の直交座標 |
| **楕円体高 (HAE)** | WGS84 楕円体面からの高さ。**RTK 設定に使う** |
| **ジオイド高 (N)** | 楕円体面とジオイド面の差 |
| **標高 (MSL / H)** | 平均海面からの高さ。`h = H + N` |
| **ARP** | Antenna Reference Point（アンテナ基準点） |
| **APC** | Antenna Phase Center（アンテナ位相中心） |
| **基線長** | 基準局と移動局の距離 |
| **移動基線** | 2 アンテナの基線ベクトルから方位を求める方式 |
| **DOP** | 衛星配置による劣化指標（HDOP / VDOP / PDOP） |
| **1σ** | 標準偏差。本リポジトリの位置精度指標 |
| **CEP** | Circular Error Probable（50% 確率円） |

詳細: [`coordinate_systems.md`](coordinate_systems.md)

---

## 5. 誤差要因

| 用語 | 説明 |
|---|---|
| **電離層遅延** | 電離層の自由電子による遅延。周波数依存（分散性） |
| **対流圏遅延** | 大気（乾燥成分＋水蒸気）による遅延 |
| **マルチパス** | 反射波の干渉。RTK で相殺されない主要誤差 |
| **受信機雑音** | 受信機内部の観測雑音 |
| **位相中心変動** | アンテナの位相中心が到来方向で変動する現象 |

詳細: [`error_and_accuracy.md`](error_and_accuracy.md)

---

## 6. 受信機・UART プロトコル

| 用語 | 説明 | 実装 |
|---|---|---|
| **UBX** | u-blox のバイナリプロトコル | `pyubx2` |
| **CFG-VALSET / CFG-VALGET** | 設定キーの書込 / 読取 | [`../../../rtk_tools/f9p_config_all.py`](../../../rtk_tools/f9p_config_all.py) |
| **layer（RAM / BBR / Flash）** | 設定の保存先。`1`=RAM、`2`=BBR、`4`=Flash、`7`=全て | [`../../../rtk_tools/README.md`](../../../rtk_tools/README.md) |
| **TMODE3** | 基準局の動作モード（Fixed Mode 等） | `CFG_TMODE_*` |
| **Survey-In** | 自己測量で基準局座標を決める機能 | `mode="auto"`（未実装） |
| **NAV-PVT** | 位置・速度・時刻・fix 情報の主要メッセージ | `gcs/integration/sources.py` |
| **NAV-RELPOSNED** | 基準局からの相対位置 | [`../../../rtk_tools/f9p_relposned_monitor.py`](../../../rtk_tools/f9p_relposned_monitor.py) |
| **RXM-RTCM** | 受信した RTCM の CRC / msgUsed | `gcs/rtcm_monitor.py` |
| **RAWX / SFRBX** | 観測データ / 航法メッセージ（PPK 用） | `ppk_logger` |
| **MON-VER** | 受信機の生存確認・バージョン情報 | [`../../../rtk_tools/f9p_config_all.py`](../../../rtk_tools/f9p_config_all.py) |
| **write-verify** | 書込後に読み戻して一致を確認する運用原則 | 同上 |

---

## 7. 機体側（MAVLink / ArduPilot）

| 用語 | 説明 | 実装 |
|---|---|---|
| **MAVLink** | 機体と GCS の通信プロトコル。RTCM 注入と RTK 状態監視に使用 | [`../../../rtk_tools/mavlink_bridge.py`](../../../rtk_tools/mavlink_bridge.py) |
| **MAVLink 2.0** | RTCM 注入に必須（`MAVLINK20=1`） | 同上 |
| **GPS_RAW_INT** | `fix_type` / HDOP / 衛星数などの測位情報 | [`../../../fix_metrics.py`](../../../fix_metrics.py) |
| **GPS_RTCM_DATA** | RTCM3 フレームを Pixhawk へ渡すメッセージ | [`../../../rtk_tools/mavlink_bridge.py`](../../../rtk_tools/mavlink_bridge.py) |
| **GPS_FIX_TYPE** | `fix_type` の 0〜6 定義 | [`../../../fix_metrics.py`](../../../fix_metrics.py) |
| **EKF / EKF3** | ArduPilot の状態推定器。RTK 測位を融合 | [`../../../ekf_failsafe/golden.py`](../../../ekf_failsafe/golden.py) |
| **EKF_STATUS_REPORT** | EKF の健全性・位置分散 | [`../../../flight_test/README.md`](../../../flight_test/README.md) |
| **フェイルセーフ (FS)** | 測位劣化・通信断時の自動動作 | `FS_*` パラメータ |
| **DroneCAN** | CAN 上の uAvionix 系プロトコル。H-RTK F9P の接続方式 | `GPS_TYPE = 9` |
| **Serial Forwarding** | 機体側シリアルを TCP へ橋渡しする仕組み | port `5001` |

---

## 8. 本リポジトリ固有の用語

| 用語 | 説明 | 実装 |
|---|---|---|
| **基地局 / 基準局（base）** | 固定座標に置く受信機。RTCM3 を生成 | [`../../../rtk_tools/rtk_base_station_v2.py`](../../../rtk_tools/rtk_base_station_v2.py) |
| **移動局（rover）** | 機体側の受信機。RTCM3 を適用し RTK 解を出す | `--role rover` |
| **`fixed_lat` / `fixed_lon` / `fixed_alt`** | 基地局の固定座標（`fixed_alt` は楕円体高 HAE） | [`../../../config/base_station.json`](../../../config/base_station.json) |
| **FIXED 維持率** | 全期間（または初回 FIXED 以降）の `RTK_FIXED` 割合 [%] | [`../../../fix_metrics.py`](../../../fix_metrics.py) |
| **FLOAT 遷移回数** | `fix_type` が FLOAT へ遷移した回数 | 同上 |
| **FIXED→FLOAT 脱落** | `RTK_FIXED` から `RTK_FLOAT` へ落ちた回数 | 同上 |
| **golden 値** | 設定が退行していないかを照合する基準値 | F9P: [`../../../backend/f9p_configurator.py`](../../../backend/f9p_configurator.py)<br>ArduPilot: [`../../../ekf_failsafe/golden.py`](../../../ekf_failsafe/golden.py) |
| **二層 golden 照合** | F9P レジスタ golden と ArduPilot パラメータ golden の同時照合 | [`../../../ekf_failsafe/README.md`](../../../ekf_failsafe/README.md) |
| **Item 1 / 2 / 3** | 飛行前チェックの項目（FIXED 率 / コンフィグ照合 / RTCM 健全性） | [`../../../preflight/README.md`](../../../preflight/README.md) |
| **PASS / FIXED / FAIL** | golden 照合の結果ステータス | [`../../../backend/README.md`](../../../backend/README.md) |
| **`--no-flash`** | RAM のみに書き込む（電源再投入で元に戻る） | [`../../../rtk_tools/README.md`](../../../rtk_tools/README.md) |

---

## 9. 略語クイックリファレンス

| 略語 | 展開 |
|---|---|
| HAE | Height Above Ellipsoid（楕円体高） |
| MSL | Mean Sea Level（平均海面＝標高） |
| ARP / APC | Antenna Reference Point / Antenna Phase Center |
| DOP / HDOP / VDOP | Dilution Of Precision（水平 / 垂直） |
| TTFF | Time To First Fix |
| RTCM | Radio Technical Commission for Maritime Services |
| NTRIP | Networked Transport of RTCM via Internet Protocol |
| MSM | Multiple Signal Message |
| EKF | Extended Kalman Filter |
| FS | Failsafe |
| PVT | Position, Velocity, Time |
| RELPOSNED | Relative Position in NED |
| CNR / C/N0 | Carrier-to-Noise ratio（信号強度） |

> 次に読む: [`rtk_details.md`](rtk_details.md)（本システムの実装定義）
