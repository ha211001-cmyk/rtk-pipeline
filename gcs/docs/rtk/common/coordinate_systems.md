# 座学② 座標系・高さ・アンテナ基準点

本資料は、RTK-GNSS で扱う **座標系** と **高さの定義**、および **アンテナ基準点**を
一般文献に基づいて解説し、本リポジトリの実装と対応づけます。

- 前: [`rtk_gnss_theory.md`](rtk_gnss_theory.md)
- 索引: [`../README.md`](../README.md)

---

## 1. 測地系と座標系

### 1.1 WGS84（緯度・経度・楕円体高）

GNSS は **WGS84 準拠の楕円体**上の位置を出力します。基本は

- **緯度 φ（latitude）** … 赤道面からの角（北緯/南緯）
- **経度 λ（longitude）** … グリニッジ子午面からの角（東経/西経）
- **楕円体高 h（ellipsoidal height, HAE）** … WGS84 楕円体面からの高さ

### 1.2 ECEF（地球中心直交座標）

計算内部では **ECEF**（Earth-Centered, Earth-Fixed）が使われます。
原点は地球重心、X 軸は本初子午線、Z 軸は自転軸です。

```
X = (N + h) · cosφ · cosλ
Y = (N + h) · cosφ · sinλ
Z = (N (1 − e²) + h) · sinφ        （N: 卯酉線曲率半径、e: 離心率）
```

RTK の二重差や基線ベクトル計算は ECEF（またはローカル接 ENU/NED 座標）で行われます。

### 1.3 本リポジトリでの扱い

| 項目 | 実装 | 備考 |
|---|---|---|
| 基地局座標の格納 | 緯度・経度・楕円体高の 3 値 | [`../../../config/base_station.json`](../../../config/base_station.json)、[`../../../config/config.yaml`](../../../config/config.yaml) |
| 緯度経度のスケーリング | `int(lat × 1e7)` / `int(lon × 1e7)` | [`../../../rtk_tools/f9p_config_all.py`](../../../rtk_tools/f9p_config_all.py) の `_build_key_table()` |
| 高さのスケーリング | `int(alt × 100)`（**cm**） | 同上（`CFG_TMODE_HEIGHT`） |

F9P の `CFG_TMODE_LAT/LON` は **1e-7 度単位**、`CFG_TMODE_HEIGHT` は **cm 単位**で
書き込まれます（実装は上表のとおり）。

---

## 2. 高さの種類（最重要）

「高さ」は文脈によって 3 種類あります。**RTK の設定に使うのは楕円体高（HAE）**です。

```text
    衛星測位が直接求める高さ
    ┌────────────────────────┐
    │  楕円体高 h (HAE)       │  ← WGS84 楕円体面から
    └────────────────────────┘
         ↑ ジオイド高 N（日本では約 +30〜+40 m 程度）
    ┌────────────────────────┐
    │  標高 H (MSL)           │  ← 平均海面（ジオイド面）から
    └────────────────────────┘
```

| 名称 | 記号 | 基準面 | 主な用途 |
|---|---|---|---|
| **楕円体高** | h (HAE) | WGS84 楕円体 | GNSS/RTK の設定値 |
| **ジオイド高** | N | 楕円体からのジオイドのずれ | 換算に使用（国土地理院のジオイドモデル等） |
| **標高** | H (MSL) | 平均海面 | 地図・飛行高度 |

換算式:

```
h = H + N        （楕円体高 = 標高 + ジオイド高）
H = h − N
```

> ⚠️ 基地局設定に**標高（MSL）を書いてしまう**と、その分だけ基準座標がずれます。
> 本リポジトリの設定ファイルは `fixed_alt` を **楕円体高 HAE** として扱います
> （出典: [`../../../config/config.yaml`](../../../config/config.yaml) の
> `fixed_alt: 44.80           # 楕円体高 HAE [m]`、
> [`../../RTK_PROCEDURES_MANUAL.md`](../../RTK_PROCEDURES_MANUAL.md) の基地局座標の注意書き）。

### 2.1 本リポジトリの表示上の注意

- 設定（基地局）: **楕円体高（HAE）** を使用。
- ロギング/集計表示: [`../../../rtk_tools/mavlink_bridge.py`](../../../rtk_tools/mavlink_bridge.py) は
  MAVLink `GPS_RAW_INT.alt` を集計し「平均高度 (MSL)」として表示します。
  MAVLink の `alt` は **MSL**、`alt_ellipsoid` は **楕円体高**という別フィールドです。

したがって、**基地局設定値（HAE）と実験ログの高度（MSL）を直接比較しない**でください。

---

## 3. アンテナ基準点とアンテナ高

| 用語 | 意味 |
|---|---|
| **ARP**（Antenna Reference Point） | アンテナの基準点（通常は取付ベース面） |
| **APC**（Antenna Phase Center） | 実際に電波を受信する位相中心 |
| **アンテナ高** | ARP から APC までの鉛直距離（機種ごとに公表値あり） |

- RTCM の **1005（Station ARP）** / **1006（Station ARP + アンテナ高）** は、
  基準局の ARP 座標とアンテナ情報をローバーへ伝えるメッセージです。
  本システムは **1005 と 1006 の両方**を出力します
  （出典: [`../../../rtk_tools/f9p_config_all.py`](../../../rtk_tools/f9p_config_all.py) の
  `CFG_MSGOUT_RTCM_3X_TYPE1005_*` / `..._1006_*`）。
- 位相中心はアンテナの到来方向（仰角・方位）でわずかに動きます（**位相中心変動**）。
  高精度が要る場合は機種別の変動モデル（PCV）を使います。

### 3.1 固定座標は APC 基準

