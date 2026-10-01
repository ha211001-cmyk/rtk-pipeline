# windows — Windows PC 向け F9P 運用スクリプト集

EVK-F9P（u-blox ZED-F9P GNSS レシーバー）を **Windows PC** から COM ポート（USB 接続）経由で
制御・データ取得するためのスクリプト集です。

基地局モード（TMODE3）の設定・RTCM 受信、NTRIP キャスター（基地局配信）、
測位精度の統計評価、PPK 用生観測値の記録、
設定の検証（Flash 永続化・ジオイド高・RTCM 1005 など）までをカバーします。

> イチミル（外部 NTRIP キャスター）を利用する RTK 測位スクリプト（`ichimile_log.py` /
> `ichimile_nolog.py`）は構成A（NTRIP/イチミル依存）のため
> [`archive/legacy_ntrip_ichimill/`](../archive/legacy_ntrip_ichimill/README.md) へ退避済みです。

## 背景・目的

本プロジェクト（EVK-F9P-1）では、ラズパイ上で基地局・移動局の検証を行ってきました
（`rtk_base_mavlink/`、`base_station_verify/` など参照）。一方で、現場での簡易確認や
デバッグには **Windows PC 単体** で完結できると便利な場面が多くあります。

本ディレクトリは、以下の目的で Windows PC 向けに用意したスクリプト群です。

- **基地局モードの設定と RTCM 受信**: F9P を TMODE3 Fixed Mode（既知点固定）に設定し、
  出力される RTCM3 補正データを受信・確認する。
- **NTRIP キャスターとしての配信**: F9P を基地局とし、RTCM3 補正データをローカルネットワークの
  ローバーへ NTRIP プロトコルで配信する。
- **測位精度の統計評価**: 位置データの標準偏差・最大誤差をリアルタイムで算出する。
- **PPK（後処理 RTK）用の生観測値記録**: UBX-RXM-RAWX / RXM-SFRBX を CSV に保存する。
- **設定の検証**: 電源再投入後の Flash 永続化、ジオイド高から楕円体高への変換、
  RTCM 1005（基準局座標）、TMODE3 の現在設定などを個別に確認する。

## ディレクトリ構成

```
windows/
├── README.md                  # このファイル
├── base_station.py            # 基地局モード設定 + RTCM3 受信（CFG-VALSET 方式 / Flash 永続化対応）
├── gps_display.py             # NMEA メッセージ表示（GGA/RMC/GSA/VTG/GSV/GLL）
├── gps_statistics.py          # 測位精度の統計評価（標準偏差・最大誤差、NTRIP 対応）
├── gps_statistics_debug.py    # 上記のデバッグ版（NTRIP 受信の詳細ログ付き）
├── ntrip_caster.py            # NTRIP キャスター（基地局サーバー、ローカル配信）
├── ppk_logger.py              # PPK 用 生観測値ロガー（RAWX/SFRBX/GGA を CSV 保存）
├── check_geoid.py             # GGA のジオイド分離量から楕円体高を計算
├── check_rtcm.py              # Flash 永続化後の RTCM 出力を確認（10秒間）
├── check_rtcm1005.py          # RTCM 1005（基準局座標）をデコードして表示
├── check_rtcm100              # check_rtcm1005.py とほぼ同内容（拡張子なしの単一ファイル）
├── check_tmode3.py            # TMODE3 の現在設定を CFG-VALGET で読み取り
├── reset_tmode3.py            # TMODE3 を Disabled にリセット（Rover モードへ戻す）
└── __pycache__/               # 自動生成キャッシュ（手動管理は不要）
```

### ファイル一覧と役割

#### 基地局モード系

