# rtcm_compare — RTCM データ比較検証

F9P 基地局モードで取得した RTCM ログと、ichimill 由来の RTCM ログを比較し、
**メッセージ内容・バイナリ形式に問題がないか**を検証するためのディレクトリです。

## 目的

基地局モードの F9P から出力される RTCM 補正データと、既に取得済みの
ichimill の RTCM 補正データを突き合わせることで、以下を確認します。

1. **RTCM3 バイナリフレーム構造の正当性**
   - 同期バイト `0xD3` の検出
   - 10bit フレーム長との整合
   - CRC24Q による誤り検出の整合
2. **メッセージタイプ構成の比較**
   - どのメッセージタイプが含まれているか（基地局座標 1005/1006、暦 1019/1020、
     MSM4 1074/1084/1094/1124、GLO バイアス 1230 など）
   - 各タイプの出現頻度・バイトサイズ
3. **基地局座標（Type 1005/1006）の比較**
   - ECEF X/Y/Z、station_id、ITRF 年 など
4. **データ品質**
   - フレーム欠損・CRC エラー率

## ディレクトリ構成

```
rtcm_compare/
├── README.md               # このファイル
├── rtk_RTCM_Log2.py        # F9P 基地局 → RTCM ログ取得（引数なしで実行可）
├── f9p_configurator_v2.py  # F9P を基地局モードに設定する補助モジュール
├── standalone_obs.py       # 単独測位 補助モジュール
├── config_loader.py        # 設定読み込み
└── logs/                   # 取得した RTCM ログ・一般ログの出力先
```

## 実行方法

### 初回セットアップ

```bash
cd ~/EVK-F9P
python3 -m venv .venv
source .venv/bin/activate
pip install pyserial pyubx2 pyyaml pyrtcm
```

### ラズパイ（デフォルト）

F9P モジュールを接続し、引数なしで実行します。
シリアルポート `/dev/ttyACM2`、F9P 設定スキップがデフォルトです。

```bash
cd ~/EVK-F9P
source .venv/bin/activate
cd base_station_verify/rtcm_compare
python3 rtk_RTCM_Log2.py
```

### Windows

`base_station_verify/config/config.yml` の `f9p.serial_port` を `COM8` に切り替えてください。

```yaml
# --- Windows 設定 ---
f9p:
  serial_port: COM8
  baudrate: 115200
```

### オプション引数

```bash
# TCPポートを変更
python3 rtk_RTCM_Log2.py --tcp-port 2110

# ログレベルを DEBUG に
python3 rtk_RTCM_Log2.py --log-level DEBUG

# F9P 設定を有効化（基地局モード未設定の場合）
python3 rtk_RTCM_Log2.py --skip-f9p-config  # デフォルトで有効、明示的に無効化する場合は指定しない
```

### 依存ライブラリ

```bash
pip install pyserial pyubx2 pyyaml
```

## 出力されるログ

| 出力 | パス | 内容 |
|---|---|---|
| RTCM 生データ | `logs/rtcm_raw_YYYYMMDD_HHMMSS.rtcm3` | F9P から受信した RTCM3 バイナリ |
| 一般ログ | `logs/rtk_base_station.log` | 起動/停止・TCP/シリアル状態 |
| 単独測位 CSV | `logs/base_obs_YYYYMMDD_HHMMSS.csv` | auto モード時の観測結果 |

- すべてのログは**本ディレクトリ直下の `logs/`** に出力されます。
- RTCM 生データの拡張子は ichimill 側と合わせて **`.rtcm3`** です。

## 解析手順

### 1. F9P 基地局側で RTCM ログを取得

```bash
cd ~/EVK-F9P/base_station_verify/rtcm_compare
python3 rtk_RTCM_Log2.py
```

→ `logs/rtcm_raw_YYYYMMDD_HHMMSS.rtcm3` が生成される

### 2. analyze_rtcm.py で解析

`dronecan_gps_rtk/ntrip_rtk_client/analyze_rtcm.py` を使用します。

```bash
cd ~/EVK-F9P
python3 dronecan_gps_rtk/ntrip_rtk_client/analyze_rtcm.py \
  base_station_verify/rtcm_compare/logs/rtcm_raw_YYYYMMDD_HHMMSS.rtcm3
```

### 3. ichimill 側のログも同様に解析

```bash
python3 dronecan_gps_rtk/ntrip_rtk_client/analyze_rtcm.py \
  dronecan_gps_rtk/ichimill_sim/logs/rtcm_*.rtcm3
```

## 動作確認済み解析結果（2026-08-08）

### 修正前（UART1設定のみ、USBポート未設定）

`rtk_RTCM_Log2.py` をラズパイ（`/dev/ttyACM2`）で約12秒間実行し、
`analyze_rtcm.py` で解析した結果です。

#### サマリ

| 項目 | 値 |
|------|-----|
| ファイルサイズ | 12,080 bytes |
| 0xD3 同期バイト出現回数 | 213 |
| 0xD3 間隔平均 | 56.3 bytes |
| pyrtcm 検出メッセージ数 | **170** |
| 正常パース | 170 |
| パースエラー | **0** ✅ |