F9P の TMODE3 に書き込む座標（`CFG_TMODE_LAT/LON/HEIGHT`）は、
**アンテナ位相中心（APC）の位置**として扱われます。そのため基地局座標を実測する際は、
アンテナを実際に設置した状態で測る必要があります。

> 本リポジトリの注意点: アンテナ位置を**数メートル以内**で一致させる必要があります。
> 数十〜数百メートルずれるとローバーが RTK 解算を拒否し、`3D_FIX` のまま昇格しません
> （出典: [`../../RTK_PROCEDURES_MANUAL.md`](../../RTK_PROCEDURES_MANUAL.md) §2 Step 1 の注意、
> および §6 トラブルシューティング表）。

---

## 4. ローカル座標（NED / ENU）と緯度経度の換算

経度 1 度あたりの距離は緯度によって変わります。本リポジトリは簡易換算で
緯度経度の差をメートルへ変換し、水平標準偏差を求めます。

```
1 度（緯度） ≒ 111320 m            … 定数
1 度（経度） ≒ 111320 m × cos(緯度)
```

実装（出典: [`../../../rtk_tools/mavlink_bridge.py`](../../../rtk_tools/mavlink_bridge.py)）:

```python
METERS_PER_DEG_LAT = 111320.0
...
cos_lat = math.cos(math.radians(mean_lat))
std_lat_m  = std(la_ok, mean_lat) * METERS_PER_DEG_LAT          # 緯度方向
std_lon_m  = std(lo_ok, mean_lon) * (METERS_PER_DEG_LAT * cos_lat)  # 経度方向
std_horiz_m = math.sqrt(std_lat_m ** 2 + std_lon_m ** 2)        # 水平（1σ）
```

> ArduPilot の機体内部・MAVLink の NED 表示では、North-East-Down の直交座標が
> 使われます（Web ダッシュボードの「NED」表示）。

---

## 5. 基線ベクトル（RELPOSNED）

2 台の受信機間の相対位置を **基線ベクトル**と呼びます。
本リポジトリは F9P の `UBX-NAV-RELPOSNED` から相対位置（N/E/D 成分）を取得します。

| 成分 | 意味 | 本システムでの主な用途 |
|---|---|---|
| `relPosN/E/D` | 基準局から見た移動局の北/東/下成分 [m] | 基線長、移動基線による方位 |
| `dist` | 3 次元距離（= 基線長） | 移動基線の検証（実測距離との一致） |
| `accN/E/D` | 各成分の精度（1σ） | 精度評価 |
| `refStationId` | 基準局 ID | どの基準局を参照したか |
| `carrSoln` | 搬送波位相解の種別 | RTK 状態判定 |

- 読み取り実装: [`../../../rtk_tools/f9p_relposned_monitor.py`](../../../rtk_tools/f9p_relposned_monitor.py)
  （`relPosN/E/D` から `dist` を計算）
- 基線長を使った機体間相対測位の実測: [`../../../accuracy/README.md`](../../../accuracy/README.md)

### 5.1 移動基線（Moving Baseline）による方位推定

2 つのアンテナを機体上に固定し、その基線ベクトルから**機体の方位（Yaw）**を
算出する方式です。GPS コンパスとも呼ばれます。

ArduPilot 公式が示す要件（一般文献）:

- F9P は **ファームウェア 1.3.2 以上**が必要
- 2 本のアンテナは **30 cm 以上**離すこと
- ArduPilot はローバーが **fix type 6（RTK fixed）**であること、および
  報告された距離が実測距離と **20% 以内**で一致することを検証する

出典: [ArduPilot — GPS for Yaw (Moving Baseline)](https://ardupilot.org/copter/docs/common-gps-for-yaw.html)

> **本システムは単一 F9P 構成のため移動基線を使用しません。**
> 方位はコンパスから取得します（`EK3_SRC1_YAW = 1`）。
> 出典: [`../../../ekf_failsafe/golden.py`](../../../ekf_failsafe/golden.py) の
> `"EK3_SRC1_YAW": 1,  # 方位ソース = コンパス（単一 F9P のため GPS 移動基線は不使用）`

---

## 6. 出典

### 一般文献

| 文献 | 内容 |
|---|---|
| [ArduPilot — GPS for Yaw (Moving Baseline)](https://ardupilot.org/copter/docs/common-gps-for-yaw.html) | 基線ベクトルによる方位、FW/アンテナ間隔/fix type の要件 |
| WGS84（NIMA TR8350.2 等） | 測地系・楕円体パラメータ |
| 国土地理院 ジオイドモデル（GSI ジオイド 2024 等） | ジオイド高 N、標高と楕円体高の換算 |
| u-blox ZED-F9P Interface Description（UBX-18010854） | `UBX-NAV-RELPOSNED`、`CFG-TMODE-*` の定義 |

### 本リポジトリ

| ファイル | 参照箇所 |
|---|---|
| `gcs/config/base_station.json` | `fixed_lat` / `fixed_lon` / `fixed_alt` |
| `gcs/config/config.yaml` | `base_station.fixed_*`（`fixed_alt` は楕円体高 HAE と明記） |
| `gcs/rtk_tools/f9p_config_all.py` | `_build_key_table()`（1e-7 度 / cm スケーリング）、TMODE キー |
| `gcs/rtk_tools/mavlink_bridge.py` | `METERS_PER_DEG_LAT`、水平/垂直標準偏差の算出 |
| `gcs/rtk_tools/f9p_relposned_monitor.py` | `relPosN/E/D` / `dist` / `accN/E/D` |
| `gcs/accuracy/README.md` | 基線長の実測と PPK クロスチェック |
| `gcs/docs/RTK_PROCEDURES_MANUAL.md` | 基地局座標の注意、高度（HAE）の実測手順 |

> 次に読む: [`error_and_accuracy.md`](error_and_accuracy.md)（誤差要因と精度指標）
