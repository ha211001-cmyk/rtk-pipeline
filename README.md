# EVK-F9P プロジェクト

u-blox ZED-F9P（EVK-F9P）を用いた RTK 測位システムのプロジェクトです。
基地局（Base Station）/ 移動局（Rover）の設定、NTRIP 補正データの配信・受信、
および PPK（後処理 RTK）用の生観測値ロギングなどを扱っています。

## 主な機能

- **基地局（Base Station）**: F9P を TMODE3 Fixed Mode に設定し、RTCM3 補正データ（1005/1077/1087/1097/1127/1230 等）を生成・配信。
- **移動局（Rover）**: 自作基地局（構成B）が配信する RTCM3 補正データを F9P に流し込み、RTK Float / Fixed 測位を実行。
- **PPK（後処理 RTK）**: UBX-RXM-RAWX / RXM-SFRBX の生観測値を CSV に記録し、後処理解析に利用。

## ディレクトリ構成

```text
EVK-F9P/
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