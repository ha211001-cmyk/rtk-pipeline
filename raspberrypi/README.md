# raspberrypi — Raspberry Pi 5 向け実行スクリプト

u-blox ZED-F9P（rtk-pipeline）を Raspberry Pi 5 で動作させるための実行スクリプト集です。
F9P は USB 接続で **`/dev/ttyACM0`**（ボーレート `38400`）として認識されることを前提としており、
基地局モード・NTRIP クライアント/キャスター・NMEA 表示・GPS 統計・PPK ロギングまで、
RTK 測位に関わる一連の機能をカバーしています。

> Windows 向けの同等機能は `archive/windows/` ディレクトリにあります（COM ポート、`pyubx2` による
> Flash 永続化対応など）。本ディレクトリは Raspberry Pi 5 専用です。
>
> イチミル（外部 NTRIP キャスター）を利用する RTK 測位スクリプト（`ichimile_log.py` /
> `ichimile_nolog.py`）は構成A（NTRIP/イチミル依存）のため
> [`archive/legacy_ntrip_ichimill/`](../archive/legacy_ntrip_ichimill/README.md) へ退避済みです。

## 背景・目的

- Windows 版と同等の RTK 測位・基地局・PPK 機能を、Raspberry Pi 5 上で軽量に実行する。
- F9P を USB 接続（`/dev/ttyACM0`）した状態で、**引数なしですぐ動く**シンプルなスクリプト群を提供する。
- 基地局モード（TMODE3 Fixed Mode）で RTCM3 補正データを生成・配信し、ローバー側の RTK Fix を実現する。
- 後処理 RTK（PPK）用の生観測値（UBX-RXM-RAWX / RXM-SFRBX）を CSV に記録する。

## ディレクトリ構成

```
raspberrypi/
├── README.md                    # このファイル（全体概要）
├── setup.sh                     # セットアップスクリプト（依存導入・権限・log作成）
├── base_station.py              # 基地局モード設定 & RTCM3 受信・表示
├── gps_display.py               # NMEA メッセージ表示
├── gps_statistics.py            # GPS 位置の標準偏差・最大誤差の計算（RTK対応）
├── gps_statistics_debug.py      # 同上（NTRIP受信の詳細ログ付きデバッグ版）
├── ntrip_caster.py              # ローカル NTRIP キャスター（基地局配信）
├── ppk_logger.py                # PPK 用 生観測値 CSV ロガー
└── test/                        # テスト・検証スクリプト（PPK / NTRIP）
    ├── README.md                # test/ の説明
    ├── test_01_rawx_enable.py   # RXM-RAWX/SFRBX 有効化 & 受信確認
    ├── test_02_rawx_verify.py   # RAWX 内容の詳細検証
    ├── test_03_ppk_logger.py    # PPK 用 CSV ロガー（テスト版）
    ├── debug_rawx_attrs.py      # RAWX 属性ダンプ（デバッグ）
    ├── debug_rtcm_crc_compare.py# RTCM CRC 比較（デバッグ）
    ├── test_ntrip_sourcetable.py# NTRIP ソーステーブル取得
    └── test_ntrip_stream.py     # NTRIP ストリーム受信
```

### 各ファイルの役割

| ファイル | 役割 |
|---------|------|
| `setup.sh` | Python パッケージ（`pyserial`/`pynmeagps`/`pyubx2`/`pyrtcm`/`numpy`）の導入、`dialout` グループ追加、`log/` ディレクトリ作成、`/dev/ttyACM*` 検出 |
| `base_station.py` | F9P を TMODE3 Fixed Mode（既知点 `36.070846 / 136.595280 / 1237.00 m`）に設定し、RTCM3（1005/1077/1087/1097/1127/1230）を生成して受信・表示 |
| `gps_display.py` | NMEA（GGA/RMC/GSA/VTG/GSV/GLL）を解析して表示。`python3 gps_display.py [ポート] [ボーレート]` で引数指定可 |
| `gps_statistics.py` | NMEA-GGA の位置データを集計し、標準偏差・最大誤差を算出。`RTK=1` で NTRIP 補正を併用可能（終了時に結果表示） |
| `gps_statistics_debug.py` | `gps_statistics.py` のデバッグ版。NTRIP 受信バイト列の先頭ログなど詳細出力を追加 |
| `ntrip_caster.py` | F9P を基地局として、ローカルネットワークへ NTRIP で RTCM3 を配信（`2101` / `F9P_BASE` / 認証なし） |
| `ppk_logger.py` | UBX-RXM-RAWX / RXM-SFRBX を取得し、`ppk_raw_*.csv` / `ppk_nav_*.csv` / `ppk_pos_*.csv` に保存（本番用） |
| `test/` | PPK（RAWX 有効化→検証→ロギング）と NTRIP のテスト・検証スクリプト。詳細は `test/README.md` を参照 |

## 依存ライブラリ

```bash
pip3 install pyserial pynmeagps pyubx2 pyrtcm numpy
```

