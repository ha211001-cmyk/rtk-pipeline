# プロジェクト構造およびプログラム内容調査報告書

本ドキュメントは、rtk-pipelineプロジェクトのディレクトリ構造、各プログラムの機能、およびプラットフォーム間（Raspberry Pi vs Windows）の違いと重複を整理したものです。

## 1. プロジェクト概要
本プロジェクトは、u-blox ZED-F9P GNSSモジュールを用いてRTK測位を行うためのシステムです。基地局（Base Station）の設定、NTRIPプロトコルを用いた補正データの配信、およびPPK（後処理RTK）用の生観測値ロギングの3つの主要機能で構成されています。

## 2. ディレクトリ構造と役割
| ディレクトリ | 内容・役割 | 備考 |
| :--- | :--- | :--- |
| `gcs/` | 統合 GCS：Web ダッシュボード（FastAPI + Web UI）・RTK-FIXED 判定・RTCM 監視・F9P 設定/RTCM 転送・systemd デプロイ・pytest | `app/`・`web/`・`rtk_tools/`・`config/`・`deploy/`・`integration/` 等 |
| `raspberrypi/` | Raspberry Pi 5向け実行スクリプト | `/dev/ttyACM0` を使用する環境向け |
| `memory-bank/` | プロジェクトの設計思想、技術コンテキスト | `projectbrief.md`, `systemPattern.md` 等 |
| `single_unit_test/` | 実機2台（基地局+ローバー）による RTK Fix 達成時 再現・検証テスト | `archive/rtk_field_test/` 等の既存資産を thin wrapper で再利用 |
| `archive/` | 過去のツール、検証、ログ、ガイド資料の退避先 | 旧Windows版（COM6/COM13）・構成A・各種検証フォルダを含む |
| `archive/windows/` | Windows PC向け実行スクリプト（2026-09-28 退避） | COMポートを使用、Flash永続化対応 |
| `archive/base_station_verify/` | 基地局モードの動作検証（2026-09-28 退避） | RTCM比較・MSM7出力検証 |
| `archive/dronecan_gps_rtk/` | DroneCAN GPS RTK 検証（2026-09-28 退避） | gps_can_verify / ichimill_sim / ntrip_rtk_client / rtk_fix_client |
| `archive/ppkLogs/` | PPK処理用データの保存先（2026-09-28 退避） | `data/` / `result/` / `script/` 構成 |
| `archive/rtk_base_mavlink/` | MAVLink経由のRTK基地局（2026-09-28 退避） | GPS_RTCM_DATA注入（ichimill不使用） |
| `archive/rtk_field_test/` | フィールドテスト・RTK記録解析（2026-09-28 退避） | GLONASS両側オフ検証 |
| `archive/udp/` | UDP経由のRTK中継・RTCMモニター（2026-09-28 退避） | Mac mini → WiFi(UDP) → ラズパイ → MAVLink |
| `archive/wifi_scripts/` | Wi-Fi設定関連スクリプト（2026-09-28 退避） | `setup_wifi*.sh` / `setup_wifi*.py` |
| `archive/ichimill_log/` | イチミル NTRIP ログ取得（macOS 版・残骸） | シンボリックリンク |

## 3. 主要プログラムの機能分析

### A. 基地局設定 (Base Station Setup)
F9Pを固定点モード（Fixed Mode）に設定し、RTCM3補正信号を出力させるための初期化スクリプト。
- **共通機能**: 固定座標の設定、TMODE3の有効化、RTCMメッセージ（1005, 1077等）の出力許可。

### B. NTRIPキャスター (NTRIP Caster)
基地局から受信したRTCM3信号をネットワーク経由でローバーへ配信するサーバー機能。
- **共通機能**: マルチスレッドによるクライアント接続管理、RTCMフレームの抽出とブロードキャスト、ソーステーブルの生成。

### C. PPKロガー (PPK Logger)
後処理RTKのために、高精度な生観測値（RAWX）および航法フレーム（SFRBX）をCSV形式で保存するツール。
- **共通機能**: `pyubx2` を使用したパケット解析、ミリ秒単位のタイムスタンプ付与、統計情報の表示。

## 4. プラットフォーム間の違いと重複の検討

### プログラム間の差異
| 機能 | Raspberry Pi 版 | Windows 版 | 差異の理由 |
| :--- | :--- | :--- | :--- |
| **シリアル通信** | `/dev/ttyACM0` | `COM6` (動的変更可) | OSによるデバイスパスの違い |
| **UBX操作方法** | 手動パケット構築 (`struct`) | `pyubx2` ライブラリ使用 | Windows版でのFlash永続化対応のため |
| **文字エンコーディング** | 標準的なUTF-8 | CP932対策を含むUnicode設定 | Windows環境での表示エラー防止 |
| **座標計算** | 内部変換を最小限に抑制 | ECEFへの正確な変換処理を含む | より厳密な位置情報の保持のため |

### プログラム間の重複と整理のポイント
- **ロジックの共通性**: NTRIPプロトコルの実装やPPKデータの保存形式は両プラットフォームでほぼ同一です。
- **整理の提案**: 
    1.  **コアロジックの分離**: RTCM解析やNTRIPサーバーの基本クラスを共通ライブラリ化することで、プラットフォーム固有の差異（シリアルポート操作等）のみを切り分ける構造にすると保守性が向上します。
    2.  **設定ファイルの外部化**: 現在は各スクリプト内にハードコードされている固定座標や通信パラメータを、JSONやYAML等の外部ファイルから読み込むように統一することで、プログラムの再利用性を高めることができます。

## 5. まとめ
本プロジェクトは非常に整理されており、プラットフォームごとに最適化された実用的な構成になっています。特にPPKロガーの実装は高度であり、データの整合性が保たれています。今後の拡張においては、共通ロジックの抽象化を進めることで、さらなるメンテナンス性の向上が期待できます。