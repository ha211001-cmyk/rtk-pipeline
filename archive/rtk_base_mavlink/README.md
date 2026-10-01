# RTK Base Station via MAVLink

ZED-F9Pを基地局モードでMSM7出力し、受信したRTCM3補正データを
MAVLink `GPS_RTCM_DATA` (ID:233) でArduPilotに注入するシステム。

ArduPilotがDroneCAN経由でHolybro DroneCAN H-RTK F9P Helicalに転送し、RTK Fixを実現する。

**ichimill（NTRIPサーバー）は使用しません。**

## システム構成

```
[ZED-F9P (基地局)] --USB--> [ラズパイ] --UART--> [Pixhawk6C] --DroneCAN--> [H-RTK F9P]
     MSM7出力              RTCM受信→注入    GPS_RTCM_DATA              RTK Fix
```

| コンポーネント | 接続 | 役割 |
|--------------|------|------|
| ZED-F9P | USB (`/dev/ttyACM*`) | 基地局モード、MSM7 RTCM3出力 |
| ラズパイ | - | RTCM受信、MAVLink注入 |
| Pixhawk6C | UART (`/dev/ttyAMA0`, 1Mbps) | ArduPilot、RTCM転送 |
| H-RTK F9P | DroneCAN (CAN1) | ロバー側GPS、RTK Fix |

## ディレクトリ構成

```
rtk_base_mavlink/
├── README.md                   # このファイル
├── config.json                 # 設定ファイル
├── main.py                     # メインエントリーポイント
├── f9p_configurator.py         # F9P基地局設定モジュール
├── rtcm_receiver.py            # RTCM受信モジュール
├── mavlink_comm.py             # MAVLink通信モジュール
├── rtcm_injector.py            # RTCM注入モジュール
├── position_observer.py        # 単独測位モジュール
├── stats.py                    # 統計情報管理モジュール
└── logs/                       # ログ出力先
    ├── rtcm_raw_*.rtcm3        # RTCM生データログ
    └── rtk_base_*.log          # 動作ログ
```

## 依存ライブラリ

```bash
# 仮想環境の有効化
source ~/Mavlink_venv/bin/activate

# 必要なライブラリ
pip install pyserial pyubx2 pymavlink
```

## 設定ファイル (`config.json`)

```json
{
    "f9p_base": {
        "serial_port": "/dev/ttyACM2",     # F9Pシリアルポート
        "auto_detect_port": false,          # ポート自動検出 (/dev/ttyACM*)
        "baudrate": 115200,                 # データ通信用ボーレート
        "config_baudrate": 38400,           # 設定用ボーレート
        "mode": "static",                   # "static" または "dynamic"
        "fixed_lat": 36.0751418,            # 静的モード: 緯度
        "fixed_lon": 136.2133477,           # 静的モード: 経度
        "fixed_alt": 44.80,                 # 静的モード: 楕円体高 (m)
        "auto_obs_duration": 60,            # 動的モード: 測位時間 (秒)
        "skip_config": false,               # F9P設定をスキップ
        "save_to_flash": true               # 設定をFlashに保存
    },
    "mavlink": {
        "port": "/dev/ttyAMA0",             # MAVLink接続ポート
        "baud": 1000000,                    # ボーレート
        "rtscts": true                      # RTS/CTSフロー制御
    },
    "rtcm_inject": {
        "max_packet_size": 180,             # 1パケット最大サイズ
        "max_fragments": 4,                 # 最大分割数
        "target_system": 1,                 # ターゲットシステムID
        "target_component": 1               # ターゲットコンポーネントID
    },
    "gga_send_interval": 1.0,              # GGA送信間隔 (秒)
    "log_level": "INFO"                     # ログレベル
}
```

### 基地局座標モード

| モード | 説明 |
|--------|------|
| `"static"` | `fixed_lat`, `fixed_lon`, `fixed_alt` の値を使用 |
| `"dynamic"` | `auto_obs_duration` 秒間単独測位し、平均座標を固定値として使用 |