| ファイル | 役割 |
|----------|------|
| `base_station.py` | F9P を TMODE3 Fixed Mode（既知点固定）に設定し、RTCM3（1005/1077/1087/1097/1127/1230）を有効化して受信・表示する。`pyubx2` の CFG-VALSET 方式で設定し、`SAVE_TO_FLASH=True` により RAM+FLASH 同時書き込み（電源 OFF 後も保持）に対応。LLH→ECEF 変換を Python 側で行い、`CFG_TMODE_POS_TYPE=ECEF` で設定する。 |
| `ntrip_caster.py` | F9P を基地局モードに設定し、RTCM3 をローカルネットワークへ NTRIP プロトコルで配信するキャスター。UBX/NMEA/RTCM3 が混在するバッファを解析し、CRC24Q 検証済みの RTCM フレームのみを配信。`CFG-CFG` による Flash 保存と CP932 対策を含む。 |
| `reset_tmode3.py` | TMODE3 を Disabled にリセットし、移動局（Rover）モードへ戻す（CFG-VALSET、RAM+FLASH）。 |
| `check_tmode3.py` | CFG-VALGET で TMODE3 の現在設定（モード・座標形式・座標値など）を読み取り表示する。 |

#### 移動局（ローバー）・RTK 測位系

| ファイル | 役割 |
|----------|------|
| `gps_statistics.py` | NMEA-GGA をリアルタイム取得し、平均位置をリファレンスとして標準偏差・最大誤差・RTK Fixed/Float 率を算出する。`RTK=1` でイチミル（NTRIP）に接続し補正データを流し込む。 |
| `gps_statistics_debug.py` | `gps_statistics.py` のデバッグ版。NTRIP 受信の詳細ログ（最初の受信バイト、0xD3 判定、HTTP ヘッダ解析など）を出力する。 |

#### 表示・統計系

| ファイル | 役割 |
|----------|------|
| `gps_display.py` | NMEA メッセージ（GGA/RMC/GSA/VTG/GSV/GLL）を解析して表示する。起動時に TMODE3 を Disabled にリセットして Rover モードを確保。コマンドライン引数でポート・ボーレートを変更可能。 |

#### PPK・検証系

| ファイル | 役割 |
|----------|------|
| `ppk_logger.py` | 後処理 RTK（PPK）用に UBX-RXM-RAWX / RXM-SFRBX / NMEA-GGA を CSV に保存するロガー。`--duration` / `--out` / `--port` / `--baud` / `--no-enable` などの引数に対応。CP932 対策を含む。 |
| `check_geoid.py` | NMEA GGA のジオイド分離量（`sep`）から楕円体高（`alt + sep`）を計算して表示する（30秒間）。 |
| `check_rtcm.py` | 電源入れ直し後、Flash 保存した設定が保持されているかを RTCM 出力で確認する（10秒間）。 |
| `check_rtcm1005.py` | RTCM 1005（基準局座標）をデコードして表示する（30秒間）。 |
| `check_rtcm100` | `check_rtcm1005.py` とほぼ同内容の単一ファイル（拡張子なし）。警告メッセージが日本語になっている。 |

> `check_rtcm100` は拡張子のない単一の Python ファイルです（`check_rtcm1005.py` の別名版）。
> 実行時は `python check_rtcm100` のように指定します。

## 依存ライブラリ

ルートの `requirements.txt` に記載されているライブラリを使用します。

```bash
pip install pyserial pynmeagps pyubx2 pyrtcm numpy
```

| ライブラリ | 用途 |
|-----------|------|
| `pyserial` | COM ポート（シリアル）通信 |
| `pynmeagps` | NMEA メッセージのパース |
| `pyubx2` | UBX メッセージの生成・パース（CFG-VALSET / CFG-VALGET など） |
| `pyrtcm` | RTCM3 メッセージのパース |
| `numpy` | 標準偏差などの統計計算（`gps_statistics.py` 等） |

## 実行方法

すべてのスクリプトは Windows PC 上で、EVK-F9P を USB 接続した状態で実行します。

```bash
# 仮想環境を使う場合（PowerShell）
.\.venv\Scripts\Activate.ps1

# 基地局モード設定 + RTCM3 受信（引数で実行秒数を指定、省略時は Ctrl+C まで）
python base_station.py 30

# NTRIP キャスター（ローカル配信）
python ntrip_caster.py

# 測位精度の統計評価
python gps_statistics.py

# PPK 用生観測値ロガー（例: 1800秒間、出力先を ./log に指定）
python ppk_logger.py --duration 1800 --out ./log

# NMEA 表示（ポート・ボーレートを引数で上書き可能）
python gps_display.py
python gps_display.py COM6 38400

# 検証系スクリプト
python check_geoid.py
python check_rtcm.py
python check_rtcm1005.py
python check_tmode3.py
python reset_tmode3.py
```

