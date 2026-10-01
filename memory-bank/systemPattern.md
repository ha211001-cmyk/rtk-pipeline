# システム設計・アーキテクチャ

## ディレクトリ構成

```
EVK-F9P/
|-- archive/windows/      # Windows環境用スクリプト（archiveへ退避）
|   |-- base_station.py   # 基地局モード設定・RTCM生成
|   |-- ntrip_caster.py   # NTRIP Caster機能（ローカル配信）
|   |-- gps_display.py    # GPS情報表示
|   |-- gps_statistics.py # GPS統計情報
|   |-- ppk_logger.py     # PPKログ記録
|
|-- raspberrypi/          # Raspberry Pi環境用スクリプト
|   |-- base_station.py   # 基地局モード設定
|   |-- ntrip_caster.py   # NTRIP Caster機能（ローカル配信）
|   |-- gps_display.py    # GPS情報表示
|   |-- gps_statistics.py # GPS統計情報
|   |-- ppk_logger.py     # PPKログ記録
|   |-- setup.sh          # セットアップスクリプト
|
|-- archive/legacy_ntrip_ichimill/  # 構成A（NTRIP/イチミル依存）退避先
|   |-- windows/ichimile_log.py / ichimile_nolog.py
|   |-- raspberrypi/ichimile_log.py / ichimile_nolog.py
|   |-- ichimill_log/     # macOS版
|   |-- base_station_verify/check_ntrip.py / check_ntrip2.py
|
|-- archive/ppkLogs/      # PPKログ・解析（archiveへ退避）
|   |-- data/             # ログデータ
|   |-- result/           # 解析結果
|   |-- script/           # 解析スクリプト
|
|-- archive/              # アーカイブ（旧版・参考資料）
|   |-- RTK_GUIDE.md      # RTK設定ガイド
|   |-- PROJECT_SUMMARY.md
|   |-- ENVIRONMENT_INFO.md
|
|-- memory-bank/          # メモリバンク（プロジェクト知識ベース）
|   |-- projectbrief.md   # プロジェクト概要
|   |-- activeContext.md  # 現在の状況・進捗
|   |-- techContext.md    # 技術的知見
|   |-- systemPattern.md  # システム設計（本ファイル）
|
|-- README.md
|-- requirements.txt
|-- .venv/                # Python仮想環境
```

## システム構成パターン

### パターン1: 移動局（Rover）単体動作（構成A・退避済み）

> この構成は外部 NTRIP キャスター（イチミル）に依存する **構成A** のため、
> 該当スクリプト（`ichimile_log.py` / `ichimile_nolog.py`）は
> `archive/legacy_ntrip_ichimill/` へ退避済みです。以降のロードマップでは使用しません。

```
[イチミルRTKサーバー] --NTRIP--> [ntrip_caster.py] --RTCM--> [F9P (COM7)]
                                                                      |
                                                                      v
                                                              [RTK測位結果出力]
```

- `ichimile_log.py` / `ichimile_nolog.py` がメインスクリプト（現在は archive/ に退避）
- NTRIP Caster経由でイチミルの補正データを取得
- F9PがRTK演算を実行

### パターン2: 基地局（Base Station）単体動作

```
[固定座標入力] --> [base_station.py] --> [F9P (COM7)]
                                           |
                                           v
                                    [RTCM3信号生成・出力]
```

- `base_station.py` がTMODE3 Fixed Modeを設定
- F9Pが標準RTCM3メッセージを生成
- 生成されたRTCMデータはシリアルから出力

### パターン3: 基地局 + NTRIP Caster配信（将来構想）

```
[固定座標] --> [base_station.py] --> [F9P] --RTCM--> [ntrip_caster.py] --NTRIP--> [移動局]
```

- 基地局が生成したRTCMをNTRIP Casterで配信
- 別のF9P移動局が補正データとして受信

## 通信設定

| 項目 | 値 |
|------|-----|
| ボーレート | 38400 baud |
| Windows COMポート | COM7 |
| F9Pポートマッピング | COM7 = UART1 (index=3) |
| UBX-CFG-MSGペイロード | 8バイト版 |

## 使用ライブラリ

| ライブラリ | 用途 |
|-----------|------|
| pyserial | シリアル通信 |
| pyrtcm | RTCM3メッセージデコード |
| pyubx2 | UBXプロトコル処理（参考） |
| argparse | コマンドライン引数処理 |