# ichimill_log — イチミル NTRIP RTCM ログ取得ディレクトリ

イチミル（`ntrip.ales-corp.co.jp`）の NTRIP Caster から RTCM3 補正データを受信し、
USB 直結した ZED-F9P（rtk-pipeline）へ注入しながら、F9P が出力する NMEA GGA を解析して
RTK Float / Fixed 状態を表示・記録するためのディレクトリです。

本ディレクトリの `ichimile_log.py` は **macOS 対応版**です。同名のスクリプトが
`raspberrypi/` と `windows/` にも存在します（目的は共通、実行環境ごとの別版）。
詳細は「関連ファイル」を参照してください。

## 背景・目的

- イチミル（全国基準局ネットワーク）が NTRIP 配信する RTCM3 補正データを、USB 直結の
  F9P に流し込んで RTK 測位が成立するかを検証する。
- F9P の NMEA GGA を解析し、RTK Float / Fixed への遷移をコンソール表示するとともに CSV に記録する。
- NTRIP から受信した RTCM3 フレームをそのままバイナリログ（`.rtcm3`）として保存し、
  後段の解析・比較（`base_station_verify/rtcm_verification/` 等）に利用できるようにする。

## ディレクトリ構成

```
ichimill_log/
├── README.md            # このファイル
├── ichimile_log.py      # イチミル NTRIP → F9P 注入・RTK 状態表示/記録（macOS 版）
└── log/                 # ログ出力先（git 管理外 / .gitignore の log/ 対象）
    ├── gpslog_YYYYMMDD_HHMMSS.csv    # GGA 解析結果（CSV）
    └── rtcm_YYYYMMDD_HHMMSS.rtcm3    # NTRIP 受信 RTCM3 生データ
```

> `log/` はスクリプト実行時に自動作成されます（`.gitignore` に `log/` が含まれており、
> 出力物は git 管理の対象外です）。

## 依存ライブラリ

`ichimile_log.py` は標準ライブラリに加えて以下の外部ライブラリを使用します。

```bash
pip install pyserial pyubx2
```

| ライブラリ | 用途 |
|-----------|------|
| `pyserial` | F9P とのシリアル通信（`serial.Serial`） |
| `pyubx2`   | UBX 設定メッセージ生成（`UBXMessage.config_set`）による Rover 設定 |

## 実行方法

F9P を Mac に USB 接続した状態で実行します。シリアルポートは省略時に自動検出
（`/dev/cu.usbmodem*` → `/dev/tty.usbmodem*` → `/dev/ttyACM*` → `/dev/ttyUSB*` の順）します。

```bash
# 自動検出して実行（RTK Fixed 到達で自動終了 / 上限 600 秒）
python3 ichimile_log.py

# ポートと最大実行秒数を明示指定
python3 ichimile_log.py --port /dev/cu.usbmodem112301 --max-duration 600
```

### コマンドライン引数

| 引数 | デフォルト | 説明 |
|------|-----------|------|
| `--port` | 自動検出 | F9P のシリアルポート |
| `--baudrate` | `38400` | F9P のボーレート |
| `--mountpoint` | `RTCM32MSM7` | NTRIP マウントポイント（繋がらない場合は `RTCM31` 等へ変更） |
| `--max-duration` | `600` | RTK Fixed 未達時の最大実行秒数 |
| `--post-fix-duration` | `10` | RTK Fixed 到達後に安定解を記録する追加秒数 |

### 停止

`Ctrl+C` で停止できます。停止時に RTCM 受信統計と保存ファイルパスが表示されます。

## 接続情報

`ichimile_log.py` 冒頭にイチミルの接続情報が定義されています。

| 項目 | 値 |
|------|-----|
| NTRIP Caster | `ntrip.ales-corp.co.jp` |
| ポート | `2101` |
| マウントポイント | `RTCM32MSM7`（F9P 推奨） |
| ボーレート | `38400` |

## 動作フロー

1. **シリアルポート検出・オープン** - F9P を検出して接続。
2. **Rover モード設定** - TMODE3 解除、NMEA GGA/RMC 出力有効化、USB からの RTCM3 入力許可。
3. **NTRIP 接続** - Basic 認証でマウントポイントをリクエスト（`200 OK` 受信で RTCM 配信待機）。
4. **受信スレッド** - NTRIP から RTCM3 を受信し、F9P へ即時注入すると同時に `.rtcm3` ログへ保存。
5. **送信スレッド** - F9P の NMEA GGA を解析し、状態表示・CSV 記録。VRS 用に GGA を 5 秒間隔で NTRIP へ送信。
6. **終了判定** - RTK Fixed 到達後 `--post-fix-duration` 秒で自動終了、または `--max-duration` で上限終了。

## 出力先（log/）

実行するとスクリプトと同じディレクトリの `log/` に、実行開始時刻を基にしたファイル名で
以下のログが出力されます。

| 出力ファイル | 内容 |
|-------------|------|
| `log/gpslog_YYYYMMDD_HHMMSS.csv` | GGA 解析結果（`timestamp, lat, lon, alt_m, quality, status`） |
| `log/rtcm_YYYYMMDD_HHMMSS.rtcm3`  | NTRIP から受信した RTCM3 フレームの生バイナリ |

- CSV の `quality` は GGA の測位品質（`0`: No Fix / `1`: GPS Fix / `2`: DGPS / `4`: RTK Fixed / `5`: RTK Float）。
- 終了時に受信した RTCM メッセージタイプの内訳（`1005/1006/1077/1087/1097/1117/1127/1230` 等）が表示されます。

## 関連ファイル（同名スクリプトのプラットフォーム別版について）

`ichimile_log.py` と同名のスクリプトが `raspberrypi/` と `windows/` にも存在します。
いずれも「イチミル NTRIP から RTCM を受信して F9P へ注入し、RTK 状態を表示・記録する」
という目的は共通ですが、実行環境ごとにシリアルポートの扱いや使用ライブラリが異なります。

| パス | 対応環境 | 主な違い |
|------|---------|---------|
| `ichimill_log/ichimile_log.py` | macOS | 本ディレクトリ。`pyserial` + `pyubx2` のみで完結。ポート自動検出（`/dev/cu.usbmodem*` 等） |
| `raspberrypi/ichimile_log.py` | Raspberry Pi 5 | シリアルポートは `/dev/ttyACM0` 固定。`pynmeagps` / `numpy` を併用 |
| `windows/ichimile_log.py` | Windows | シリアルポートは `COM6`。`pynmeagps` / `numpy` / `struct` を併用 |

> 使い分けは **実行するマシンの OS** に応じます。Mac で検証する場合は本ディレクトリの
> `ichimile_log.py` を使用し、ラズパイ / Windows で動かす場合はそれぞれのディレクトリの
> 同名ファイルを使用してください。

## 更新履歴

- 2026-09-09: `ichimile_log.py`（macOS 対応版）新規作成
- 2026-09-27: `README.md` 新規作成
