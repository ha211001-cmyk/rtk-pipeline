# RTK Fix Client - ichimill NTRIP + ArduPilot GPS_RTCM_DATA注入

## 概要

ArduPilot (Pixhawk6C) からMAVLinkでGPS位置情報を受信し、NMEA-0183 `$GNGGA`形式に変換してichimill NTRIPサーバーに送信。サーバーから受信したRTCM3補正データをMAVLink `GPS_RTCM_DATA` (ID:233) としてArduPilotに注入し、DroneCAN経由でH-RTK F9PのRTK Fixを実現する。

## アーキテクチャ

```
[H-RTK F9P] ←DroneCAN→ [Pixhawk6C] ←MAVLink→ [本プログラム] ←NTRIP→ [ichimill]
     │                        │                    │                  │
     │  RTCM補正データ         │  GPS_RTCM_DATA     │  RTCM3受信       │
     │  (CANバス経由で         │  (ID:233)          │  GGA送信         │
     │   自動透過転送)         │  /dev/ttyAMA0      │  TCP/IP          │
     │                        │  @ 1Mbps           │                  │
     ▼                        ▼                    ▼                  ▼
  RTK FIXED!              ArduPilot           ラズパイ           ichimill
                          GPS1_TYPE=9         rtk_fix_client     NTRIPサーバー
```

## 処理フロー

1. **MAVLink接続**: `/dev/ttyAMA0` @ 1Mbps (RTS/CTS有効) でPixhawk6Cに接続
2. **ストリームレート設定**: `GPS_RAW_INT` (ID=24) を10Hzで要求
3. **GPS Fix待機**: `fix_type >= 3` (3D_FIX) を待つ
4. **NTRIP接続**: ichimillサーバーに接続し、GPS位置から生成した`$GNGGA`を送信
5. **RTCM受信**: NTRIPサーバーからRTCM3補正データを受信
6. **RTCMフレーム解析**: `0xD3`プリアンブル検出、フレーム長取得、CRC24Q検証
7. **GPS_RTCM_DATA送信**: 180バイトずつ分割し、MAVLink `GPS_RTCM_DATA` (ID:233) でArduPilotに注入
8. **ArduPilot透過転送**: `GPS1_TYPE=9`設定により、CAN1バス上のH-RTK F9Pへ自動転送

## セットアップ

### 必要なパッケージ

```bash
# pymavlinkがインストールされた仮想環境を使用
source ~/Mavlink_venv/bin/activate

# pyrtcm（オプション、RTCM解析ログ用）
pip install pyrtcm
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
  "gga_send_interval": 1.0,
  "rtcm_inject": {
    "max_packet_size": 180,
    "max_fragments": 4,
    "target_system": 1,
    "target_component": 1
  }
}
```

| 項目 | 説明 |
|---|---|
| `mavlink.port` | PixhawkのTELEM1ポート (`/dev/ttyAMA0`) |
| `mavlink.baud` | **1000000 (1Mbps)** — 115200では接続できない |
| `mavlink.rtscts` | ハードウェアフロー制御 (有効必須) |
| `ntrip.*` | ichimillのNTRIP接続情報 |
| `gga_send_interval` | GGA送信間隔（秒）。通常1.0 |
| `rtcm_inject.max_packet_size` | GPS_RTCM_DATAの1パケット最大長（180バイト固定） |
| `rtcm_inject.max_fragments` | 1フレームあたりの最大分割数（4固定、最大720バイト） |
| `rtcm_inject.target_system` | ArduPilotのSystem ID（通常1） |
| `rtcm_inject.target_component` | ArduPilotのComponent ID（通常1） |

## 実行方法

```bash
source ~/Mavlink_venv/bin/activate
cd ~/EVK-F9P/dronecan_gps_rtk/rtk_fix_client
python3 rtk_fix_client.py
```

## 出力

- **RTCMログ**: `logs/rtcm_YYYYMMDD_HHMMSS.rtcm3` (バイナリ)
- **コンソール**: 接続状態、GPS状態、GGA送信数、RTCM受信量、GPS_RTCM_DATA送信数がリアルタイム表示される

## 前提条件（Pixhawk側）

ArduPilotには以下の設定が済んでいる必要がある（`../gps_can_verify/README.md`参照）:

- `CAN_P1_DRIVER = 1` (CAN1ポート有効化)
- `CAN_D1_PROTOCOL = 1` (DroneCANプロトコル)
- `GPS1_TYPE = 9` (DroneCAN GPS)
- `GPS_AUTO_CONFIG = 2` (DroneCAN AutoConfig)
- `GPS_PRIMARY = 0` (プライマリGPS)

## GPS_RTCM_DATA (ID: 233) 仕様

### flags (1バイト) のビット構成

