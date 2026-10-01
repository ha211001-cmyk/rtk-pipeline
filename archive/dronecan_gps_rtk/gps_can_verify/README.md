# DroneCAN H-RTK F9P Helical + Pixhawk6C GPS検証

## 概要

Holybro DroneCAN H-RTK F9P HelicalモジュールをPixhawk6CのCAN1ポートに接続し、
DroneCANプロトコル経由でGPSデータが正常に受信できるかを検証する。

## 使用機器

| 機器 | 仕様 |
|------|------|
| **GPSモジュール** | Holybro DroneCAN H-RTK F9P Helical |
| **GNSSモジュール** | u-blox ZED-F9P |
| **プロセッサ** | STM32G473 (DroneCANブリッジ) |
| **プロトコル** | DroneCAN 1 Mbit/s |
| **コンパス** | IST8310 / BMM150 |
| **フライトコントローラー** | Pixhawk6C |
| **ファームウェア** | ArduPilot 4.7.0 (dev) |
| **接続** | CAN1ポート (CAN_H/CAN_L/GND/5V) |
| **電源** | CAN経由で給電（~250mA） |

## 検証結果（2026-08-08）

### ✅ 成功

| 項目 | 値 |
|------|-----|
| **Fix状態** | DGPS_FIX (fix_type=4) |
| **衛星数** | 28〜30個 |
| **緯度** | 36.0858005° |
| **経度** | 136.2096994° |
| **高度** | 23.1m |
| **水平精度(EPH)** | 0.62m |
| **垂直精度(EPV)** | 0.79m |
| **GPS_RAW_INT受信** | 50回以上 |
| **GLOBAL_POSITION_INT受信** | 50回以上 |

### 重要な知見

1. **MAVLinkストリームレート設定が必須**
   - `GPS_RAW_INT` (ID=24) と `GLOBAL_POSITION_INT` (ID=33) はデフォルトでは送信されない
   - `MAV_CMD_SET_MESSAGE_INTERVAL` で送信間隔を設定する必要がある
   - `REQUEST_DATA_STREAM` でもストリームを要求できる

2. **接続設定**
   - ポート: `/dev/ttyAMA0` (TELEM1)
   - ボーレート: **1000000 (1Mbps)** - 115200では接続できない
   - ハードウェアフロー制御: **有効 (rtscts=True)**

3. **DroneCAN GPS設定**
   - `CAN_P1_DRIVER = 1` (CAN1ポート有効化)
   - `CAN_D1_PROTOCOL = 1` (DroneCANプロトコル)
   - `GPS1_TYPE = 9` (DroneCAN GPS) ← **重要**
   - `GPS_AUTO_CONFIG = 2` (DroneCAN AutoConfig)
   - `GPS_PRIMARY = 0` (プライマリGPS)

4. **コンパス設定**
   - `COMPASS_USE = 0` (内蔵コンパス無効)
   - `COMPASS_USE2 = 1` (H-RTK外付コンパス有効)

5. **EEPROM保存（MAV_CMD_PREFLIGHT_STORAGE）は不要**
   - ArduPilotは `PARAM_SET` メッセージを受信した時点で、内部パラメータを**自動的に即時Flash/EEPROMへ書き込む**仕様
   - `MAV_CMD_PREFLIGHT_STORAGE` コマンドを送ると、ArduPilotのバージョンやステータスによっては `MAV_RESULT_UNSUPPORTED` や `MAV_RESULT_DENIED` を返したり、ACKを返さずにタイムアウトすることがある
   - これにより「パラメータは正しく書き込まれているのに、スクリプト上はEEPROM保存失敗と判定される」誤判定が発生する
   - **対策**: `PARAM_SET` 後の `PARAM_VALUE` 確認で値が正しければ保存完了とみなす。`MAV_CMD_PREFLIGHT_STORAGE` は使用しない

## ファイル構成

