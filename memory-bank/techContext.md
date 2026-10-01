# 技術的知見・トラブルシューティング

## F9P基地局設定の技術知見

### 1. TMODE3 (UBX-CFG-TMODE3) 設定

#### ペイロード構造（40バイト）

```
Offset  Field       Type    説明
0       version     U1      0固定
1       reserved1   U1      0固定
2       flags       U2      mode (bits 0-1): 0=Disabled, 1=Survey-In, 2=Fixed
                          lla_fmt (bit 8): 0=ECEF, 1=LLH
4       ecefXOrLat  I4      緯度[deg] x 1e-7 (LLH時)
8       ecefYOrLon  I4      経度[deg] x 1e-7 (LLH時)
12      ecefZOrAlt  I4      高度[cm] (LLH時)
16      latHp       S1      緯度HP [deg] x 1e-9 (LLH時)
17      lonHp       S1      経度HP [deg] x 1e-9 (LLH時)
18      altHp       S1      高度HP [mm] (LLH時)
19      reserved2   U1      0固定
20      fixedPosAcc U4      固定位置精度[mm] (10000 = 10m)
24      svInNumObs  U4      0 (Survey-In用)
28      svInMinDur  U4      0 (Survey-In用)
32      svInMeanAcc U4      0 (Survey-In用)
36      reserved3   U4      0固定
```

- **重要**: ペイロードは40バイト（0x28）。32バイトではNAKが返る。
- **flags値**: `0x0102` = Fixed Mode + LLH座標形式

### 2. UBX-CFG-MSG によるRTCM出力有効化

#### 8バイトペイロード構造

```
Offset  Field   説明
0       cls     メッセージクラス (0xF5 = RTCM3)
1       id      メッセージID (例: 0x05 = 1005)
2       I2C     I2Cポートの出力レート
3       UART1   UART1ポートの出力レート
4       UART2   UART2ポートの出力レート
5       UART3   UART3ポートの出力レート
6       USB     USBポートの出力レート
7       SPI     SPIポートの出力レート
```

#### 重要な落とし穴

- **COM7はUART1（index=3）として認識される**
- USBポート（index=6）のみにレートを設定しても、UART1経由では出力されない
- **解決策**: 使用するポート（UART1）とUSBの両方にレートを設定する
  ```python
  payload = bytes([cls, id_, 0, rate, 0, 0, rate, 0])  # UART1 + USB
  ```

### 3. RTCMメッセージID一覧

| MSG ID | UBX ID | 内容 | 推奨レート |
|--------|--------|------|-----------|
| 1005   | 0x05   | 基準局座標 | 5秒毎 (rate=5) |
| 1077   | 0x4D   | GPS MSM7 | 1Hz (rate=1) |
| 1087   | 0x57   | GLONASS MSM7 | 1Hz (rate=1) |
| 1097   | 0x61   | Galileo MSM7 | 1Hz (rate=1) |
| 1127   | 0x7F   | BeiDou MSM7 | 1Hz (rate=1) |
| 1230   | 0xE6   | GLOコードフェーズバイアス | 5秒毎 (rate=5) |
| 4072   | -      | u-blox独自メッセージ | 自動出力 |

### 4. MSG 4072について

- u-blox独自のRTCM3.2プロプライエタリメッセージ
- F9Pが基地局モード時に自動的に出力
- 標準RTCMメッセージ（1005等）と混在して出力される
- pyrtcmのRTCMReaderで正しくデコード可能（identity="4072"）

### 5. RTCM受信時のプロトコル分離

F9Pのシリアル出力はUBX/NMEA/RTCMが混在するため、正確な分離が必要:

- **0xB5 0x62**: UBXフレーム（ヘッダ2 + cls/id/len4 + payload + checksum2）
- **0x24 or 0x21**: NMEA文（`$` or `!`で始まり`\n`で終わる）
- **0xD3**: RTCM3フレーム（ヘッダ3 + payload + CRC3）
  - フレーム長 = 3 + payload_length + 3
  - payload_length = `((buf[1] & 0x03) << 8) | buf[2]`
  - CRC24Q検証が可能

### 6. Windows環境での注意点

- **cp932エンコードエラー**: Unicode記号（`✓`, `✗`, `⏱`, `⚠`, `→`等）はcp932でエンコード不可
- **解決策**: ASCII文字（`[OK]`, `[ERR]`, `[TIMER]`, `[WARN]`, `->`等）を使用
- `PYTHONUTF8=1`環境変数はcmd.exeの`set`では確実に反映されない場合がある

### 7. pyrtcmライブラリの使用

```python
from pyrtcm import RTCMReader

rtr = RTCMReader(ser)  # serial.Serialオブジェクトを直接渡す
raw_data, parsed_data = rtr.read()
msg_num = parsed_data.identity  # "1005", "1077" 等
```

- RTCMReaderはUBX/NMEAフレームを自動スキップする
- 自前のプロトコル分離ロジックより確実

## 移動局（Rover）としての動作

> このイチミル（NTRIP）方式は構成Aとして `archive/legacy_ntrip_ichimill/` へ退避済みです。
> 以降のロードマップでは自作基地局（構成B）を使用します。

### イチミルRTK補正データの受信

1. NTRIP Caster（`ntrip_caster.py`）経由でイチミルのRTCMデータを取得
2. F9PのシリアルポートにRTCMデータを転送
3. F9PがRTK演算を実行し、補正された位置を出力

### u-centerでのNTRIP Client設定

1. u-center起動 → COM7（38400 baud）に接続
2. `Receiver > NTRIP Client` メニューを開く
3. イチミルのNTRIPサーバー情報を入力
4. RTCM補正データがF9Pに自動送信され、RTK演算が開始