各スクリプトの COM ポートは **ファイル先頭の `COM_PORT` 定数** にハードコードされています。
自分の環境のポート番号（デバイスマネージャーで確認）に合わせて変更してから実行してください。

## 注意点

### COM ポート番号がファイルごとに異なる

| ポート | 該当ファイル |
|--------|-------------|
| `COM6` | `gps_statistics.py`, `gps_statistics_debug.py`, `ntrip_caster.py`, `ppk_logger.py` |
| `COM7` | `base_station.py`, `gps_display.py`, `check_geoid.py`, `check_rtcm.py`, `check_rtcm1005.py`, `check_rtcm100`, `check_tmode3.py`, `reset_tmode3.py` |

ボーレートはすべて `38400` です。実行前にデバイスマネージャーで COM 番号を確認し、
該当ファイルの `COM_PORT` を環境に合わせて書き換えてください。

### 基地局の固定座標がファイルごとに異なる

基地局モードで使用する既知点座標はファイルごとに異なります。用途に応じて正しい値を設定してください。

| ファイル | 緯度 | 経度 | 高度（楕円体高） |
|----------|------|------|------------------|
| `base_station.py` | 36.0751418 | 136.2133477 | 44.800 m |
| `ntrip_caster.py` | 36.070846 | 136.595280 | 1237.00 m |

### Flash 永続化対応

以下のスクリプトは設定を Flash（BBR）に保存するため、**電源 OFF 後も設定が保持されます**。

- `base_station.py`: `SAVE_TO_FLASH=True` の場合、CFG-VALSET の `layers=0x05`（RAM+FLASH）で書き込み。
- `ntrip_caster.py`: `CFG-CFG`（class=0x06, id=0x09）で `saveMask=0xFFFF` を保存。
- `reset_tmode3.py`: CFG-VALSET の `layers=0x05` で TMODE3 を Disabled に保存。

基地局モードの検証後は `reset_tmode3.py` を実行して Rover モードへ戻すことを推奨します。
（`gps_display.py` も起動時に TMODE3 をリセットします。）

### Windows CP932 対策

Windows のコンソールは既定で CP932 のため、UTF-8 の記号（✓ / ✗ / ⚠ など）を出力すると
`UnicodeEncodeError` になる場合があります。

`ntrip_caster.py` と `ppk_logger.py` では起動直後に

```python
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
```

で標準出力・標準エラーを UTF-8（置換あり）に切り替えて対処しています。
他のスクリプトで同様のエラーが出る場合は、上記の処理を先頭付近に追加するか、
ターミナルのコードページを UTF-8（`chcp 65001`）に切り替えてください。

### 認証情報・サーバー情報がハードコードされている

`gps_statistics.py`, `gps_statistics_debug.py` には
イチミル（`ntrip.ales-corp.co.jp:2101`）のマウントポイント・ユーザー名・パスワードが
ソースコード内に直接記述されています。リポジトリ管理や配布の際は取り扱いに注意してください。

> イチミル（NTRIP クライアント）専用の `ichimile_log.py` / `ichimile_nolog.py` は
> `archive/legacy_ntrip_ichimill/` へ退避済みです。

### その他

- USB 接続ではボーレート設定値は実質無視されます（通信は USB CDC で行われるため）。
- `__pycache__/` は自動生成されるキャッシュなので、コミット・手動編集は不要です。

## 更新履歴

- 2026-09-27: 初版作成。Windows PC 向けスクリプト群の全体概要を整理
- 2026-09-27: イチミル（NTRIP クライアント）スクリプト（`ichimile_log.py` / `ichimile_nolog.py`）を
  `archive/legacy_ntrip_ichimill/` へ退避し、本 README の記述を更新。

