# rtk_field_test — 開けた場所での RTK 記録・解析（GLONASS 両側オフ検証）

開けた場所に基地局とローバーを置き、**GLONASS を両側で無効化**した状態で
**約10分間静止記録**し、ログを解析して RTK FIX の挙動を切り分けるためのツール群です。

## 目的

- 基地局・移動局の両方で GLONASS を外し、RTK FIXED 到達の有無を確認する
- RTCM 生データ（`.rtcm3`）とローバー RTK 状態（CSV）を記録して後から読み解く

## フォルダ構成

```
rtk_field_test/
├── README.md            # このファイル
├── rtcm_logger.py       # RTCM生ログ保存＋msgType集計（base/rover 共用）
├── set_gnss_mode.py     # ローバー側 GLONASS 無効化（GPS_GNSS_MODE の bit6 を落とす）
├── base_recorder.py     # 基地局 F9P → RTCM受信 → .rtcm3保存（＋任意でUDP送信）
├── rover_recorder.py    # UDP受信 → MAVLink注入 + .rtcm3保存 + RTK状態CSV
├── set_rtcm_rate.py     # 基地局の RTCM 出力レート変更（1Hz など）
├── analyze_status.py    # RTK状態CSVの解析（FIX到達判定・std・最大誤差・継続時間）
└── logs/                # 出力先（.gitignore に追加）
```

## 検証レポート・ログ保全（2026-09-27 実地検証）

- **レポート**: [`RTK_FIELD_TEST_REPORT.md`](RTK_FIELD_TEST_REPORT.md) — 基地局 Mac/ZED-F9P → UDP → ローバー
  Raspberry Pi/ArduPilot の RTCM 配信で、RTK-FIXED 到達（TTFF 約 5 秒）と維持（dropped=0 / loss 0%）をログで立証。
- **保全ログ**: `logs/rtk_rover_full.log`（ローバー、injected=2471）、`logs/rtk_sender2.log`（送信、frames=2299）、
  `logs/rtk_sender_full.log`（frames=1485）、`logs/rtk_sender.log`（初回、frames=832）。
  ※ ラズパイ正本 `/home/taki/rtk_rover.log`（injected=3263 まで）は SSH 到達不可のため未回収（後日追記予定）。


## 依存ライブラリ

| スクリプト | 実行場所 | 必要なライブラリ |
|---|---|---|
| `set_gnss_mode.py` | ラズパイ | `pymavlink` |
| `base_recorder.py` | Mac mini | `pyserial` |
| `set_rtcm_rate.py` | Mac mini | `pyserial` + `pyubx2` |
| `rover_recorder.py` | ラズパイ | `pyserial` + `pymavlink` |
| `rtcm_logger.py` / `analyze_status.py` | どちらでも | 標準ライブラリのみ |

```bash
# Mac mini
pip install pyserial

# ラズパイ（pymavlink は専用 venv を推奨）
python3 -m venv ~/Mavlink_venv
~/Mavlink_venv/bin/pip install pyserial pymavlink
```

> `rover_recorder.py` はリポジトリ内の `rtk_base_mavlink/`（`MavlinkComm` / `RtcmInjector`）を
> `sys.path` 挿入で再利用します。リポジトリ全体をラズパイ側にも用意してください。

## 現地での手順（10分静止記録）

事前に基地局・ローバーを開けた場所へ設置（上空視界を確保）。

> **新規場所へ移動した場合は、必ず下記 ⓪ で基地局座標を再測してから進めること。**
> 旧座標のままだと、たとえ RTK_FIXED になっても出力位置が移動距離ぶんだけズレる。

### ⓪ 基地局座標の再測（新規場所のみ・Mac mini）

```bash
cd ~/EVK-F9P/base_station_verify/rtcm_compare
python3 standalone_obs.py --set-rover --duration 120 --save
```

- `--set-rover` で一時的に移動局化して単独測位（TMODE3 を解除）
- 出力の **平均 緯度 / 経度 / 高度（楕円体高 HAE）** を控える（後続の `--lat/--lon/--alt` に使用）
- ポートが見つからない場合は `--port /dev/cu.usbmodemXXXX` を明示指定

### ① ローバー側 GLONASS を無効化（ラズパイ）

```bash
cd ~/EVK-F9P/rtk_field_test
source ~/Mavlink_venv/bin/activate
python3 set_gnss_mode.py --no-glonass
```

- 現在の `GPS_GNSS_MODE` を表示し、GLONASS ビット（bit6）だけ落として書き戻す
- 画面に表示される「元値」を控えておく（実験後の復元に使用）
- 反映には **Pixhawk / GPS の再起動**が必要

### ② 基地局側 GLONASS を無効化（Mac mini）

```bash
cd ~/EVK-F9P/udp
python3 glonass_toggle.py --off
```

