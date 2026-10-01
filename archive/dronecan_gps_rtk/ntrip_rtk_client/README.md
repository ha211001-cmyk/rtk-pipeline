# NTRIP RTKクライアント

ArduPilot (Pixhawk) からMAVLinkでGPS位置情報を受信し、NMEA-0183 `$GNGGA`形式に変換してichimill NTRIPサーバーに送信することで、実際のGPS位置に応じたRTCM補正データを取得するクライアント。

## 概要

```
┌─────────────────────┐         ┌──────────────────────────┐
│  Pixhawk6C          │         │  ichimill NTRIPサーバー   │
│  (DroneCAN H-RTK)   │         │  ntrip.ales-corp.co.jp:2101│
└─────────┬───────────┘         └───────────┬──────────────┘
          │ MAVLink (GPS_RAW_INT)           │ NTRIP (RTCM3)
          │ /dev/ttyAMA0 @ 1Mbps            │ TCP/IP
          ▼                                 ▼
┌───────────────────────────────────────────────────────────┐
│                    ntrip_rtk_client.py                    │
│                                                           │
│  [MAVLink受信スレッド]        [NTRIP送信スレッド]          │
│  GPS_RAW_INT受信 ──→ 共有状態 ──→ $GNGGA変換 ──→ 送信     │
│                                                           │
│  [NTRIP受信スレッド]                                       │
│  RTCM3データ ──→ logs/rtcm_*.rtcm3 にバイナリ保存          │
└───────────────────────────────────────────────────────────┘
```

## 変換の仕組み

MAVLink `GPS_RAW_INT` (バイナリ) → NMEA `$GNGGA` (ASCIIテキスト):

| MAVLinkフィールド | 変換 | NMEAフィールド |
|---|---|---|
| `lat` (`int32_t`, 1e7倍) | `lat / 1e7` → 度分変換 (`DDMM.MMMM`) | 緯度 |
| `lon` (`int32_t`, 1e7倍) | `lon / 1e7` → 度分変換 (`DDDMM.MMMM`) | 経度 |
| `alt` (`int32_t`, mm単位) | `alt / 1000` (m) | 楕円体高 (M) |
| `fix_type` | 品質マッピング | 品質インジケータ |
| `satellites_visible` | そのまま | 使用衛星数 |
| `eph` (`uint16_t`, cm単位) | `eph / 100 * 1.5` | HDOP |

### fix_type → GGA品質マッピング

| MAVLink fix_type | 意味 | NMEA品質 |
|---|---|---|
| 0 / 1 | NO_FIX | 0 (無効) |
| 2 | 2D_FIX | 1 (GPS fix) |
| 3 | 3D_FIX | 1 (GPS fix) |
| 4 | DGPS_FIX | 2 (DGPS) |
| 5 | RTK_FLOAT | 5 (float RTK) |
| 6 | RTK_FIXED | 4 (RTK fixed) |

## セットアップ

### 必要なパッケージ

```bash
# pymavlinkがインストールされた仮想環境を使用
source ~/Mavlink_venv/bin/activate
```

### 設定ファイル (`config.json`)

```json
{
  "mavlink": {
    "port": "/dev/ttyAMA0",
    "baud": 1000000,
    "rtscts": true
  },
  "ntrip": {
    "server": "ntrip.ales-corp.co.jp",
    "port": 2101,
    "mount_point": "RTCM32M7S",
    "username": "ユーザー名",
    "password": "パスワード"
  },
  "gga_send_interval": 1.0
}
```

| 項目 | 説明 |
|---|---|
| `mavlink.port` | PixhawkのTELEM1ポート (`/dev/ttyAMA0`) |
| `mavlink.baud` | **1000000 (1Mbps)** — 115200では接続できない |
| `mavlink.rtscts` | ハードウェアフロー制御 (有効必須) |
| `ntrip.*` | ichimillのNTRIP接続情報 |
| `gga_send_interval` | GGA送信間隔（秒）。通常1.0 |

## 実行方法

```bash
source ~/Mavlink_venv/bin/activate
cd ~/rtk-pipeline/dronecan_gps_rtk/ntrip_rtk_client
python3 ntrip_rtk_client.py
```

## 出力

- **RTCMログ**: `logs/rtcm_YYYYMMDD_HHMMSS.rtcm3` (バイナリ)
- **コンソール**: 接続状態、GPS状態、GGA送信数、RTCM受信量がリアルタイム表示される

## 前提条件（Pixhawk側）

ArduPilotには以下の設定が済んでいる必要がある（`../gps_can_verify/README.md`参照）:

- `CAN_P1_DRIVER = 1` (CAN1ポート有効化)
- `CAN_D1_PROTOCOL = 1` (DroneCANプロトコル)
- `GPS1_TYPE = 9` (DroneCAN GPS)
- `GPS_AUTO_CONFIG = 2` (DroneCAN AutoConfig)

