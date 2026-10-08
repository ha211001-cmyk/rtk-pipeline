# Raspberry Pi 5（機体側中継・RTCM 注入）

機体に搭載した **Raspberry Pi 5** の役割（MAVLink 中継・RTCM 注入・ロギング）と、
その実装 [`../../../../rtk_tools/mavlink_bridge.py`](../../../../rtk_tools/mavlink_bridge.py)
の仕様をまとめます。

- 索引: [`../../README.md`](../../README.md)
- 手順書: [`../../../RTK_PROCEDURES_MANUAL.md`](../../../RTK_PROCEDURES_MANUAL.md) §2 Step 3
- 受信側: [`../pixhawk_ardupilot/README.md`](../pixhawk_ardupilot/README.md)

> **出典ポリシー**: 本資料は `gcs/` パッケージ内のみを出典とします。

---

## 1. 役割と接続

| 項目 | 内容 |
|---|---|
| Pixhawk 接続 | `/dev/ttyAMA0` @ 921600 bps（**RTS/CTS 有効**） |
| GCS 接続 | Mac（`192.168.2.1`）へ **UDP:14550** で送受信 |
| 補正の受信 | Mac の基地局 **TCP:2101** から RTCM3 を受信 |
| 補正の注入 | **MAVLink `GPS_RTCM_DATA`** で Pixhawk へ送出 |
| Python 環境 | `~/Mavlink_venv`（`pymavlink` / `pyserial`） |

```text
[Pixhawk /dev/ttyAMA0] ⇄ (MAVLink) ⇄ [mavlink_bridge.py]
                                          ├─→ UDP:14550 → [Mac GCS]
                                          └─← TCP:2101 ← [Mac 基地局]
```

出典: [`../../../../rtk_tools/mavlink_bridge.py`](../../../../rtk_tools/mavlink_bridge.py)
の docstring / argparse 既定値、
[`../../../RTK_PROCEDURES_MANUAL.md`](../../../RTK_PROCEDURES_MANUAL.md) §1。

---

## 2. 実行

```bash
cd ~/rtk-pipeline-local
~/Mavlink_venv/bin/python3 gcs/rtk_tools/mavlink_bridge.py \
    --serial /dev/ttyAMA0 --baud 921600
```

- ターゲットホストの既定は **`192.168.2.1`** です（明示するなら `--target-host 192.168.2.1`）。
- **`pymavlink` / `pyserial` は `~/Mavlink_venv/` 配下**にあるため、
  必ず `~/Mavlink_venv/bin/python3` を使用します。

出典: [`../../../RTK_PROCEDURES_MANUAL.md`](../../../RTK_PROCEDURES_MANUAL.md) §2 Step 3
および §6（`ModuleNotFoundError` の項）。

### 2.1 CLI オプション

| オプション | 既定値 | 意味 |
|---|---|---|
| `--serial` | `/dev/ttyAMA0` | Pixhawk UART ポート |
| `--baud` | `921600` | ボーレート |
| `--rtscts` | （既定 True） | RTS/CTS ハードウェアフロー制御を有効化 |
| `--no-rtscts` | — | RTS/CTS を無効化 |
| `--target-host` | `192.168.2.1` | Mac GCS の IP（UDP 送信先） |
| `--target-port` | `14550` | GCS の UDP ポート |
| `--rtcm-host` | `192.168.2.1` | 基地局 TCP ホスト |
| `--rtcm-port` | `2101` | 基地局 TCP ポート |
| `--log-dir` | `logs` | `.rtcm3` / `.csv` の保存先 |
| `--auto-fix-fs` | — | `FS_GCS_ENABLE` が 1 の場合に自動で 0 に設定 |

出典: [`../../../../rtk_tools/mavlink_bridge.py`](../../../../rtk_tools/mavlink_bridge.py) の
`main()` argparse 定義。

> ⚠️ **ポート名**: Raspberry Pi 5 のピンヘッダ UART は **`/dev/ttyAMA0`** です
> （`/dev/serial0` ではありません）。開けない場合は `sudo raspi-config` で
> シリアルコンソールを無効化してください。
> 出典: [`../../../RTK_PROCEDURES_MANUAL.md`](../../../RTK_PROCEDURES_MANUAL.md) §6。

---

## 3. 内部構成（3 スレッド）

| スレッド | 関数 | 処理 |
|---|---|---|
| 1 | `serial_to_udp()` | Pixhawk → Mac GCS への転送。MAVLink を逐次パースし `PARAM_VALUE` を監視 |
| 2 | `udp_to_serial()` | Mac GCS → Pixhawk への転送（`serial_lock` で排他） |
| 3 | `rtcm_tcp_to_mavlink()` | 基地局 TCP → RTCM3 抽出 → `GPS_RTCM_DATA` へ分割エンコード → 送出 |

出典: 同上の各関数。

### 3.1 RTCM3 フレームの抽出

