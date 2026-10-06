# rtk-pipeline-local プロジェクト（ローカルネットワーク版）

u-blox ZED-F9P を用いた RTK 測位システムのプロジェクトです。
**Tailscale（VPN）を使用せず、Mac を Wi-Fi ルーター（親機）とし、アクセスポイント（AP）を経由して基地局、PC、ローバー（Raspberry Pi）が通信するスタンドアロン・ローカルネットワーク版**です。

---

## 🌐 ネットワーク構成（Tailscale不要版）

```text
┌───────────────────────────────────────────────┐
│              Mac (地上基地局 & GCS)            │
│  - IP: 192.168.2.1 (Wi-Fi/有線ルーター親機)    │
│  - 基地局 F9P: USB (/dev/cu.usbmodem112301)   │
│  - RTCM3 配信: TCP 2101                       │
│  - Web GCS ダッシュボード: http://localhost:9000│
│                           (UDP:14550 受信)    │
└───────────────────────┬───────────────────────┘
                        │ 有線LAN (USB-LANアダプタ)
┌───────────────────────▼───────────────────────┐
│         アクセスポイント (BUFFALO AP)          │
│  - IP: 192.168.2.3 (ブリッジ接続)              │
└───────────────┬───────────────────────┬───────┘
                │ Wi-Fi                 │ Wi-Fi
┌───────────────▼───────────────┐   ┌───▼───────────────────────────┐
│ ローバー (Raspberry Pi 5)     │   │ 別のPC (監視 / 作業用ノートPC)│
│  - IP: 192.168.2.x (DHCP)     │   │  - IP: 192.168.2.2 (DHCP)     │
│  - Pixhawk: /dev/ttyAMA0      │   │  - ブラウザ等で GCS を閲覧可能 │
│  - mavlink_bridge.py 実行     │   │    http://192.168.2.1:9000    │
└───────────────────────────────┘   └───────────────────────────────┘
```

## 主な機能

- **基地局（Base Station）**: F9P を TMODE3 Fixed Mode に設定し、RTCM3 補正データ（1005/1077/1087/1097/1127/1230 等）を生成・TCP 2101 でローカル配信。
- **移動局（Rover）**: 自作基地局が配信する RTCM3 補正データを F9P に流し込み、RTK Float / Fixed 測位を実行。
- **ローカル MAVLink ブリッジ**: ラズパイ上の `mavlink_bridge.py` がデフォルトで `192.168.2.1`（Mac）へ自動接続。
- **PPK（後処理 RTK）**: UBX-RXM-RAWX / RXM-SFRBX の生観測値を CSV に記録し、後処理解析に利用。

## ディレクトリ構成

```text
rtk-pipeline-local/
├── README.md                               # 本ドキュメント
├── requirements.txt                        # 依存ライブラリ
├── .gitignore
│
├── gcs/                      # 統合 GCS：Web ダッシュボード + RTK 判定/監視 + デプロイ
├── memory-bank/              # プロジェクト知識ベース
├── raspberrypi/              # Raspberry Pi 5 向けスクリプト
├── single_unit_test/         # 実機2台（基地局+ローバー）による RTK Fix 達成時 再現・検証テスト
│
└── archive/                  # 過去のツール・検証・ログ等の退避先
```

---

## 🛠️ RTK FIXED 達成のための運用ノウハウ・トラブルシューティング

実機テストおよびフィールド試験で判明した、RTK 測位を確実に `RTK_FIXED`（fix_type: 6）へ到達させるための必須要件です。

### 1. 基地局座標の整合性（3D_FIX のまま RTK に遷移しない場合の最大原因）
- **現象**: 補正データ（RTCM）は毎秒正常に受信されているのに、何分待っても `3D_FIX`（3）のままで `RTK_FLOAT`（5）や `RTK_FIXED`（6）に上がらない。
- **原因**: 基地局アンテナの実際の位置と、設定ファイル（`gcs/config/base_station.json` 等）に指定した座標に数十〜数百メートルの乖離がある。
  - RTK は基地局と移動局の電波位相差（波長約19cm）からミリ単位で解析するため、基地局の申告座標が実際とズレていると幾何学的位相が破綻し、Rover F9P が異常データと判定して RTK 計算を拒絶します。
- **対策**: アンテナを設置・移動した際は、必ず単独測位で現在地を実測し、設定ファイルに反映してください。
  ```bash
  # 基地局アンテナの現在座標を実測（Mac側）
  python3 single_unit_test/run_survey.py --set-rover --duration 30
  # 出力された平均緯度・経度・楕円体高(HAE)を gcs/config/base_station.json に記入
  ```

### 2. Pixhawk TELEM1 の高速シリアル要件（921600 bps）
- **ハードウェアフロー制御（RTS/CTS）**:
  Pixhawk の TELEM1（921600 bps）へ RTCM パケットを流し込む場合、**RTS/CTS フロー制御（`--rtscts`）** が必須です。フロー制御が無効だと送信バッファ溢れにより RTCM パケットが破損・破棄されます。
- **MAVLink 2.0 必須**:
  ArduPilot の RTCM 注入メッセージ（`GPS_RTCM_DATA`）は MAVLink 2.0 パケット（ヘッダー `0xFD`）で送る必要があります。`pymavlink` を使う際は、必ず import 前に `os.environ["MAVLINK20"] = "1"` を指定してください（指定しないと MAVLink 1.0 `0xFE` となり Pixhawk 側で弾かれます）。

### 3. Raspberry Pi 5 のポート構成と Python 仮想環境
- **Pixhawk 接続 UART**: `/dev/ttyAMA0`（921600 bps）
- **Rover F9P 直結 UART2（構成による）**: `/dev/ttyAMA4`（115200 bps）
- **実行環境**: Raspberry Pi 上で `pymavlink` を動かす際は、専用仮想環境（`~/Mavlink_venv/bin/python3`）を使用してください。

### 4. 基地局 RTCM 配信（マルチクライアント・ブロードキャスト）
- `gcs/rtk_tools/rtk_base_station_v2.py` は、接続してきた複数のクライアント（GCS Webサーバー、中継ブリッジ、常駐サービス等）に対して、RTCM3 フレームを同一複製して一斉配信（ブロードキャスト）します。

---

## 🚀 推奨起動コマンド（ローカル統合パイプライン）

### ① 基地局側（Mac: IP `192.168.2.1`）
```bash
cd ~/rtk-pipeline-local
source .venv/bin/activate

# 1. 基地局 F9P から RTCM 配信 (TCP 0.0.0.0:2101)
python3 gcs/rtk_tools/rtk_base_station_v2.py --config gcs/config/base_station.json --serial-port /dev/cu.usbmodem112301

# 2. Web ダッシュボード起動 (別ターミナル)
python3 -m gcs.server --port 9000
# ブラウザで http://localhost:9000 (または別PCから http://192.168.2.1:9000) を開き、右上の「Connect」を押す
```

### ② ローバー側（Raspberry Pi 5: IP `192.168.2.x`）
```bash
cd ~/rtk-pipeline-local
# 引数なしで自動的に Mac (192.168.2.1) に接続されます
~/Mavlink_venv/bin/python3 gcs/rtk_tools/mavlink_bridge.py --serial /dev/ttyAMA0 --baud 921600

# ※ 明示的に指定する場合:
# ~/Mavlink_venv/bin/python3 gcs/rtk_tools/mavlink_bridge.py --serial /dev/ttyAMA0 --baud 921600 --target-host 192.168.2.1
```
これで Mac の Web ダッシュボードにドローンが表示され、数秒〜数十秒で **`RTK: Fixed`（緑色点灯）** に到達します。