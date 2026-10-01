# archive — 過去ツール・検証・デバッグ・ガイド資料の退避ディレクトリ

本プロジェクト（EVK-F9P）で過去に使用していた**ツール・検証スクリプト・デバッグ用スクリプト・
ガイド資料・ログ**を退避・保存するためのディレクトリです。

現在の実装は `gcs/`（現役 GCS）・`raspberrypi/`・`memory-bank/`・`single_unit_test/` に
集約されており、本ディレクトリ内のファイルは**旧版・参考資料・検証済みの過去成果物**として
残しています。

## 背景・目的

- 初期プロジェクト（2026-03-01 作成）の Windows 版ツール群と、それらを説明するガイド資料を
  一箇所にまとめて退避する。
- 現在は Raspberry Pi / Linux ベースの基地局・ローバー構成（構成B）と GCS（`gcs/`）へと
  発展しており、ここに退避したツール群はメンテナンス対象から外れている。
- 過去の設計思想や NTRIP/RTK の基本知識は後続の実装でも参照できるため、参考資料として保持している。

## 2026-09-28 に追加退避したフォルダ

以下のフォルダは 2026-09-28 のリポジトリ整理でルート直下から `archive/` へ退避しました。

| 退避先 | 内容・役割 |
| :--- | :--- |
| `base_station_verify/` | 基地局モードの動作検証（RTCM比較・MSM7出力検証） |
| `dronecan_gps_rtk/` | DroneCAN GPS RTK 検証（gps_can_verify / ichimill_sim / ntrip_rtk_client / rtk_fix_client） |
| `rtk_base_mavlink/` | MAVLink経由のRTK基地局（GPS_RTCM_DATA注入・ichimill不使用） |
| `rtk_field_test/` | フィールドテスト・RTK記録解析（GLONASS両側オフ検証） |
| `ppkLogs/` | PPK処理用データの保存先（`data/` / `result/` / `script/` 構成） |
| `udp/` | UDP経由のRTK中継・RTCMモニター（Mac mini → WiFi → ラズパイ → MAVLink） |
| `wifi_scripts/` | Wi-Fi設定関連スクリプト（`setup_wifi*.sh` / `setup_wifi*.py`） |
| `windows/` | Windows PC向け実行スクリプト（COMポート・Flash永続化対応） |
| `ichimill_log/` | イチミル NTRIP ログ取得（macOS 版・残骸シンボリックリンク） |

> `gcs/`・`raspberrypi/`・`memory-bank/`・`single_unit_test/` は現役のため退避していません。

## ディレクトリ構成

```
archive/
├── README.md               # このファイル（全体概要）
│
├── ENVIRONMENT_INFO.md     # 環境情報詳細（AI用）
├── PROJECT_SUMMARY.md      # プロジェクト全体サマリー
├── RTK_GUIDE.md            # RTK利用ガイド
│
├── debug_nmea.py           # NMEAメッセージ属性ダンプ（デバッグ）
├── debug_serial.py         # シリアル生データ確認（デバッグ）
├── gps_console.py          # GPS表示（コンソール版 / UBX・NMEA対応）
├── gps_simple.py           # GPS表示（シンプル版 / NMEA）
├── rtk_input.py            # RTK修正データ流し込み（NTRIP/SPARTN）
├── ubx_mon_hw.py           # UBX MON-HW/EXTENDED ハードウェア監視
├── run.bat                 # Windows実行メニュー
│
├── legacy_ntrip_ichimill/  # 構成A（NTRIP/イチミル依存）スクリプトの退避先
│   ├── windows/            # 元 windows/ のイチミル NTRIP クライアント
│   ├── raspberrypi/        # 元 raspberrypi/ のイチミル NTRIP クライアント
│   ├── ichimill_log/       # 元 ichimill_log/（macOS 版）
│   ├── base_station_verify/# 元 base_station_verify/ の NTRIP 接続確認スクリプト
│   └── README.md           # 各スクリプトの用途と封印理由
│
├── base_station_verify/    # 基地局モードの動作検証（2026-09-28 退避）
├── dronecan_gps_rtk/       # DroneCAN GPS RTK 検証（2026-09-28 退避）
├── ichimill_log/           # イチミル NTRIP ログ取得（macOS 版・残骸シンボリックリンク）
├── ppkLogs/                # PPK 処理用データ保存先（2026-09-28 退避）
├── rtk_base_mavlink/       # MAVLink 経由 RTK 基地局（2026-09-28 退避）
├── rtk_field_test/         # フィールドテスト・RTK 記録解析（2026-09-28 退避）
├── udp/                    # UDP 経由 RTK 中継（2026-09-28 退避）
├── wifi_scripts/           # Wi-Fi 設定関連スクリプト（2026-09-28 退避）
└── windows/                # Windows PC 向けスクリプト（2026-09-28 退避）
```

