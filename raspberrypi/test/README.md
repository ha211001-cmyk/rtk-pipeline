# test/ ディレクトリ

このディレクトリには EVK-F9P の各種テスト・検証スクリプトが入っています。

## PPK (後処理RTK) テスト

後処理RTK (Post-Processing Kinematic) は、リアルタイムに補正信号を受けるのではなく、
生の GNSS 観測値を記録しておき、後からソフトウェア (RTKLIB 等) で精密測位処理を行う手法。

### 実行順序

```
Step 1: test_01_rawx_enable.py   — RXM-RAWX/SFRBX 有効化 & 受信確認
Step 2: test_02_rawx_verify.py   — 受信した RAWX の内容詳細検証
Step 3: test_03_ppk_logger.py    — PPK 用 CSV ロガー (本命)
```

### 各スクリプトの概要

| スクリプト | 目的 |
|-----------|------|
| `test_01_rawx_enable.py` | F9P に CFG-VALSET で `UBX-RXM-RAWX` / `UBX-RXM-SFRBX` を有効化し、受信を確認する |
| `test_02_rawx_verify.py` | 受信した RAWX の衛星別データ (疑似距離・搬送波位相・ドップラー・CNR) を詳細表示して健全性を検証する |
| `test_03_ppk_logger.py`  | RAWX データを CSV に記録。`ppk_raw_*.csv` が RTKLIB のインプットになる |

### 使い方

```bash
# Step 1: 有効化確認
python3 test_01_rawx_enable.py

# Step 1: BBR に保存する場合 (電源断後も設定維持)
python3 test_01_rawx_enable.py --save

# Step 2: 詳細検証 (5エポック)
python3 test_02_rawx_verify.py --count 5

# Step 3: 5分間ログ
python3 test_03_ppk_logger.py --duration 300

# Step 3: 無制限ログ (Ctrl+C で停止)
python3 test_03_ppk_logger.py
```

### CSV 出力フォーマット (ppk_raw_*.csv)

| カラム | 説明 |
|-------|------|
| tow_s | GPS 受信時刻 (GPS 週内秒) |
| week | GPS 週番号 |
| leap_s | GPS-UTC 閏秒 |
| gnss | 衛星システム (GPS/Galileo/GLONASS/BeiDou 等) |
| sv_id | 衛星番号 |
| sig_id | 信号番号 |
| freq_id | 周波数 ID (GLONASS 用) |
| pseudorange_m | 疑似距離 [m] |
| carrier_phase_cyc | 搬送波位相 [cycles] |
| doppler_hz | ドップラー周波数 [Hz] |
| cno_dbhz | C/N0 (搬送波対雑音比) [dBHz] |
| lock_time_ms | ロック継続時間 [ms] |
| pr_stdev_raw | F9P生の疑似距離標準偏差コード |
| cp_stdev_raw | F9P生の搬送波位相標準偏差コード |
| do_stdev_raw | F9P生のドップラー標準偏差コード |
| pr_valid | 疑似距離有効フラグ |
| cp_valid | 搬送波位相有効フラグ (PPK に必須) |
| half_cyc_valid | ハーフサイクル有効フラグ |
| recv_utc | ラズパイ受信時刻 (参照用) |

### PPK 後処理ワークフロー

1. **移動局データ収集**: `test_03_ppk_logger.py` で `ppk_raw_*.csv` を取得
2. **基準局データ入手**: 国土地理院の電子基準点データ (RINEX) や自作基地局の観測値を使用
3. **後処理ソフトで演算**: RTKLIB (`rnx2rtkp` / RTKPOST) で cm 精度の軌跡を取得

## NTRIP テスト (既存)

| スクリプト | 目的 |
|-----------|------|
| `test_ntrip_sourcetable.py` | ローカル NTRIP キャスター (127.0.0.1:2101) のソーステーブルを取得 |
| `test_ntrip_stream.py` | NTRIP ストリームの受信テスト |