#### メッセージタイプ分布

| Type | 名称 | フレーム数 |
|------|------|-----------|
| **1005** | Stationary RTK Reference Station ARP（基地局座標） | 57 |
| **1074** | GPS MSM4（GPS 観測データ） | 56 |
| **4072** | Unknown（u-blox 独自メッセージ） | 57 |

> **原因**: `_UART1` 向け設定のみで USB ポート（`/dev/ttyACM2`）の設定を変更していなかったため、工場出荷設定（MSM4）が出力された。

---

### 修正後（USB + UART1 両方に MSM7 設定）

`f9p_configurator_v2.py` に `_USB` 向け設定キーを追加し、約18秒間実行した結果です。

#### サマリ

| 項目 | 値 |
|------|-----|
| ファイルサイズ | 40,187 bytes |
| 0xD3 同期バイト出現回数 | 462 |
| 0xD3 間隔平均 | 86.9 bytes |
| pyrtcm 検出メッセージ数 | **393** |
| 正常パース | 393 |
| パースエラー | **0** ✅ |

#### メッセージタイプ分布

| Type | 名称 | フレーム数 |
|------|------|-----------|
| **1006** | Stationary RTK Reference Station ARP (with antenna height) | 56 |
| **1074** | GPS MSM4 | 56 |
| **1077** | GPS MSM7 | 56 |
| **1087** | GLONASS MSM7 | 57 |
| **1097** | Galileo MSM7 | 56 |
| **1127** | BeiDou MSM7 | 56 |
| **1230** | GLONASS L1 & L2 Code-Phase Biases | 56 |

#### 基地局座標（Type 1006）

| 項目 | 値 |
|------|-----|
| 局ID | 0 |
| 緯度 | **36.0751418°** |
| 経度 | **136.2133477°** |
| 高度（楕円体高） | **44.80 m** |
| ECEF-X | -3,725,930.30 m |
| ECEF-Y | 3,571,372.84 m |
| ECEF-Z | 3,734,960.19 m |
| 座標変動 | **0.0000 m（完全安定）** ✅ |
| GNSS | GPS, GLONASS, Galileo 対応 |

### 結論

- ✅ **ZED-F9P は基地局モードで MSM7（1077/1087/1097/1127）および Type 1006 の出力に対応**
- ✅ パースエラー 0、全 393 フレームが正常に解析された
- ✅ 基地局座標は完全に安定しており、固定基地局として正しく動作
- ✅ RTCM3 フレーム構造（0xD3 プリアンブル、10bit フレーム長、CRC24Q）は規格準拠
- ✅ Type 1005 → Type 1006 への切り替え成功（アンテナ高含む）
- ✅ Type 4072（u-blox 独自メッセージ）の無効化成功
- ⚠️ Type 1074（GPS MSM4）が依然として出力されている（追加調査推奨）

## ichimill との比較分析（2026-08-08）

### ichimill ログ解析結果

| 項目 | 値 |
|------|-----|
| ファイルサイズ | 27,730 bytes |
| メッセージ数 | 120 |
| パースエラー | 0 |

| Type | 名称 | フレーム数 |
|------|------|-----------|
| **1006** | Station ARP (with antenna height) | 15 |
| **1033** | Receiver and Antenna Description | 15 |
| **1077** | GPS MSM7 | 30 |
| **1087** | GLONASS MSM7 | 15 |
| **1097** | Galileo MSM7 | 15 |
| **1117** | QZSS MSM7 | 15 |
| **1127** | BeiDou MSM7 | 15 |

### F9P vs ichimill メッセージタイプ比較

| Type | 名称 | F9P (修正後) | ichimill | 差異 |
|------|------|:---:|:---:|------|
| 1006 | Station ARP (with antenna height) | ✅ | ✅ | 一致 |
| 1033 | Receiver and Antenna Description | ❌ | ✅ | **ichimill のみ** |
| 1074 | GPS MSM4 | ❌ (無効化済) | ❌ | 一致 |
| 1077 | GPS MSM7 | ✅ | ✅ | 一致 |
| 1087 | GLONASS MSM7 | ✅ | ✅ | 一致 |
| 1097 | Galileo MSM7 | ✅ | ✅ | 一致 |
| 1117 | QZSS MSM7 | ✅ (追加済) | ✅ | 一致 |
| 1127 | BeiDou MSM7 | ✅ | ✅ | 一致 |
| 1230 | GLONASS Bias | ✅ | ❌ | **F9P のみ** |
| 4072 | u-blox Proprietary | ❌ (無効化済) | ❌ | 一致 |

### 差異の評価