## 各ファイルの役割

### ガイド・ドキュメント

| ファイル | 内容 |
|---------|------|
| `ENVIRONMENT_INFO.md` | 開発環境の詳細（OS / Python / インストール済みライブラリ / RTK の動作原理 / 実行方法）を AI 向けにまとめた資料 |
| `PROJECT_SUMMARY.md` | プロジェクト全体の構成・クイックスタート・RTK 機能説明・チェックリスト・バージョン履歴をまとめたサマリー |
| `RTK_GUIDE.md` | NTRIP サービス別（RTK2GO / イチミル）の接続手順・コマンドラインオプション・トラブルシューティング・FAQ をまとめた RTK 利用ガイド |

### スクリプト

| ファイル | 内容 |
|---------|------|
| `debug_nmea.py` | `pynmeagps` の `NMEAReader` で COM6 から NMEA メッセージを読み込み、先頭 20 メッセージの属性をすべてダンプするデバッグツール |
| `debug_serial.py` | COM6 から受信する生バイト列を Hex / ASCII 表示し、UBX フレーム（`0xB5 0x62`）を検出するシリアル通信デバッグツール |
| `gps_console.py` | `pyubx2` / `pynmeagps` の両方に対応し、UBX・NMEA の主要メッセージをリアルタイム表示するコンソール版表示プログラム |
| `gps_simple.py` | `pynmeagps` のみを使用したシンプルな NMEA 表示プログラム（GGA / RMC / GSA / VTG / GSV を表示） |
| `rtk_input.py` | `pygnssutils` の `GNSSNTRIPClient` で NTRIP サーバーから RTK 修正データを受信し、F9P に流し込みつつ位置情報を表示するプログラム（対話モード / コマンドライン引数対応） |
| `ubx_mon_hw.py` | `pyubx2` で UBX の MON-HW / MON-HW2 / MON-IO をポーリングし、ハードウェア状態（ノイズ・AGC・通信バッファ等）を確認するツール |
| `run.bat` | Windows で GPS 表示・RTK 入力・デバッグをメニューから選択実行するためのバッチランチャー |

## 既存ドキュメントとの関係

本ディレクトリの 3 つの `.md` ファイルは、初期 Windows 版プロジェクトのドキュメント一式です。

- `ENVIRONMENT_INFO.md` … 開発環境・ライブラリ・RTK の基本知識（NTRIP / SPARTN / イチミル）を詳述。AI に環境を伝えるための資料。
- `PROJECT_SUMMARY.md` … プロジェクト全体像と、`gps_*.py` / `rtk_input.py` / `run.bat` などの使い方・クイックスタートを集約。
- `RTK_GUIDE.md` … `rtk_input.py` の詳細な使い方（NTRIP サービス別手順・CLI オプション・トラブルシューティング）を集約。

これら 3 資料は、同ディレクトリ内のスクリプト群を読者・AI が理解・実行するための補助資料として
機能します。すなわち、`ENVIRONMENT_INFO.md` が「環境」、`PROJECT_SUMMARY.md` が「全体構成」、
`RTK_GUIDE.md` が「RTK の具体的な操作手順」をそれぞれ担当する役割分担になっています。

## 前提・注意

- 本ディレクトリのスクリプトは **Windows 環境（COM6 / COM13、Python 3.11.9）を前提**に作成されています。
  - 現在の Raspberry Pi / Linux 環境で使う場合は `raspberrypi/` や `gcs/` の実装を参照してください。
- 初期版のため、シリアルポート名がスクリプト内にハードコードされている箇所があります（例: `COM6`）。
- RTK 関連の検証結果・知見は本ディレクトリ配下の `base_station_verify/`・`rtk_base_mavlink/`・
  `udp/`・`rtk_field_test/`・`dronecan_gps_rtk/`（いずれも 2026-09-28 退避）を参照してください。

## 更新履歴

- 2026-03-01: 初期プロジェクト作成時に、本ディレクトリのファイル一式（ガイド 3 点＋スクリプト 6 点＋run.bat）を追加。
- 2026-09-27: 本 README を新規作成。
- 2026-09-28: リポジトリ整理に伴い `base_station_verify/`・`dronecan_gps_rtk/`・
  `rtk_base_mavlink/`・`rtk_field_test/`・`ppkLogs/`・`udp/`・`wifi_scripts/`・
  `windows/`・`ichimill_log/` をルート直下から本ディレクトリへ退避し、本 README を更新。
