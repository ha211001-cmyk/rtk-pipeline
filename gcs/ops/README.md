# 運用スクリプト — RTK-GNSS 実行入口

**RTK-GNSS の運用時に実行するのは、このディレクトリのスクリプトだけです。**
`gcs/rtk_tools/*.py` などの実体を直接叩かず、必ずここにあるラッパーを使ってください。
各ラッパーは「リポジトリ直下へ移動」→「仮想環境の有効化」→「実体の起動」を行い、
**追加のコマンドライン引数はそのまま実体へ透過**します。

---

## 1. 実行一覧

| # | スクリプト | 実行ホスト | 役割 | 実体 |
|---|---|---|---|---|
| 1 | `1_start_base_station.sh` | Mac | 基地局 F9P を TMODE3 Fixed に設定し、RTCM3 を TCP:2101 で配信 | `gcs/rtk_tools/rtk_base_station_v2.py` |
| 2 | `2_start_web_gcs.sh` | Mac | Web GCS ダッシュボード（HTTP 9000 / MAVLink UDP 14550） | `gcs/server.py` → `gcs.app.server:app` |
| 3 | `3_start_mavlink_bridge.sh` | Raspberry Pi 5 | TCP:2101 から RTCM を受信し、Pixhawk へ `GPS_RTCM_DATA` として注入 | `gcs/rtk_tools/mavlink_bridge.py` |
| 4 | `4_measure_base_position.sh` | Mac | 基地局アンテナ移動時に現在地（楕円体高 HAE）を実測 | `single_unit_test/run_survey.py` |
| 5 | `5_check_rtcm_link.sh` | Mac | 基地局 TCP:2101 の疎通と RTCM3 フレームを確認 | `gcs/rtk_tools/verify_rtcm_tcp.py` |
| 6 | `6_analyze_logs.sh` | Mac | 取得済み CSV から FIXED 維持率・TTFF 等を集計 | `gcs/analyze_fix_log.py` |

---

## 2. 標準の起動順

**ターミナル A（Mac）— 基地局**
```bash
cd ~/rtk-pipeline-local
bash gcs/ops/1_start_base_station.sh
```
確認: `TCP server started on 0.0.0.0:2101`

**ターミナル B（Mac）— Web GCS**
```bash
cd ~/rtk-pipeline-local
bash gcs/ops/2_start_web_gcs.sh
```
ブラウザで `http://localhost:9000` を開き、右上の Connect を押します。

**Raspberry Pi 5（SSH）— 中継・注入**
```bash
ssh taki@192.168.2.4
cd ~/rtk-pipeline
bash gcs/ops/3_start_mavlink_bridge.sh
```

**疎通確認（任意・Mac）**
```bash
bash gcs/ops/5_check_rtcm_link.sh
```

---

## 3. 環境変数による上書き

| 変数 | 既定値 | 用途 | 使用スクリプト |
|---|---|---|---|
| `RTK_BASE_CONFIG` | `gcs/config/base_station.json` | 基地局設定 JSON | 1 |
| `RTK_SERIAL_PORT` | （JSON の値） | 基地局 F9P のシリアルポート | 1 |
| `GCS_PORT` | `9000` | Web GCS の待受ポート | 2 |
| `RTK_SERIAL` | `/dev/ttyAMA0` | Pixhawk の UART | 3 |
| `RTK_BAUD` | `921600` | Pixhawk のボーレート | 3 |
| `GCS_HOST_IP` | `192.168.2.1` | MAVLink 送出先（Mac） | 3 |
| `RTK_BASE_IP` | `192.168.2.1` | 基地局 TCP ホスト | 3 / 5 |
| `RTK_TCP_PORT` | `2101` | 基地局 TCP ポート | 5 |
| `RTK_CHECK_SECONDS` | `30` | 疎通確認の計測秒数 | 5 |

例:
```bash
GCS_PORT=9000 RTK_BASE_IP=192.168.2.1 bash gcs/ops/2_start_web_gcs.sh
```

---

## 4. ここに無いもの（実行しない）

以下は**今回の RTK-GNSS 運用では実行しません**。過去の実験・検証資産です。

- `gcs/_retired/` — 退避済み GUI（PyQt5 / Tkinter / 旧 fix 監視）
- `gcs/relpos/` `gcs/ekf_failsafe/` `gcs/flight_test/` `gcs/hw_verify/` — 実験・検証コード
- `gcs/rtk_tools/rtk_forwarder_service.py` `gcs/rtk_tools/tcp2serial.py` `gcs/deploy/` — 別構成の注入サービス（systemd 常駐）
- `gcs/**/test_*.py` — 単体テスト（`python3 -m unittest discover -t . -s gcs -p 'test_*.py'` で実行）

> **重要**: `3_start_mavlink_bridge.sh` の実体は、CSV / `.rtcm3` の書き出し処理が
> 現在コメントアウトされています（起動バナーは `Logging Disabled`）。ログファイルは生成されません。
> 詳細は [`../docs/rtk/README.md`](../docs/rtk/README.md) §7 を参照してください。

---

## 5. 関連文書

| 文書 | 内容 |
|---|---|
| [`../../STARTUP_GUIDE.md`](../../STARTUP_GUIDE.md) | 起動手順の全体（ネットワーク構成図つき） |
| [`../docs/RTK_PROCEDURES_MANUAL.md`](../docs/RTK_PROCEDURES_MANUAL.md) | RTK 手順書 |
| [`../docs/rtk/README.md`](../docs/rtk/README.md) | RTK 資料索引 |
| [`../README.md`](../README.md) | パッケージ概要 |
| [`../../README.md`](../../README.md) | リポジトリ全体の README |