## 実行方法

### 1. 前提条件

- Pixhawk6C (ArduPilot 4.4.4以上) が起動していること
- Holybro DroneCAN H-RTK F9P Helical がCAN1に接続されていること
- ZED-F9P がUSBでラズパイに接続されていること
- `~/Mavlink_venv` 仮想環境がセットアップ済みであること

### 2. 実行

```bash
# 仮想環境を有効化
source ~/Mavlink_venv/bin/activate

# ディレクトリに移動
cd ~/rtk-pipeline/rtk_base_mavlink

# 実行
python3 main.py
```

### 3. 停止

`Ctrl+C` で停止します。停止時にサマリーが表示されます。

## 動作フロー

1. **設定読み込み** - `config.json` を読み込み
2. **F9Pポート検出** - `/dev/ttyACM*` を自動検出（または設定値を使用）
3. **基地局座標解決** - 静的モードは設定値、動的モードは単独測位で取得
4. **F9P基地局設定** - TMODE3固定座標、MSM7 RTCM3出力有効化
5. **MAVLink接続** - Pixhawk6Cに接続、GPSデータストリーム受信開始
6. **RTCM受信開始** - F9PからRTCM3データを受信、ログ保存
7. **RTCM注入** - 受信したRTCM3フレームをGPS_RTCM_DATAでArduPilotに注入
8. **ステータス表示** - 5秒間隔でシステムステータスを表示

## 出力されるログ

| 出力 | パス | 内容 |
|------|------|------|
| RTCM生データ | `logs/rtcm_raw_YYYYMMDD_HHMMSS.rtcm3` | F9Pから受信したRTCM3バイナリ |
| 動作ログ | `logs/rtk_base_YYYYMMDD_HHMMSS.log` | 起動/停止・各モジュールの状態 |

## F9P設定内容

### 有効化するRTCM3メッセージ (MSM7)

ZED-F9Pは基地局モードで以下の4システムのMSM7を出力します。

| Type | 名称 | ポート |
|------|------|--------|
| 1006 | Station XYZ with antenna height | USB + UART1 |
| 1077 | GPS MSM7 | USB + UART1 |
| 1087 | GLONASS MSM7 | USB + UART1 |
| 1097 | Galileo MSM7 | USB + UART1 |
| 1127 | BeiDou MSM7 | USB + UART1 |
| 1230 | GLONASS Bias | USB + UART1 |

> **⚠️ QZSS MSM7 (Type 1117) について**
>
> ZED-F9Pは基地局モードでQZSS MSM7 (Type 1117) を**出力できません**。
> これはu-blox公式仕様上の制限であり、基地局モードのRTCM3 MSM7出力は
> GPS/GLONASS/Galileo/BeiDou の4システムのみに限定されています。
> `pyubx2` 1.3.6の設定データベースにも `CFG-MSGOUT-RTCM_3X_TYPE1117_*` は
> 未登録です。
>
> ichimill（全国基準局ネットワーク）はQZSSを含む全5システムのMSM7を配信可能ですが、
> 4システム（GPS+GLONASS+Galileo+BeiDou）のMSM7でも日本国内のドローンRTK運用に
> 十分な衛星数が確保され、RTK Fixが可能です。

### 無効化するメッセージ

| Type | 名称 | 理由 |
|------|------|------|
| 1005 | Station ARP | 1006と競合 |
| 1074 | GPS MSM4 | MSM7で十分 |
| 4072 | u-blox Proprietary | 不要 |

## 各モジュールの役割

