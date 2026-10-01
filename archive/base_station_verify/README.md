# base_station_verify — 基地局モード 検証ディレクトリ

RTK 基地局モードで動作する F9P モジュールの動作を検証するためのディレクトリです。
本プロジェクト（EVK-F9P-1）の最終目標は、基地局モードで出力される RTCM 補正データを
別経路（ichimill 等）で取得した RTCM データと比較し、**メッセージ内容やバイナリ形式に
問題がないか**を検証することです。

## 背景・目的

- 基地局モード（TMODE3 Fixed Mode）に設定した F9P が、どのような RTCM メッセージを
  シリアル出力するかをログで確認する。
- 取得した RTCM ログを、既に取得済みの ichimill 由来の RTCM ログと比較する。
- 比較により、以下の観点で問題がないかを確認する。
  - RTCM3 フレーム構造（`0xD3` プリアンブル / フレーム長 / CRC24Q）が正しいか
  - メッセージタイプの構成（1005/1006, 1019/1020, MSM4/1074/1084/1094/1124 等）に
    差分がないか
  - 基地局座標（Type 1005/1006 の ECEF X/Y/Z）が正しいか

## ディレクトリ構成

```
base_station_verify/
├── README.md               # このファイル（全体概要）
├── check_tmode3_web.txt    # TMODE3 確認用 u-blox Portal ページ取得結果（HTML）
├── config/                 # 共通設定ファイル
│   └── config.yml          # F9P シリアルポート等の設定
├── rtcm_compare/           # RTCM データ比較 検証
│   ├── README.md           # RTCM 比較の目的・手順
│   ├── rtk_RTCM_Log2.py    # F9P 基地局 → RTCM ログ取得（単体動作版）
│   ├── f9p_configurator_v2.py
│   ├── standalone_obs.py
│   ├── config_loader.py
│   └── logs/               # 取得した RTCM/ログ出力先
└── rtcm_verification/      # F9P基地局 vs ichimill RTCMログ比較検証
    ├── README.md           # 検証結果・知見まとめ
    ├── step1_analyze_f9p_logs.py
    ├── step2_analyze_ichimill_logs.py
    ├── step3_compare.py
    └── results/            # 解析結果出力先
```

> `rtk_RTCM_Log2.py` は `GCS-UmemotoLab/rtk_tools/rtk_RTCM_Log2.py` を、
> 単体動作できるように依存モジュールとともに本ディレクトリへコピーしたものです。
> 詳細は `rtcm_compare/README.md` を参照してください。

## TMODE3 検証資料

基地局モード（TMODE3 Fixed Mode）での補正データ配信に先立ち、TMODE3 設定の参考情報を
確認するための簡易資料です。

| ファイル | 役割 |
|---|---|
| `check_tmode3_web.txt` | u-blox Portal（`portal.u-blox.com`）のページ取得結果（HTML スナップショット）。TMODE3 設定時の参考情報として保存されたもの（拡張子は `.txt` ですが中身は HTML）。 |

> これらは接続・確認用の使い捨て資料であり、基地局本体のロジック
> （`rtcm_compare/rtk_RTCM_Log2.py` など）には依存していません。

### NTRIP 接続確認スクリプト（構成A）の退避について

外部 NTRIP キャスター（イチミル `ntrip.ales-corp.co.jp:2101`）への接続可否を確認する
`check_ntrip.py` / `check_ntrip2.py` は、構成A（NTRIP/イチミル依存）のスクリプトとして
[`archive/legacy_ntrip_ichimill/`](../archive/legacy_ntrip_ichimill/README.md) へ退避済みです。

## 検証で確定した最終結論

### ✅ ZED-F9P は基地局モードで MSM7 出力に対応している

**「ZED-F9Pは基地局モードでMSM7を出力できない」という初期結論は誤りでした。**

実際の原因は、**設定を適用したポートとログを取得したポートの不一致**です。
ZED-F9P のメッセージ出力設定は**インターフェース（USB/UART1等）ごとに独立**しており、
初期検証では `_UART1` 向け設定のみを変更して、ログ取得元の USB ポート（`/dev/ttyACM2`）の
設定を変更していませんでした。`_USB` 向け設定キーを追加したところ、MSM7 の出力を実機確認できました。

### F9P と ichimill の MSM7 メッセージは完全一致

GPS(1077) / GLONASS(1087) / Galileo(1097) / QZSS(1117) / BeiDou(1127) の全 MSM7 と
Type 1006 が F9P から出力可能。ichimill との最大差異は Type 1033（受信機・アンテナ情報）のみ
で、RTK 測位には必須ではありません。

> 詳細な検証結果・技術知見は `rtcm_compare/README.md` および `rtcm_verification/README.md` を参照してください。

## 前提・注意

- ラズパイ上での実行を想定しています（本ディレクトリをラズパイへ展開して使用）。
- 実行には `pyserial` / `pyubx2` / `pyyaml` 等のライブラリが必要です。
- **ポート別設定キーの重要ポイント**: `_USB` 向け設定と `_UART1` 向け設定は独立しており、
  対象ポートの設定を必ず指定してください。

## 関連ディレクトリ（比較対象）

- `dronecan_gps_rtk/ichimill_sim/logs/` … ichimill 由来の RTCM ログ（比較対象）
- `dronecan_gps_rtk/ntrip_rtk_client/` … RTCM 解析・比較に使える `analyze_rtcm.py`
  （pyrtcm による Type 1006 座標抽出など）が含まれています。

## 更新履歴

- 2026-08-08: ディレクトリ新設（基地局モード検証用）
- 2026-09-27: NTRIP / TMODE3 検証用スクリプト（`check_ntrip.py` / `check_ntrip2.py` /
  `check_tmode3_web.txt`）をルート直下から本ディレクトリへ移動・整理
- 2026-09-27: 構成A（NTRIP/イチミル依存）の `check_ntrip.py` / `check_ntrip2.py` を
  `archive/legacy_ntrip_ichimill/` へ退避