本スクリプトは起動時に以下のMAVLinkストリームレートを自動設定する:
- `GPS_RAW_INT` (ID=24) を10Hzで要求
- `GLOBAL_POSITION_INT` (ID=33) を10Hzで要求
- `REQUEST_DATA_STREAM` (POSITION) を10Hzで要求

## RTCM3ログ解析

NTRIPサーバーから受信したRTCM3データを解析するスクリプトです。

### パーサー (`analyze_rtcm.py`)

[pyrtcm](https://github.com/semuconsulting/pyrtcm) ライブラリを使用して、RTCM3メッセージを解析するスクリプト。Type 1005/1006の基地局座標（ECEF X/Y/Z）を自動抽出し、緯度・経度・楕円体高に変換します。

```bash
source ~/Mavlink_venv/bin/activate
pip install pyrtcm
python3 analyze_rtcm.py logs/rtcm_YYYYMMDD_HHMMSS.rtcm3
```

**pyrtcmの利点**:
- Type 1005/1006 の基地局座標（ECEF X/Y/Z）を自動抽出
- メッセージの詳細フィールド（局ID、ITRF年、衛星インジケータ等）を取得可能
- イテレータによるストリーム処理
- エラーハンドリング（ERR_IGNORE / ERR_LOG / ERR_RAISE）
- CRC24Q検証の完全サポート

### 検証結果（2026-08-08 受信ログ）

受信したRTCM3ストリームには以下のメッセージが含まれていました：

| メッセージID | メッセージ名 | 役割 | 件数 |
|---|---|---|---|
| **1006** | Stationary RTK Reference Station ARP with Height | 基地局座標（ECEF）+ アンテナ高 | 58 |
| **1033** | Receiver and Antenna Descriptors | レシーバ・アンテナ情報 | 58 |
| **1077** | GPS MSM7 | GPS最高精度フル観測値 | 58 |
| **1087** | GLONASS MSM7 | GLONASS最高精度フル観測値 | 58 |
| **1097** | Galileo MSM7 | Galileo最高精度フル観測値 | 58 |
| **1117** | QZSS MSM7 | みちびき最高精度フル観測値 | 58 |
| **1127** | BeiDou MSM7 | BeiDou最高精度フル観測値 | 58 |

**基地局座標（Type 1006）の解析結果**:
- 局ID: 2849
- ECEF-X: -3728279.4766 m
- ECEF-Y: 3567971.4105 m
- ECEF-Z: 3735881.5539 m
- 緯度: 36.0853352° / 経度: 136.2586599° / 楕円体高: 57.09 m
- 基準局: 仮想（VRS） / ITRF年: 0（不明）
- 座標は全メッセージで安定（変動なし）

### RTCM3 MSMメッセージID対応表

RTCM3のMSM（Multiple Signal Messages）は、各衛星システムで次のように割り当てられています：

| 衛星システム | MSM1 | MSM2 | MSM3 | MSM4 | MSM5 | MSM6 | MSM7 |
|---|---|---|---|---|---|---|---|
| GPS | 1071 | 1072 | 1073 | 1074 | 1075 | 1076 | 1077 |
| GLONASS | 1081 | 1082 | 1083 | 1084 | 1085 | 1086 | 1087 |
| Galileo | 1091 | 1092 | 1093 | 1094 | 1095 | 1096 | 1097 |
| SBAS | 1101 | 1102 | 1103 | 1104 | 1105 | 1106 | 1107 |
| QZSS | 1111 | 1112 | 1113 | 1114 | 1115 | 1116 | 1117 |
| BeiDou | 1121 | 1122 | 1123 | 1124 | 1125 | 1126 | 1127 |

- **MSM4**（擬似距離 + キャリアフェーズ + 信号強度）: 標準的なRTK補正データ
- **MSM7**（最高精度フル観測値）: 高解像度の擬似距離・位相・ドップラー・C/N0

一般的な日本のNTRIPサービス（ichimill等）では、**1005/1006（基準局座標）+ 1230（GLONASSバイアス）+ 1077/1087/1097/1117/1127（MSM7）** が標準的な構成です。

## トラブルシューティング

### MAVLinkに接続できない
- ボーレートが `1000000` であるか確認
- `rtscts: true` が設定されているか確認
- TELEM1ポートの配線確認

### GGAが送信されない
- コンソールの `GPS_RAW_INT受信数` が増えているか確認
- 増えていない場合: PixhawkのGPS設定、ストリームレート設定を確認

### NTRIP接続が確立しない
- `config.json` のユーザー名・パスワード・マウントポイントを確認
- ネットワーク接続（インターネット）を確認

### RTCMが受信できない
- 送信している`$GNGGA`が有効か確認（品質インジケータが0以外か）
- `fix_type >= 3` のGPS Fixが必要（NO_FIXでは補正データが配信されない場合がある）