```
gps_can_verify/
├── README.md                    # このファイル（手順書・知見）
├── config.json                  # 接続設定
├── setup_dronecan_gps.py        # DroneCANパラメータ設定（11項目）
├── verify_gps_fix2.py           # GPS Fix状態確認 ⭐ メイン
└── logs/                        # GPSログ保存先
```

## 検証手順

### 1. ArduPilotバージョン確認

```bash
source ~/Mavlink_venv/bin/activate
cd ~/EVK-F9P/dronecan_gps_rtk/gps_can_verify
python3 check_ardupilot_version.py
```

**期待結果:**
- Flight SW Version: 4.7.0 (dev)
- ArduPilot 4.4.4以上 - DroneCAN H-RTK F9P対応

### 2. DroneCAN GPSパラメータ設定

```bash
python3 setup_dronecan_gps.py
```

**設定されるパラメータ:**
- `CAN_P1_DRIVER = 1` (CAN1ポート有効化)
- `CAN_D1_PROTOCOL = 1` (DroneCANプロトコル)
- `GPS1_TYPE = 9` (DroneCAN GPS)
- `GPS_AUTO_CONFIG = 2` (DroneCAN AutoConfig)
- `GPS_PRIMARY = 0` (プライマリGPS)
- `GPS_AUTO_SWITCH = 0` (GPS自動切替無効)
- `COMPASS_ENABLE = 1` (コンパス有効化)
- `COMPASS_USE = 0` (内蔵コンパス無効)
- `COMPASS_USE2 = 1` (H-RTK外付コンパス有効)
- `COMPASS_USE3 = 0` (外付コンパス3無効)
- `COMPASS_AUTODEC = 1` (自動磁気偏角有効)

**注意:** EEPROM保存が拒否された場合は、機体をディスアームして再実行してください。

### 3. GPS Fix状態確認

```bash
python3 verify_gps_fix2.py
```

**このスクリプトはMAVLinkストリームレート設定を含むため、GPSデータが受信できます。**

**確認項目:**
- 3D Fix取得（精度1.5m程度）
- 衛星数
- DroneCAN経由でGPSデータ受信
- コンパスデータ正常

## トラブルシューティング

### GPSデータが受信できない

**原因1: MAVLinkストリームレート設定が不足**
- `GPS_RAW_INT` と `GLOBAL_POSITION_INT` はデフォルトでは送信されない
- `verify_gps_fix2.py` を使用する（ストリームレート設定を含む）

**原因2: ボーレートが間違っている**
- `/dev/ttyAMA0` は **1000000 (1Mbps)** で接続する
- 115200では接続できない

**原因3: DroneCAN設定が未完了**
- `GPS1_TYPE = 9` が設定されているか確認
- `CAN_P1_DRIVER = 1` が設定されているか確認
- 設定変更後はPixhawk6Cのリブートが必要

### GPS Fixが得られない

1. **衛星数を確認**
   - ベランダ環境では衛星数が少ない可能性
   - 最低4衛星必要（3D Fix）
   - 推奨: 8衛星以上

2. **CAN接続を確認**
   - CAN_H / CAN_L の配線が正しいか
   - 終端抵抗の設定

3. **GPSモジュールのLEDを確認**
   - 消灯: No Fix
   - 点滅: 3D Fix / RTK Float
   - 点灯: RTK Fix

### ArduPilotバージョンが古い

- ArduPilot 4.4.4以上が必要
- ファームウェアアップデートを検討

## 参考リンク

- [Holybro DroneCAN H-RTK F9P](https://holybro.com/products/dronecan-h-rtk-f9p-helical)
- [ArduPilot DroneCAN GPS](https://ardupilot.org/copter/docs/common-dronecan-gps.html)
- [u-blox ZED-F9P](https://www.u-blox.com/en/product/zed-f9p-module)

## 更新履歴

- 2026-08-08: 初版作成
- 2026-08-08: GPS検証成功（DGPS_FIX、衛星数30個、精度0.62m）
- 2026-08-08: 不要なスクリプト削除、知見をREADMEに統合