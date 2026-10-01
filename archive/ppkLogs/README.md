# ppkLogs — PPK 後処理 RTK 用 生観測値ロギングデータ保存先

PPK（Post-Processing Kinematic / 後処理 RTK）用の生観測値ロギングデータと、
その解析結果・解析スクリプトをまとめて保存するディレクトリです。

リアルタイムで補正信号を受ける RTK と異なり、PPK では F9P から出力される
生の GNSS 観測値（UBX-RXM-RAWX / RXM-SFRBX）をいったん記録しておき、
後から RTKLIB 等のソフトウェアで精密測位処理を行います。
本ディレクトリは、その「記録した生観測値」と「後処理の解析結果」を保管する場所です。

## 背景・目的

- 移動局（ローバー）側の F9P から **UBX-RXM-RAWX（生観測値）** と
  **UBX-RXM-SFRBX（航法フレーム）** を取得し、CSV へ保存する。
- 同時に **NMEA-GGA（参照位置）** を記録し、後処理で得られる精密軌跡の
  妥当性確認や、観測データの品質評価に使う。
- 記録した CSV を解析スクリプト（`script/analyze_ppk_logs.py`）で読み込み、
  衛星数・HDOP・Fix 品質などの品質レポートとグラフを `result/` に出力する。

## ディレクトリ構成

```
ppkLogs/
├── README.md                       # このファイル（全体概要）
├── data/                           # 生観測値ロギングデータ（CSV）
│   ├── ppk_raw_YYYYMMDD_HHMMSS.csv # 生観測値（UBX-RXM-RAWX）
│   ├── ppk_nav_YYYYMMDD_HHMMSS.csv # 航法フレーム統計（UBX-RXM-SFRBX）
│   └── ppk_pos_YYYYMMDD_HHMMSS.csv # 参照位置（NMEA-GGA）
├── result/                         # 解析結果（script が出力）
│   ├── ppk_quality_report.json     # 品質評価レポート（JSON）
│   ├── ppk_quality_report.txt      # 品質評価レポート（テキスト）
│   ├── ppk_summary_plots.png       # 品質サマリのグラフ
│   └── ppk_timeseries_summary.csv  # 時系列サマリ（1秒毎にリサンプル）
└── script/                         # 解析スクリプト
    └── analyze_ppk_logs.py         # data/ を読み込み result/ に品質レポートを出力
```

### data/ — 生観測値ロギングデータ

`raspberrypi/ppk_logger.py` / `windows/ppk_logger.py`（後述）が記録する
3 種類の CSV を保存します。ファイル名末尾は取得日時のタイムスタンプです。

| ファイル | 元メッセージ | 内容 |
|---------|------------|------|
| `ppk_raw_*.csv` | `UBX-RXM-RAWX` | 疑似距離・搬送波位相・ドップラー・CNR などの生観測値。**PPK 演算の本体** |
| `ppk_nav_*.csv` | `UBX-RXM-SFRBX` | 航法フレーム（衛星軌道情報）の受信統計 |
| `ppk_pos_*.csv` | `NMEA-GGA` | 参照位置（緯度・経度・高度・Fix 品質・衛星数・HDOP） |

`ppk_raw_*.csv` の主なカラム（詳細は `raspberrypi/test/README.md` 参照）：

| カラム | 説明 |
|-------|------|
| `tow_s` / `week` / `leap_s` | GPS 受信時刻（週内秒 / 週番号 / 閏秒） |
| `gnss` / `sv_id` / `sig_id` / `freq_id` | 衛星システム / 衛星番号 / 信号番号 / 周波数 ID |
| `pseudorange_m` / `carrier_phase_cyc` / `doppler_hz` | 疑似距離 [m] / 搬送波位相 [cycles] / ドップラー [Hz] |
| `cno_dbhz` / `lock_time_ms` | C/N0 [dBHz] / ロック継続時間 [ms] |
| `pr_valid` / `cp_valid` / `half_cyc_valid` | 各観測値の有効フラグ（`cp_valid` は PPK に必須） |
| `recv_utc` | 記録側の受信時刻（参照用） |

### result/ — 解析結果

`script/analyze_ppk_logs.py` が出力する品質評価の結果一式です。
`data/` のログを読み込み、以下の 4 ファイルを生成します。

| ファイル | 内容 |
|---------|------|
| `ppk_quality_report.json` | 位置品質・衛星品質・総合評価を JSON 形式で保存 |
| `ppk_quality_report.txt` | 上記を人間が読みやすいテキスト形式で保存 |
| `ppk_summary_plots.png` | 衛星数の推移 / HDOP・Fix 品質 / 緯度経度散布 / GNSS 別衛星数 のグラフ |
| `ppk_timeseries_summary.csv` | POS/RAW/NAV を 1 秒毎にリサンプルした時系列サマリ |

### script/ — 解析スクリプト

| スクリプト | 役割 |
|-----------|------|
| `analyze_ppk_logs.py` | `data/` の 3 種類の CSV を読み込み、品質評価とグラフを `result/` に出力 |

> 注意: 現在の `analyze_ppk_logs.py` は解析対象のファイル名（`ppk_*_20260314_144809.csv`）を
> ハードコードしています。別のログを解析する場合は、スクリプト内の
> `NAV_FILE` / `POS_FILE` / `RAW_FILE` を対象のファイル名に書き換えてください。

## 関連ツール（ロギング側）

生観測値 CSV を記録する本番スクリプトは、実行環境ごとに用意されています。
記録した CSV を本ディレクトリの `data/` へ格納する運用です。

| ツール | 実行環境 | 説明 |
|--------|---------|------|
| `raspberrypi/ppk_logger.py` | ラズパイ（Linux） | 本番用ロガー。既定 `/dev/ttyACM0` @ 38400 bps |
| `windows/ppk_logger.py` | Windows | 上記の Windows 対応版。既定 `COM6` @ 38400 bps |
| `raspberrypi/test/test_03_ppk_logger.py` | ラズパイ（Linux） | テスト用ロガー（`raspberrypi/test/README.md` 参照） |

いずれも F9P に対して `CFG-MSGOUT-UBX-RXM-RAWX` / `CFG-MSGOUT-UBX-RXM-SFRBX` を
有効化し、`ppk_raw_*.csv` / `ppk_nav_*.csv` / `ppk_pos_*.csv` の 3 ファイルを出力します。

## PPK 後処理ワークフロー

1. **移動局データ収集**: `raspberrypi/ppk_logger.py` または `windows/ppk_logger.py` で
   `ppk_raw_*.csv` などを取得し、本ディレクトリの `data/` に置く。
2. **基準局データ入手**: 国土地理院の電子基準点データ（RINEX）や自作基地局の観測値を用意する。
3. **後処理ソフトで演算**: RTKLIB（`rnx2rtkp` / RTKPOST）などで cm 精度の軌跡を求める。
4. **品質確認**: `script/analyze_ppk_logs.py` で取得ログの品質を確認し、`result/` に結果を残す。

## 更新履歴

- 2026-03-14: ディレクトリ新設（PPK 生観測値ログの保存・解析用）
- 2026-09-27: 本 README を作成（ディレクトリ構成・関連ツールの説明を追記）
