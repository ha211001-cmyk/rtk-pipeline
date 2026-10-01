# DroneCAN GPS RTK 検証プロジェクト

Holybro DroneCAN H-RTK F9P Helical + Pixhawk6C + ラズパイ を用いた、
DroneCAN GPSの検証・RTK補正データ注入の一連の実装。

## ディレクトリ構成

```
dronecan_gps_rtk/
├── README.md                       # このファイル（プロジェクト全体概要）
├── gps_can_verify/                 # ① DroneCAN GPS 基本検証
│   ├── README.md
│   ├── config.json
│   ├── setup_dronecan_gps.py       # DroneCANパラメータ設定
│   ├── verify_gps_fix2.py          # GPS Fix状態確認
│   └── logs/
├── ichimill_sim/                   # ② ichimill 擬似通信・RTCMログ記録
│   ├── implementation_spec.md
│   ├── config.json
│   ├── main.py                     # 固定座標GGA送信 + RTCM受信
│   └── logs/
├── ntrip_rtk_client/               # ③ NTRIP RTKクライアント（GGA送信のみ）
│   ├── README.md
│   ├── config.json
│   ├── ntrip_rtk_client.py         # MAVLink GPS→GGA変換 + NTRIP送受信
│   ├── analyze_rtcm.py             # RTCM3ログ解析
│   └── logs/
└── rtk_fix_client/                 # ④ RTK Fixクライアント（RTCM注入）⭐ メイン
    ├── README.md
    ├── config.json
    ├── rtk_fix_client.py           # MAVLink受信 + NTRIP + GPS_RTCM_DATA注入
    └── logs/
```

## 各ディレクトリの役割

| # | ディレクトリ | 目的 | 主な成果 |
|---|---|---|---|
| ① | `gps_can_verify/` | DroneCAN GPSの基本動作検証 | DGPS_FIX確認、衛星30個、精度0.62m |
| ② | `ichimill_sim/` | 固定座標でichimillからRTCM取得 | RTCM3ログ記録、MSM7全衛星データ受信 |
| ③ | `ntrip_rtk_client/` | 実GPS位置でichimillからRTCM取得 | MAVLink→NMEA変換、RTCMログ解析 |
| ④ | `rtk_fix_client/` | RTCMをArduPilotに注入しRTK Fix | **GPS_RTCM_DATA送信、RTK_FLOAT確認** |

## システム構成

```
[H-RTK F9P] ←DroneCAN→ [Pixhawk6C] ←MAVLink→ [ラズパイ] ←NTRIP→ [ichimill]
                              │                    │
                         CAN1 1Mbps          /dev/ttyAMA0
                         GPS1_TYPE=9         1Mbps RTS/CTS
```

## 実行手順（RTK Fixまで）

### 1. DroneCAN GPSパラメータ設定

```bash
source ~/Mavlink_venv/bin/activate
cd ~/EVK-F9P/dronecan_gps_rtk/gps_can_verify
python3 setup_dronecan_gps.py
```

### 2. GPS Fix状態確認

```bash
python3 verify_gps_fix2.py
```

3D_FIX以上（fix_type >= 3）を確認する。

### 3. RTK Fixクライアント実行

```bash
cd ~/EVK-F9P/dronecan_gps_rtk/rtk_fix_client
python3 -u rtk_fix_client.py
```

ichimillからRTCM補正データを受信し、MAVLink `GPS_RTCM_DATA` (ID:233) でArduPilotに注入。
ArduPilotがCAN1経由でH-RTK F9Pに自動転送し、RTK Fixを実現する。

## 前提条件

- Pixhawk6C (ArduPilot 4.4.4以上)
- Holybro DroneCAN H-RTK F9P Helical
- ラズパイ (Companion Computer)
- ichimill NTRIPアカウント
- `~/Mavlink_venv` 仮想環境 (pymavlinkインストール済み)

## 検証結果サマリー（2026-08-08）

| 項目 | 結果 |
|---|---|
| DroneCAN GPS認識 | ✅ GPS1_TYPE=9で正常認識 |
| GPS Fix | ✅ DGPS_FIX (fix_type=4)、衛星30個、EPH 0.62m |
| NTRIP接続 | ✅ ichimill RTCM32M7Sに接続成功 |
| RTCM受信 | ✅ MSM7全衛星（GPS/GLONASS/Galileo/QZSS/BeiDou） |
| GPS_RTCM_DATA注入 | ✅ 70フレーム/15秒、分割送信正常、ドロップゼロ |
| RTK状態 | ✅ RTK_FLOAT確認（RTK_FIXEDは継続実行で移行予定） |

## 更新履歴

- 2026-08-08: プロジェクト全体構成の整理、4ディレクトリ統合