- 基地局の GLONASS RTCM 出力（Type 1087/1230）を停止
- 既定は **RAM のみ**（電源再投入で自動復元＝恒久化しない）

### ③ ローバー側を起動（ラズパイ・先に起動）

```bash
cd ~/EVK-F9P/rtk_field_test
source ~/Mavlink_venv/bin/activate
python3 rover_recorder.py --rtscts --log-dir logs
```

- `UDP受信待機中: 0.0.0.0:50010` と表示されるまで待つ
- RTK 状態が `logs/rtk_status_*.csv` に **1秒毎** 記録される

### ④ 基地局側を起動（Mac mini・後から起動）

**新規場所（再設定が必要）の場合：**

```bash
cd ~/EVK-F9P/rtk_field_test
python3 base_recorder.py --lat <新緯度> --lon <新経度> --alt <新高度HAE>
```

- 起動時に基地局を TMODE3 + RTCM3 に設定（Flash 保存 → 自動再検出）してから記録開始
- RAM のみで設定したい場合は `--no-save` を付ける

**基地局が設定済みの場合：**

```bash
cd ~/EVK-F9P/rtk_field_test
python3 base_recorder.py
```

- RTCM が `logs/rtcm_base_*.rtcm3` に保存されつつ、ラズパイへ UDP 送信される
- 送信先は既定 `raspi5.local:50010`（`--host` / `--port` で変更可）
- 記録のみ（UDP 送信なし）にしたい場合は `--no-udp` を付ける

### ⑤ 10分間静止

この間 `rover_recorder.py` が RTK 状態を記録し続ける。
`[STATUS]` に `GPS:RTK_FLOAT` / `GPS:RTK_FIXED` の遷移が表示される。

### ⑥ 終了

両方の端末で **Ctrl+C**。msgType 別集計と保存先パスが表示される。

## RTCM 出力レートの変更（1Hz 化）

基地局の RTCM 出力レートを変えて帯域を減らす場合（フルレートが FIX 未達の原因かを
切り分ける場合など）：

```bash
# 基地局を 1Hz に（Mac mini）
cd ~/EVK-F9P/rtk_field_test
python3 set_rtcm_rate.py --rate 1

# 5Hz（200ms）に戻す場合
python3 set_rtcm_rate.py --restore 200
```

- `CFG_RATE_MEAS`（測定レート）を変更する。既定は RAM のみ（電源再投入で復元）
- `--rate 1` は 1000ms（1Hz）、`--rate 5` は 200ms（5Hz）に相当
- `--save` を付けると Flash 保存（永続化）

## 解析手順（読み解き）

### 1. RTK 状態 CSV の解析

```bash
cd ~/EVK-F9P/rtk_field_test
python3 analyze_status.py logs/rtk_status_YYYYMMDD_HHMMSS.csv
```

出力される項目：

| 項目 | 内容 |
|---|---|
| FIX 状態遷移 | いつ `3D_FIX → RTK_FLOAT → RTK_FIXED` に遷移したか（タイムスタンプ付き） |
| FIX 別継続時間 | 各状態に留まった時間（FLOAT が何分続いたか等） |
| RTK FIXED 判定 | ✅ 到達 / ❌ 未到達、到達なら開始からの秒数 |
| 衛星数 sats / nsats | GLONASS 除去で衛星数が減ったか |
| 基線長 base(m) | 基線長が安定しているか |
| 位置の安定性 | 緯度/経度の標準偏差(m)・最大水平誤差(m) |

### 2. RTCM 生データの型別解析（GLONASS が消えたか確認）

```bash
source ~/Mavlink_venv/bin/activate
cd ~/EVK-F9P
python3 dronecan_gps_rtk/ntrip_rtk_client/analyze_rtcm.py \
  rtk_field_test/logs/rtcm_base_YYYYMMDD_HHMMSS.rtcm3
```

- **Type 1087（GLO MSM7）と 1230（GLO Bias）が 0 であること** を確認
- Type 1006 / 1077（GPS）/ 1097（GAL）/ 1127（BDS）が流れていることを確認

## 注意点

- **GLONASS 設定の復元**
  - 基地局: `glonass_toggle.py --off` は RAM のみ。電源再投入で復元、または `glonass_toggle.py --on`
  - ローバー: `set_gnss_mode.py --restore <元値>` で復元（Pixhawk に永続保存されるため必ず実施）
- **基地局座標** を動かした場合は、新座標を再観測して基地局を再設定すること
- **シリアル排他アクセス**: `base_recorder.py` と `glonass_toggle.py` / `udp_base_sender.py` を
  同時に動かさない（同じポートを二重オープンすると不安定になる）
- `rover_recorder.py` 起動前は `sudo systemctl stop mavlink-router.service` で
  `/dev/ttyAMA0` の競合を回避すること