| Bit | 名前 | 説明 |
|---|---|---|
| 0 (LSB) | Is_Fragmented | 分割あり=1, なし=0 |
| 1-2 | Fragment_ID | 断片番号 (0〜3) |
| 3-7 | Sequence_ID | フレームシーケンス番号 (0〜31、フレームごとに+1) |

### パケット分割ルール

- 1パケット最大: **180バイト**
- 1フレーム最大: **4分割 (720バイト)**
- 720バイト超過フレームは**ドロップ**（ArduPilot側で再構築不可のため）

### RTCM3フレーム構造

```
+--------+------------------+------------------+---------+
| 0xD3   | 長さ(10bit)      |    ペイロード     | CRC24Q  |
| 8bit   | 10bit            |    (N*8 bit)     | 24bit   |
+--------+------------------+------------------+---------+
```

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

### RTK Fixが得られない
- `GPS_RTCM_DATA送信数` が増えているか確認
- RTCMフレームが720バイトを超えてドロップされていないか確認
- ichimill側の配信設定でMSM4にするか、不要な衛星（BeiDou等）を間引く
- H-RTK F9PのLEDを確認（点灯=RTK Fix）

## ファイル構成

```
rtk_fix_client/
├── README.md              # このファイル（手順書・仕様）
├── config.json            # 接続設定
├── rtk_fix_client.py      # メインプログラム
└── logs/                  # RTCMログ保存先
```

## 動作検証結果（2026-08-08 実機テスト）

### テスト環境

| 項目 | 値 |
|---|---|
| ラズパイ | Raspberry Pi (Companion Computer) |
| Pixhawk | Pixhawk6C (ArduPilot 4.7.0 dev) |
| GPS | Holybro DroneCAN H-RTK F9P Helical (ZED-F9P) |
| 接続 | TELEM1 `/dev/ttyAMA0` @ 1Mbps (RTS/CTS有効) |
| NTRIP | ichimill `ntrip.ales-corp.co.jp:2101/RTCM32M7S` |
| 仮想環境 | `~/Mavlink_venv` (pymavlink + pyrtcm) |

### 15秒間テスト結果

| 項目 | 結果 | 判定 |
|---|---|---|
| MAVLink接続 | `/dev/ttyAMA0` @ 1Mbps (RTS/CTS) | ✅ |
| GPS受信 | RTK_FLOAT, 衛星31個, EPH 0.62m | ✅ |
| NTRIP接続 | `ntrip.ales-corp.co.jp:2101/RTCM32M7S` | ✅ |
| GGA送信 | 7回（1秒間隔） | ✅ |
| RTCM受信 | 17,960バイト | ✅ |
| RTCMフレーム解析 | 70フレーム | ✅ |
| GPS_RTCM_DATA送信 | 70フレーム（110分割パケット） | ✅ |
| フレームドロップ | 0 | ✅ |
| キュー遅延 | 0（リアルタイム処理） | ✅ |

### 検証から得られた知見

1. **RTCMフレーム分割の実態**
   - 70フレーム中、55フレームが分割不要（≤180バイト）、15フレームが分割あり（>180バイト）
   - MSM7データ（1077/1087/1097/1117/1127）の一部が180バイトを超えるが、720バイト制限内で正常に分割送信されている
   - フレームドロップはゼロ。ichimillのMSM7配信でも720バイト超過は発生していない

2. **リアルタイム性能**
   - キュー長は常にゼロ。受信→解析→注入が遅延なく追いついている
   - ラズパイの処理能力で十分にリアルタイム処理が可能

3. **GPS Fix遷移**
   - 起動時点ですでにRTK_FLOAT状態（fix_type=5）
   - RTK_FIXED（fix_type=6）への移行には通常数分の継続実行が必要
   - H-RTK F9PのLED: 点滅=RTK_FLOAT, 点灯=RTK_FIXED

4. **GGA品質マッピングの確認**
   - RTK_FLOAT時は品質インジケータ=5（float RTK）で正しく送信されている
   - `$GNGGA,193851.00,3605.1508,N,13612.5829,E,5,31,0.9,16.5,M,0.0,M,,*75`

5. **システムIDの注意点**
   - heartbeat受信直後は `システム: 0, コンポーネント: 0` と表示されるが、
     `GPS_RTCM_DATA`送信には`config.json`の`target_system: 1, target_component: 1`が使用されるため問題なし

### 継続実行方法

```bash
source ~/Mavlink_venv/bin/activate
cd ~/EVK-F9P/dronecan_gps_rtk/rtk_fix_client
python3 -u rtk_fix_client.py
```

`-u` フラグでstdoutバッファリングを無効化し、リアルタイムにログを確認できる。

## 更新履歴

- 2026-08-08: 初版作成、実機テスト完了（全機能正常動作確認）