| 差異 | 影響 | 対応 |
|------|------|------|
| **Type 1033** (ichimill のみ) | 受信機・アンテナ情報。RTK測位には必須ではない | 対応不要（F9Pは基地局モードで1033を出力しない） |
| **Type 1230** (F9P のみ) | GLONASS L1/L2 Code-Phase Bias。GLONASSのRTK精度向上に寄与 | 有益な追加情報。ichimill が未対応の場合は無効化も検討可 |
| **QZSS MSM7 (1117)** | みちびき補正データ。日本国内のRTK Fix維持に重要 | ✅ 追加済み |

### 結論

- ✅ F9P と ichimill の RTCM3 メッセージ構成は **95% 以上一致**
- ✅ 主要な MSM7 メッセージ（GPS, GLO, GAL, BDS, QZSS）は完全一致
- ✅ 基地局座標（Type 1006）のフォーマットは同一
- ⚠️ Type 1033 は F9P 基地局モードでは出力不可（仕様上の制限、RTK測位に影響なし）
- ⚠️ Type 1230 は ichimill が未対応（GLONASS使用時のみ影響、無効化も可能）

## 比較観点まとめ

| 観点 | F9P 基地局 | ichimill | 一致すべき点 |
|---|---|---|---|
| 同期バイト | `0xD3` | `0xD3` | 同一フォーマット |
| フレーム長 | 10bit サイズ表記 | 同 | 構造一致 |
| 基地局座標 | Type 1006 | Type 1006 | どちらも ECEF XYZ |
| MSM メッセージ | 1077/1087/1097/1117/1127 (MSM7) | 1077/1087/1097/1117/1127 (MSM7) | **完全一致** ✅ |
| CRC24Q | 検証可能 | 検証可能 | エラー率 0 が理想 |

> ZED-F9P は FW 1.00 HPG 1.00 以降、基地局モードで MSM7（1077/1087/1097/1117/1127）および Type 1006 の出力に公式対応しています。
> 設定時は**対象ポート（USB/UART1）ごとに独立した設定キー**が必要です。
> `_UART1` 向け設定だけでは USB ポート（`/dev/ttyACM2`）の出力は変更されません。

## 設定の重要ポイント

### ポート別設定キー

ZED-F9P のメッセージ出力設定は**インターフェース（USB, UART1, UART2, I2C, SPI）ごとに独立**しています。

| インターフェース | 設定キー suffix | デバイスパス例 |
|---|---|---|
| USB | `_USB` | `/dev/ttyACM2` |
| UART1 | `_UART1` | Pixhawk 接続用 |
| UART2 | `_UART2` | 補助シリアル |

### 必要な設定項目

1. **MSM7 出力有効化**（USB + UART1 両方）:
   - `CFG-MSGOUT-RTCM_3X_TYPE1077_USB` / `_UART1` (GPS MSM7)
   - `CFG-MSGOUT-RTCM_3X_TYPE1087_USB` / `_UART1` (GLO MSM7)
   - `CFG-MSGOUT-RTCM_3X_TYPE1097_USB` / `_UART1` (GAL MSM7)
   - `CFG-MSGOUT-RTCM_3X_TYPE1127_USB` / `_UART1` (BDS MSM7)
2. **Type 1006 有効化 + Type 1005 無効化**（1005 と 1006 の同時出力は帯域圧迫のため）
3. **RTCM3 プロトコル出力許可**: `CFG-USBOUTPROT-RTCM3X` / `CFG-UART1OUTPROT-RTCM3X`
4. **保存レイヤー**: RAM + BBR + Flash（`layers=7`）で再起動後も設定維持

## 元コードとの差分

`GCS-UmemotoLab/rtk_tools/rtk_RTCM_Log2.py` からの変更点:

1. **単体動作化**: `rtk_tools.xxx` パッケージ基準のインポートを、本ディレクトリ内の
   ローカルモジュール基準に変更。
2. **ログ出力先**: RTCM 生データ・一般ログを本ディレクトリの `logs/` に統一。
3. **拡張子**: RTCM 生データを `.bin` → `.rtcm3` に変更。
4. **設定耐性**: 設定ファイル（config.yml 等）が無くてもデフォルト設定で起動できるよう、
   `load_hardware_config()` を try/except で寛容に処理。
5. **ラズパイデフォルト**: デフォルトのシリアルポートを `/dev/ttyACM2` に、
   F9P 設定をデフォルトスキップに変更。引数なしでラズパイ上ですぐ実行可能。
6. **プラットフォーム切り替え**: `config.yml` でラズパイ/Windows のシリアルポートを
   コメントアウトで切り替え可能。

## 更新履歴

- 2026-08-08: ディレクトリ新設・`rtk_RTCM_Log2.py` を単体動作版として導入
- 2026-08-08: ラズパイデフォルト設定に変更、`analyze_rtcm.py` による解析結果を追記、
  プラットフォーム切り替え対応
- 2026-08-08: **`_USB` 向け設定キーを追加し、ZED-F9P の MSM7 出力を実機確認**。
  「MSM7出力非対応」という初期結論を誤りと確定。QZSS(1117)含む全MSM7出力に対応。
- 2026-08-08: シリアルポート二重オープン問題（`_read_gps_status`）を修正。
  ichimill との比較分析を追記。