| モジュール | クラス | 役割 |
|-----------|--------|------|
| `f9p_configurator.py` | `F9pConfigurator` | TMODE3設定、RTCM3メッセージ有効化、設定検証 |
| `rtcm_receiver.py` | `RtcmReceiver` | F9PからシリアルでRTCM3受信、フレーム解析、ログ保存 |
| `mavlink_comm.py` | `MavlinkComm` | MAVLink接続、GPS位置受信、GPS_RTCM_DATA送信 |
| `rtcm_injector.py` | `RtcmInjector` | RTCM3フレームを180バイト分割してMAVLink注入 |
| `position_observer.py` | `PositionObserver` | 単独測位で基地局座標を取得（動的モード用） |
| `stats.py` | `SystemStats` | 統計情報管理、ステータス表示 |

## 参考プログラム

本システムは以下の既存プログラムを参考に実装されています：

| 参考ファイル | 流用内容 |
|-------------|---------|
| `base_station_verify/rtcm_compare/f9p_configurator_v2.py` | F9P基地局設定ロジック |
| `base_station_verify/rtcm_compare/rtk_RTCM_Log2.py` | RTCM受信・フレーム解析ロジック |
| `dronecan_gps_rtk/rtk_fix_client/rtk_fix_client.py` | MAVLink通信・RTCM注入ロジック |

## 動作確認結果 (2026-08-08)

窓際環境でのテスト結果です。

### システム動作統計 (10秒間)

| 項目 | 値 |
|------|-----|
| GPS状態 | DGPS_FIX → **RTK_FLOAT** ✅ |
| 衛星数 | 25 |
| RTCM受信バイト | 42,959 |
| RTCM受信フレーム | 212 |
| RTCM受信エラー | 0 |
| GPS_RTCM_DATA送信 | 212フレーム |
| RTCM注入ドロップ | 0 |
| F9P設定 | 33キー成功, 0失敗 |

### RTCMログ解析結果

| 項目 | 値 |
|------|-----|
| ファイルサイズ | 10,386 bytes |
| 0xD3同期バイト | 172 |
| pyrtcm検出メッセージ | 163 |
| パースエラー | 0 |

| Type | 名称 | フレーム数 |
|------|------|-----------|
| 1006 | Station ARP (with antenna height) | 52 |
| 1077 | GPS MSM7 | 15 |
| 1087 | GLONASS MSM7 | 15 |
| 1097 | Galileo MSM7 | 15 |
| 1127 | BeiDou MSM7 | 15 |
| 1230 | GLONASS Bias | 51 |

### 基地局座標 (Type 1006)

| 項目 | 値 |
|------|-----|
| 局ID | 0 |
| 緯度 | 36.0751418° |
| 経度 | 136.2133477° |
| 高度（楕円体高） | 44.80 m |
| 座標変動 | 0.0000 m（完全安定） ✅ |

## トラブルシューティング

### F9Pが認識されない

```bash
# 接続されているUSBデバイスを確認
ls /dev/ttyACM*
ls /dev/ttyUSB*

# config.json の serial_port を確認
# auto_detect_port: true で自動検出を有効化
```

### MAVLink接続エラー

```bash
# Pixhawkが接続されているか確認
ls /dev/ttyAMA0

# ボーレート設定を確認
# Pixhawk6Cのデフォルトは SERIAL1_BAUD=115 (115200bps)
# または SERIAL1_BAUD=1000 (1Mbps)
```

### RTCMデータが受信できない

```bash
# F9Pが基地局モードに設定されているか確認
# skip_config: false で自動設定を有効化

# ログを確認
cat logs/rtk_base_*.log | grep "RTCM"
```

### F9P設定時に "Undefined configuration database key" エラーが出る

`pyubx2` 1.3.6の設定データベースに存在しないキーを指定した場合に発生します。
ZED-F9Pが基地局モードでサポートしていないRTCM3メッセージタイプ
（例: QZSS MSM7 Type 1117）は設定リストから除外してください。

## 更新履歴

- 2026-08-08: 初版作成。ichimill不使用、ZED-F9P MSM7 → MAVLink GPS_RTCM_DATA注入
- 2026-08-08: 動作確認。RTK_FLOAT達成を確認。QZSS MSM7 (Type 1117) 非対応を明記