`extract_rtcm_frames()` が TCP ストリームから RTCM3 フレームを取り出します。

| 検査 | 内容 |
|---|---|
| 同期バイト | 先頭が `0xD3` |
| 予約ビット | `(buf[1] >> 2) == 0` |
| 長さ | `((buf[1] & 0x03) << 8) \| buf[2]`、**1023 バイト以下** |
| フレーム長 | `6 + frame_len`（ヘッダ 3 ＋ CRC 3） |

出典: 同上の `extract_rtcm_frames()`。

### 3.2 `GPS_RTCM_DATA` への分割

MAVLink の `GPS_RTCM_DATA` は 1 メッセージで運べる RTCM が限られるため、
**180 バイト単位**に分割して送ります。

| 定数 | 値 |
|---|---|
| `MAX_SIZE` | `180` |
| `MAX_FRAGS` | `4` |
| `flags` | `(seq << 3) \| 0`（フラグメント番号を上位に持たせる） |

出典: 同上の `rtcm_tcp_to_mavlink()`。

> **重要**: ArduPilot への `GPS_RTCM_DATA` 注入には **MAVLink 2.0 が必須**です。
> 実装冒頭で `os.environ["MAVLINK20"] = "1"` が設定されています。
> また 921600 bps の高速シリアルでは **RTS/CTS が不可欠**です。
> 出典: [`../../../RTK_PROCEDURES_MANUAL.md`](../../../RTK_PROCEDURES_MANUAL.md) §6。

---

## 4. 起動時のフェイルセーフ安全チェック

ブリッジは起動 1 秒後に **`FS_GCS_ENABLE` を自動照会**し、値を確認します。

| 値 | 表示 | 意味 |
|---|---|---|
| `0` | 🛡️ `[SAFETY CHECK] FS_GCS_ENABLE = 0 (OK: 通信断でもプロポ操縦を維持)` | 通信断でも RTL/Land しない |
| それ以外 | ⚠️ `[SAFETY WARNING] FS_GCS_ENABLE = <値>! 通信断でRTL/着陸が発動します。` | 警告 |

`--auto-fix-fs` を付けると、値が `0` でない場合に **`PARAM_SET` で 0 に自動変更**します。

出典: [`../../../../rtk_tools/mavlink_bridge.py`](../../../../rtk_tools/mavlink_bridge.py) の
`serial_to_udp()` 内 `fs_checked` ブロック、`--auto-fix-fs` の定義。

> ⚠️ **`ekf_failsafe` の golden との関係**: ArduPilot パラメータ golden では
> `FS_GCS_ENABLE = 1`（GCS 喪失時 Always RTL）が既定です
> （[`../../common/fix_conditions.md`](../../common/fix_conditions.md) §5.2）。
> **実験中に一時的に `0` にする**運用と、**飛行時の golden（1）**を混同しないでください。
> この安全チェックは「地上実験で通信断により意図せず RTL しないようにする」ための補助です。

---

## 5. 終了時の精度サマリー自動集計

`Ctrl + C` で終了すると、`print_statistics()` が CSV を解析してサマリーを出力します。

```text
==================================================================
 📊 実験ロギング & 位置精度解析サマリー
==================================================================
  CSV ログ      : logs/rtk_status_YYYYMMDD_HHMMSS.csv
  総サンプル数  : 199 点 (208.2 秒間)

  [測位モード内訳]
  ⭐ RTK_FIXED :  199 点 (100.0%)

  [位置誤差の標準偏差 (RTK_FIXED 区間, 199 点)]
  🎯 水平標準偏差 (1σ) : 0.8 cm (0.0078 m)
     - 緯度方向 (1σ)   : ...
     - 経度方向 (1σ)   : ...
  🎯 垂直標準偏差 (1σ) : 1.3 cm (0.0131 m)
  最大水平偏位         : ... cm
```

| 仕様 | 内容 |
|---|---|
| 対象区間 | **`RTK_FIXED` のサンプルのみ**（3 点未満なら全記録区間へフォールバック） |
| 水平 1σ | `sqrt(σ_lat² + σ_lon²)`（経度は `cos(緯度)` 補正） |
| 垂直 1σ | 高度の標準偏差 |
| 最大水平偏位 | 重心からの最大距離 |

出典: [`../../../../rtk_tools/mavlink_bridge.py`](../../../../rtk_tools/mavlink_bridge.py) の
`print_statistics()`、および
[`../../../RTK_PROCEDURES_MANUAL.md`](../../../RTK_PROCEDURES_MANUAL.md) §2 Step 4。

> 出力例は [`../../../RTK_PROCEDURES_MANUAL.md`](../../../RTK_PROCEDURES_MANUAL.md) §2 Step 4
> と [`../../../../README.md`](../../../../README.md) に記載があります。

### 5.1 高解像度ヒストグラム

実験後の可視化は次で行えます。

