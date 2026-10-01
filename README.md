# rtk-pipeline プロジェクト

u-blox ZED-F9P（rtk-pipeline）を用いた RTK 測位システムのプロジェクトです。
基地局（Base Station）/ 移動局（Rover）の設定、NTRIP 補正データの配信・受信、
および PPK（後処理 RTK）用の生観測値ロギングなどを扱っています。

## 主な機能

- **基地局（Base Station）**: F9P を TMODE3 Fixed Mode に設定し、RTCM3 補正データ（1005/1077/1087/1097/1127/1230 等）を生成・配信。
- **移動局（Rover）**: 自作基地局（構成B）が配信する RTCM3 補正データを F9P に流し込み、RTK Float / Fixed 測位を実行。
- **PPK（後処理 RTK）**: UBX-RXM-RAWX / RXM-SFRBX の生観測値を CSV に記録し、後処理解析に利用。

## ディレクトリ構成

```text
rtk-pipeline/
├── README.md                               # 本ドキュメント
├── PROJECT_STRUCTURE_AND_CONTENT_REPORT.md # 構造・プログラム調査報告書
├── requirements.txt                        # 依存ライブラリ
├── .gitignore
│
├── gcs/                      # 統合 GCS：Web ダッシュボード + RTK 判定/監視 + systemd デプロイ
├── memory-bank/              # プロジェクト知識ベース
├── raspberrypi/              # Raspberry Pi 5 向けスクリプト
├── single_unit_test/         # 実機2台（基地局+ローバー）による RTK Fix 達成時 再現・検証テスト
│
└── archive/                  # 過去のツール・検証・ログ等の退避先
    ├── base_station_verify/  # 基地局モードの動作検証
    ├── dronecan_gps_rtk/     # DroneCAN GPS RTK 検証
    ├── ichimill_log/         # イチミル NTRIP ログ取得（macOS 版・残骸）
    ├── legacy_ntrip_ichimill/# 構成A（NTRIP/イチミル依存）退避先
    ├── ppkLogs/              # PPK 後処理用データ保存先
    ├── rtk_base_mavlink/     # MAVLink 経由 RTK 基地局
    ├── rtk_field_test/       # フィールドテスト・RTK 記録解析
    ├── udp/                  # UDP 経由 RTK 中継
    ├── wifi_scripts/         # Wi-Fi 設定関連スクリプト
    └── windows/              # Windows PC 向けスクリプト

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
- `gcs/rtk_tools/rtk_base_station_v2.py` は、接続してきた複数のクライアント（GCS Webサーバー、中継ブリッジ、常駐サービス等）に対して、RTCM3 フレームを同一複製して一斉配信（ブロードキャスト）します。切断された古いセッションがキューを奪い合わないよう、各接続ごとに独立キューで保護されています。

---

## 🚀 推奨起動コマンド（統合パイプライン）

### ① 基地局側（Mac）
```bash
# 1. 基地局 F9P から RTCM 配信
python3 gcs/rtk_tools/rtk_base_station_v2.py --config gcs/config/base_station.json --serial-port /dev/cu.usbmodem112301

# 2. Web ダッシュボード起動 (別ターミナル)
python3 -m gcs.server --port 9000
# ブラウザで http://localhost:9000 を開き、右上の「Connect」を押す
```

### ② ローバー側（Raspberry Pi 5）
```bash
cd ~/rtk-pipeline
~/Mavlink_venv/bin/python3 gcs/rtk_tools/mavlink_bridge.py --serial /dev/ttyAMA0 --baud 921600 --target-host <Mac_Tailscale_IP>
```
これで Mac の Web ダッシュボードにドローンが表示され、数秒〜数十秒で **`RTK: Fixed`（緑色点灯）** に到達します。