`setup.sh` を実行すれば、上記のインストールと `dialout` グループ追加まで自動で行えます。

| ライブラリ | 用途 |
|-----------|------|
| `pyserial` | F9P とのシリアル通信（`/dev/ttyACM0`） |
| `pynmeagps` | NMEA メッセージ解析（`gps_display.py` 等） |
| `pyubx2` | UBX メッセージ解析・設定（`ppk_logger.py`） |
| `pyrtcm` | RTCM3 フレーム解析（`base_station.py`） |
| `numpy` | 統計計算（`gps_statistics.py`） |

## 実行方法

### 1. 初回セットアップ

```bash
cd ~/rtk-pipeline/raspberrypi
chmod +x setup.sh
./setup.sh
```

> シリアルポート権限（`dialout` グループ）は追加後に**再ログイン**（または `newgrp dialout`）が必要です。

### 2. 各スクリプトの実行

```bash
cd ~/rtk-pipeline/raspberrypi

# NMEA 表示（単独測位の確認）
python3 gps_display.py

# 基地局モード（TMODE3 Fixed + RTCM3 生成・受信）
python3 base_station.py

# ローカル NTRIP キャスター（基地局を配信）
python3 ntrip_caster.py

# GPS 位置の標準偏差・最大誤差
python3 gps_statistics.py
python3 gps_statistics_debug.py

# PPK 用 生観測値ロガー
python3 ppk_logger.py --duration 1800
python3 ppk_logger.py --out ./log
```

いずれも無限ループで動作するため、停止は `Ctrl+C` で行います。
`ppk_logger.py` のみ `--duration` 秒で自動終了できます。

### 3. テスト（PPK / NTRIP）

```bash
cd ~/rtk-pipeline/raspberrypi/test

# PPK Step 1: RXM-RAWX/SFRBX 有効化 & 受信確認
python3 test_01_rawx_enable.py

# PPK Step 2: RAWX 内容の詳細検証
python3 test_02_rawx_verify.py --count 5

# PPK Step 3: PPK 用 CSV ロガー
python3 test_03_ppk_logger.py --duration 300
```

## 注意点

- **対象デバイスは `/dev/ttyACM0`（ボーレート `38400`）です。** F9P を USB 接続した際の標準的な
  デバイスパスで、各スクリプトの冒頭に `SERIAL_PORT = "/dev/ttyACM0"` とハードコードされています。
  USB-シリアル変換アダプタ経由の場合は `/dev/ttyUSB0` などに変更してください。
- 接続ポートの確認・権限付与:

  ```bash
  ls /dev/ttyACM*       # または ls /dev/ttyUSB*
  sudo usermod -aG dialout $USER
  ```

- **基地局モード（TMODE3 Fixed Mode）の注意点**（`base_station.py` / `ntrip_caster.py` 共通）:
  - TMODE3 payload は **40 bytes 必須**（32 bytes だと NAK される）。
  - 設定は `Disabled(mode=0)` → `Fixed(mode=2)` の **2 ステップ**で行う。
  - モード切替には **3 秒程度の安定待ち**が必要。
  - 設定は **CFG-CFG で Flash 保存**すること（RAM のみだと接続切断後に MSG 1005 が出なくなる）。
- **NTRIP ポート 2101 のブロック**: `ntrip.ales-corp.co.jp:2101` など外部 NTRIP への接続は
  ネットワーク環境によってタイムアウトする場合があります。その場合は `ntrip_caster.py` による
  **ローカル NTRIP キャスター**（`<Raspberry Pi の IP>:2101 / F9P_BASE`、認証不要）を利用してください。
- **認証情報はハードコードされています。** `gps_statistics.py` などに
  イチミルのユーザー名・パスワードが直接記述されているため、公開リポジトリへの流出に注意してください。
- `ppk_logger.py` / `test_03_ppk_logger.py` は実行前に RXM-RAWX / RXM-SFRBX の出力を有効化
  （`test_01_rawx_enable.py`）しておく必要があります。設定は RAM のみで、電源断でリセットされます。

## 動作確認状況（2026-09-25 時点）

| 機能 | 状態 |
|------|------|
| 単独測位（`gps_display.py`） | ✅ 動作確認済み（DGPS Fix / 衛星12 / HDOP 0.57） |
| RTCM3 基地局（`base_station.py`） | ✅ 動作確認済み（MSG 1005/1077/1087/1097/1127/1230 全出力） |
| NTRIP キャスター（`ntrip_caster.py`） | ✅ 動作確認済み（`172.20.10.2:2101` でローカル配信成功） |
| NTRIP（イチミル:2101） | ⚠ ポートブロック中（ラズパイ・Windows 両方でタイムアウト） |

## 更新履歴

- 2026-09-27: `raspberrypi/README.md` を新規作成（全体概要・ファイル一覧・実行方法・注意点）
- 2026-09-27: イチミル（NTRIP クライアント）スクリプト（`ichimile_log.py` / `ichimile_nolog.py`）を
  `archive/legacy_ntrip_ichimill/` へ退避し、本 README の記述を更新。
