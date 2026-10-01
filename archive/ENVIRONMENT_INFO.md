# ENVIRONMENT SUMMARY (for AI use)

## 基本情報
- **OS**: Windows 10/11
- **Python**: 3.11.9 (native installation at C:/Users/keita/AppData/Local/Programs/Python/Python311)
- **Project location**: C:/Users/keita/Documents/Local/rtk-pipeline
- **Execution**: Use standalone Python executable: `C:/Users/keita/AppData/Local/Programs/Python/Python311/python.exe`
- **Device**: u-blox F9P GNSS receiver (RTK-capable)
- **Connection**: USB Serial Device (COM13 - normally, COM6 in gps_display.py)
- **Connection method**: USB virtual COM port (not UART physical pins)

## Python環境
### インストール済みライブラリ一覧
**GNSS/GPS関連**:
- `pyubx2` (1.2.60) - UBX プロトコル解析・生成 (u-blox binary)
- `pynmeagps` (1.1.2) - NMEA 0183 解析・生成
- `pyrtcm` (1.1.10) - RTCM3 解析 (RTK修正データ)
- `pyspartn` (1.0.8) - SPARTN 解析 (u-blox proprietary RTK correction)
- `pygnssutils` (1.1.22) - GNSS utility library (CLI tools + Python API)
- `pyubxutils` (1.0.6) - UBX utility functions
- `pyunigps` (0.2.0) - UNI protocol support
- `pysbf2` (1.0.3) - Septentrio SBF protocol
- `pyqgc` (0.2.2) - Quectel protocol
- `pygpsclient` (1.6.4) - GPS client library
- `pygnssutils` (1.1.22) - GNSS utilities CLI

**通信・ネットワーク関連**:
- `pyserial` (3.5) - Serial port communication
- `paho-mqtt` (2.1.0) - MQTT client (SPARTN IP support)
- `requests` (2.32.5) - HTTP requests (NTRIP)

**その他実用**:
- beautifulsoup4, pillow, openpyxl など

## RTK (Real-Time Kinematic) 統合について

### RTKの動作原理
RTKは基準局からの修正データをローバー受信機に流し込み、衛星信号の搬送波位相を使用して
**センチメートル精度の位置情報**を実現します。
- 基準局: 既知位置からRTCM3またはSPARTN修正データを送信
- ローバー: 修正データを受信しリアルタイムで位置計算を改善

### 利用可能なRTK配信プロトコル

**1. NTRIP (Networked Transport of RTCM via Internet Protocol)**
- インターネット経由でRTCM3修正データを配信
- 公開NTRIP Caster例:
  - **rtk2go.com** (無料、国内外のマウントポイント多数)
  - その他商用サービス
- 利用ライブラリ: `pygnssutils.GNSSNTRIPClient` または CLI `gnssntripclient`

**2. SPARTN IP (MQTT経由)**
- u-blox Thingstream (PointPerfect) サービス
- モバイルネットワーク対応
- 利用ライブラリ: `pygnssutils.GNSSMQTTClient` または CLI `gnssmqttclient`

**3. 国内サービス (イチミル等)**
- 具体的なサービス仕様が必要な場合は、提供者のドキュメントを確認
- NTRIPまたはMQTT形式の場合、上記ライブラリで対応可能

### RTK流し込みの基本フロー
```
┌─────────────┐         NTRIP/MQTT        ┌──────────────┐
│ RTK Caster  │──────→ 修正データ ────────→│ F9P Receiver │
│(rtk2go.com) │                          │   (Rover)    │
└─────────────┘                          └──────┬───────┘
                                              │
                                          GNSS Fix
                                          ↓
                                    高精度位置情報
                               (cm-level accuracy)
```

## スクリプト実行方法

### 単一スクリプト実行例
```powershell
C:/Users/keita/AppData/Local/Programs/Python/Python311/python.exe gps_display.py
```

### RTK流し込みスクリプト実行例 (作成予定)
```powershell
C:/Users/keita/AppData/Local/Programs/Python/Python311/python.exe rtk_input.py --port COM13 --server rtk2go.com --mountpoint YOURMOUNT
```

## 注記
- USB通信なのでボーレート設定は無視される（実効レート直接指定不要）
- NTRIP接続にはインターネット接続が必須
- 認証情報（ユーザー名・パスワード）は環境変数または実行時入力推奨
- RTK修正データ取得まで通常5-30秒の初期化時間が必要