```bash
.venv/bin/python3 gcs/rtk_tools/plot_rtk_histogram.py <CSVログのパス>
```

水平誤差（重心からの距離）と垂直誤差（高度偏位）のヒストグラムを PNG 出力します
（出典: [`../../../RTK_PROCEDURES_MANUAL.md`](../../../RTK_PROCEDURES_MANUAL.md) §2 Step 4）。

---

## 6. ロギングの現状（重要）

`mavlink_bridge.py` は docstring で

```
+ 自動ロギング (.rtcm3 生ログ + RTK 状態 CSV)
+ 終了時「位置誤差の標準偏差 (std)」自動集計・出力
```

を掲げていますが、**現行実装では CSV / `.rtcm3` の書き出しはコメントアウト**されています
（起動バナーも `MAVLink Bridge + RTCM Injector (Logging Disabled)`）。
`--log-dir` オプションとログ保存先の準備コードもコメントアウトされています。

| 項目 | 実装状態 |
|---|---|
| `GPS_RAW_INT` の CSV 記録 | **無効**（コメントアウト） |
| RTCM 生フレームの `.rtcm3` 記録 | **無効**（コメントアウト） |
| `print_statistics()`（終了時集計） | **有効**（ただし上記 CSV が無いと何も出力しない） |
| RTCM → `GPS_RTCM_DATA` 注入 | **有効** |
| MAVLink 中継（UDP ⇄ シリアル） | **有効** |

CSV ヘッダ（コメントアウト部分に定義）:
`utc_time, elapsed_sec, fix_type, fix_name, sats, lat, lon, alt, eph, epv`

出典: [`../../../../rtk_tools/mavlink_bridge.py`](../../../../rtk_tools/mavlink_bridge.py)
の `main()`（ロギング準備・バナー）と `print_statistics()`。

> **要確認**: 手順書（[`../../../RTK_PROCEDURES_MANUAL.md`](../../../RTK_PROCEDURES_MANUAL.md) §2 Step 3）
> と [`../../../../README.md`](../../../../README.md) は
> 「`logs/rtk_status_*.csv` / `logs/rtcm_rover_*.rtcm3` が自動記録される」と記載していますが、
> 現行実装では**ロギングは無効**です。ログが必要な場合は実装の有効化、または
> [`../../../../flight_test/README.md`](../../../../flight_test/README.md) の
> `FlightRecorder`（MAVLink 観測 + CSV 出力が有効）の利用を検討してください。

---

## 7. 注意事項

1. **ポート名は `/dev/ttyAMA0`**（`/dev/serial0` ではない）。開けない場合は
   `sudo raspi-config` でシリアルコンソールを無効化する。
2. **Python は `~/Mavlink_venv/bin/python3`** を使う。システム python3 では
   `ModuleNotFoundError: No module named 'pymavlink'` になります。
3. **MAVLink 2.0 と RTS/CTS** を無効化しないこと（注入が壊れます）。
4. **シリアル排他**: MAVLink シリアルポートは `mavlink-router.service` や他ツールと
   同時に開かないこと。
5. 通信断・TCP 瞬断は RTK age の上昇として観測されます。`gcs/preflight/session.py` の
   `TcpSession` は **RTK age の stale と TCP 切断の両方**を切断として扱います
   （出典: [`../../../../preflight/README.md`](../../../../preflight/README.md) §5）。
6. **実験中の `FS_GCS_ENABLE = 0` は一時的な運用**であり、飛行時 golden は `1` です（§4）。

出典: [`../../../RTK_PROCEDURES_MANUAL.md`](../../../RTK_PROCEDURES_MANUAL.md) §6、
[`../../../../preflight/README.md`](../../../../preflight/README.md) §5 / §9。

---

## 8. 出典（`gcs/` 内のみ）

| ファイル | 参照箇所 |
|---|---|
| `gcs/rtk_tools/mavlink_bridge.py` | docstring / `FIX_NAMES` / `extract_rtcm_frames()` / `print_statistics()` / `main()` の argparse / `serial_to_udp()` / `udp_to_serial()` / `rtcm_tcp_to_mavlink()` |
| `gcs/rtk_tools/README.md` | ツール一覧 |
| `gcs/preflight/README.md` | §5 TCP 切断ハンドリング / §9 前提・注意 |
| `gcs/ekf_failsafe/golden.py` | `FS_GCS_ENABLE = 1` |
| `gcs/config/config.yaml` | `rover.mavlink_port` / `rover.mavlink_baud = 921600` |
| `gcs/README.md` | クイックスタート（Step 3） |
| `gcs/docs/RTK_PROCEDURES_MANUAL.md` | §1 / §2 Step 3・Step 4 / §6 |

> 関連: [`../mac_gcs/README.md`](../mac_gcs/README.md)（対向の Mac 側）／
> [`../pixhawk_ardupilot/README.md`](../pixhawk_ardupilot/README.md)（注入先）