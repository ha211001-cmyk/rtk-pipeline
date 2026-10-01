# udp/ — 基地局(Mac mini) → WiFi(UDP) → ラズパイ → MAVLink → Pixhawk → DroneCAN → 移動局 F9P RTK 中継

基地局 F9P を **Mac mini に USB 接続**し、その補正データ（RTCM3）を
**WiFi 経由の UDP** でラズパイへ送ります。ラズパイは受信した RTCM3 を
**MAVLink GPS_RTCM_DATA** として Pixhawk へ注入し、Pixhawk が
**DroneCAN 経由で移動局 F9P** へ転送して RTK 測位（Float / Fixed）を行います。

## 接続図

```
[基地局 F9P] --USB--> [Mac mini] --WiFi(UDP)--> [ラズパイ] --UART(MAVLink)--> [Pixhawk] --DroneCAN--> [移動局 F9P]
                           |                            |
                 udp_base_sender.py          udp_mavlink_rover.py
                 (基地局設定 + RTCM送信)      (UDP受信 + MAVLink注入)
```

## ファイル構成

| ファイル | 実行場所 | 役割 |
|---|---|---|
| `udp_base_sender.py` | **Mac mini** | 基地局F9Pを基地局モードに設定 → RTCM読み取り → UDP送信 |
| `udp_mavlink_rover.py` | **ラズパイ** | UDP受信 → MAVLink GPS_RTCM_DATA注入（Pixhawk/DroneCAN経由）→ RTK Float/Fixed表示 |
| `udp_rover.py` | **ラズパイ** | （別方式）UDP受信 → 移動局F9Pへ直接注入（移動局をラズパイにUSB/UART直結する場合） |
| `f9p_rtcm_monitor.py` | **Mac mini**（Pixhawk USB直結） | （診断）DroneCAN tunnel経由で移動局F9PのUBX-RXM-RTCMを集計し「受信・CRC確認・使用」を3軸判定 |

## 必要なもの

- 基地局用 F9P × 1（Mac mini に USB 接続）
- 移動局用 F9P × 1（Pixhawk に DroneCAN 接続）
- Pixhawk（ArduPilot。移動局 F9P を DroneCAN で搭載）
- Mac mini とラズパイを **同一 WiFi ネットワーク**に接続（例: 192.168.11.0/24）
- ラズパイと Pixhawk を **UART（MAVLink）**で接続（例: `/dev/ttyAMA0` @ 921600）
- 基地局の固定座標（福井大学: `36.0751418, 136.2133477, 44.80` を既定値に設定済み）

## 依存ライブラリ

Mac mini は `pyserial` と `pyubx2`（基地局設定用）が必要です。
ラズパイは `pyserial` と `pymavlink`（MAVLink 注入用）が必要です。
また、移動局 RTCM 受信の診断に使う `f9p_rtcm_monitor.py` は `dronecan` が必要です
（`~/Mavlink_venv` にインストール済みであれば `source ~/Mavlink_venv/bin/activate` で有効化）。

```bash
# Mac mini
pip install pyserial pyubx2

# ラズパイ（pymavlink は専用 venv を推奨）
python3 -m venv ~/Mavlink_venv
~/Mavlink_venv/bin/pip install pyserial pymavlink
```

> Mac mini で基地局設定を毎回行う場合は、リポジトリ全体を Mac mini 側にも
> 用意してください（既存の `base_station_verify/rtcm_compare/f9p_configurator_v2.py`
> を再利用するため）。

## ラズパイ側の実行手順（先に起動）

```bash
cd ~/EVK-F9P/udp
source ~/Mavlink_venv/bin/activate
python3 udp_mavlink_rover.py --rtscts
```

起動すると以下を表示します：

1. Pixhawk への MAVLink 接続（`/dev/ttyAMA0` @ 921600 bps）
2. このラズパイ自身の IP（→ Mac mini 側の `--host` に使う）
3. `UDP受信待機中: 0.0.0.0:50010`

> **RTK-FIXED 定量判定（本番検証）**: 本スクリプトは MAVLink の
> `GPS_RAW_INT.fix_type` を時系列で記録し、`gcs/fix_metrics.compute_metrics()`
> で RTK-FIXED 到達・維持率・FLOAT 遷移・TTFF を判定します。終了時に
> `udp/reports/` へ JSON レポート（`rtk_report_*.json`）と fix_type CSV を保存し、
> コンソールに PASS/FAIL を表示します。判定基準は `udp_mavlink_rover.py` 内の
> `RTK_CRITERIA` で変更できます。
>
> | 判定項目 | 合格条件 | 既定閾値 |
> |---|---|---|
> | RTK_FIXED 到達 | `reached_fixed == True`（fix_type == 6） | — |
> | FIXED 維持率 | `fixed_rate_pct >= fixed_rate_pct_min` | 80.0 % |
> | FLOAT 遷移回数 | `float_transition_count <= max_float_transitions` | 5 回 |
> | TTFF（初回 FIXED） | `ttff_sec <= ttff_sec_max` | 120.0 秒 |
>
> TTFF は **初回 RTCM 注入を起点** に計測します（基地局からの補正が流れ始めてから
> 最初の FIXED までの時間）。

### 主なオプション

| オプション | 既定値 | 説明 |
|---|---|---|
| `--port` | `50010` | UDP受信ポート |
| `--mavlink-port` | `/dev/ttyAMA0` | Pixhawk との MAVLink 接続ポート |
| `--baud` | `921600` | MAVLink ボーレート |
| `--rtscts` | 有効 | RTS/CTS フロー制御（921600bps では推奨。`--no-rtscts` で無効化） |
| `--max-packet-size` | `180` | GPS_RTCM_DATA 1パケット最大サイズ |
| `--max-fragments` | `4` | 1フレームあたり最大分割数 |
| `--duration` | `0`（無制限） | 観測時間[秒]。>0 で自動終了 + レポート保存 |
| `--report-dir` | `udp/reports` | RTK判定レポート（JSON/CSV）の出力先 |

## Mac mini 側の実行手順（後から起動）

ラズパイが `UDP受信待機中` になってから実行します。

```bash
cd ~/EVK-F9P/udp
python3 udp_base_sender.py --skip-config
```

デフォルトで以下を実行します：

1. 基地局F9Pのシリアルポート自動検出（macOS: `/dev/cu.usbmodem*`）
2. RTCM3 を読み取り、`raspi5.local`（mDNSで自動解決）へ **ユニキャスト**送信
   - 基地局が設定済みの場合は `--skip-config` で設定をスキップできます
   - 基地局設定を毎回行う場合は `--skip-config` を外します
     （TMODE3 Fixed + RTCM3 MSM7 出力有効化、Flash保存）

### 主なオプション

| オプション | 既定値 | 説明 |
|---|---|---|
| `--host` | `raspi5.local` | 送信先IPまたはホスト名（mDNSで自動解決） |
| `--port` | `50010` | UDP送信ポート |
| `--broadcast` | 無効 | ブロードキャスト送信に切り替え |
| `--serial` | 自動検出 | 基地局F9Pのシリアルポート |
| `--lat` / `--lon` / `--alt` | 福井大学座標 | 基地局の固定座標 |
| `--skip-config` | 無効 | 基地局設定をスキップ（設定済みの場合） |
| `--no-save` | 無効 | Flash保存せず RAM のみで設定 |

> 既定は `raspi5.local`（mDNS）なので、通常はIPを意識する必要はありません。
> mDNS が効かない環境では `--host 192.168.11.50` のようにIPを明示指定してください
> （ラズパイ側 `udp_mavlink_rover.py` 起動時に自身のIPを表示します）。

## 推奨ワークフロー：Mac mini から SSH でラズパイを操作

ラズパイ側で `sshd` が稼働し、Mac mini の公開鍵が登録されていれば、
**Mac mini 1台だけで完結**します。

```bash
# Mac mini ターミナル①: SSHでラズパイへ入って rover を起動（先に）
ssh taki@raspi5.local
cd ~/EVK-F9P/udp && source ~/Mavlink_venv/bin/activate && python3 udp_mavlink_rover.py --rtscts

# Mac mini ターミナル②: ローカルで基地局送信を起動（後から）
cd ~/EVK-F9P/udp && python3 udp_base_sender.py --skip-config
```

- `raspi5.local` は mDNS なので、IPを覚える必要はありません。
- SSH が使えない場合は、ラズパイのターミナルで `udp_mavlink_rover.py` を直接起動してください。

## ユニキャスト vs ブロードキャスト

UDP には送り先の指定方法が2種類あります。

| 方式 | 宛先 | 意味 |
|---|---|---|
| **ユニキャスト**（既定） | `raspi5.local`（自動解決） | 特定の1台（ラズパイ）だけに送信 |
| **ブロードキャスト**（将来） | `255.255.255.255` | ネットワーク上の全端末に一斉送信 |

```bash
# ユニキャスト（既定・安定・IP入力不要）
python3 udp_base_sender.py

# ユニキャスト（IPを明示指定したい場合）
python3 udp_base_sender.py --host 192.168.11.50

# ブロードキャスト（将来・複数受信機へ一斉配信）
python3 udp_base_sender.py --broadcast
```

受信側 `udp_mavlink_rover.py` は `0.0.0.0:50010` に bind するため、
**ユニキャスト・ブロードキャストの両方をそのまま受信**できます（方式を意識しない）。

## ブロードキャストの注意点

ブロードキャストは便利ですが、以下の制約があります。

1. **WiFi環境では不安定になりやすい**
   - アクセスポイント（ルーター）がブロードキャストパケットを遮断・フィルタすることがあります。
   - ユニキャストより到達率が下がる場合があります。まずはユニキャストで動作確認することを推奨します。

2. **同一サブネット内でしか届かない**
   - ブロードキャストはルーターを越えません。
   - Mac mini とラズパイが同じネットワーク（例: `192.168.11.0/24`）にいる必要があります。

3. **ネットワーク上の全端末に届く**
   - 無関係な端末にもパケットが届くため、セキュリティ・帯域の面で注意が必要です。

4. **パケットロス・順序逆転があり得る**
   - UDP は到達保証・順序保証がありません。
   - RTCM3 は各フレームが自己完結（`0xD3` プリアンブル + 長さ + CRC）しているため、
     1フレーム欠けても F9P は次のフレームで再同期します。大きな問題にはなりません。

## 動作確認の目安

1. **ラズパイ側**: `udp_mavlink_rover.py` が `UDP受信待機中` と表示される。
2. **Mac mini 側**: `udp_base_sender.py` が `frames=N` と表示し、N が増え続ける（RTCM受信中）。
3. **ラズパイ側**: `[STATUS] injected=N` が増加し、`GPS:RTK_FIXED`（または `RTK_FLOAT`）に到達することを確認。
   - `RTK_FLOAT (RTK浮動解 - 10~20cm)`
   - `RTK_FIXED (RTK固定解 - cm精度!)`（アンテナ環境に依存）

## トラブルシューティング

| 症状 | 原因 | 対処 |
|---|---|---|
| Mac mini 側で `frames=0` のまま | 基地局設定失敗・アンテナ未捕捉 | `--skip-config` を外して再実行、アンテナ設置確認 |
| ラズパイ側で UDP パケットが届かない | IP/ポート不一致・WiFi遮断 | `--host` をラズパイのIPに修正、同一WiFi確認、`ping` で疎通確認 |
| MAVLink 接続に失敗する | Pixhawk 未接続・ボーレート不一致 | `/dev/ttyAMA0` と `--baud 921600` を確認、Pixhawk の電源確認 |
| `injected=0` のまま増えない | UDP未受信・MAVLink未接続 | Mac mini 側の `frames` を確認、`ss -lunp` で 50010 を確認 |
| UDPポート `50010` bind 失敗 | 既に別プロセスが使用中 | `--port` を変更、または `ss -lunp` で確認 |
| F9Pポートが見つからない | USB未接続・権限 | `ls /dev/ttyACM*` / `ls /dev/cu.usbmodem*` で確認、`dialout` 権限を付与 |
| `RTK_FLOAT` 止まりで `RTK_FIXED` にならない | アンテナ環境・基線長 | 開けた場所で待つ、マルチパス低減 |
| 基地局設定で `all_ok=False` | F9P再起動による一時的な検証失敗 | 送信開始後に `frames` が増えていれば成功。再実行も可 |
| `mavlink-routerd` と ttyAMA0 が競合 | 両者が `/dev/ttyAMA0` を open | 不要なら mavlink-routerd を停止、または異なるポートを使用 |

## 場所を変えて再テストする場合（基地局・移動局を移動）

RTK_FIXED 到達は物理環境（基地局↔移動局の基線長・アンテナ上空視界・マルチパス）に依存するため、
別の場所で再テストする場合は以下の手順で行います。

> **⚠️ 最重要**: 基地局 F9P は TMODE3 Fixed Mode で、座標が Flash 保存されています。
> **基地局を移動した場合、必ず新座標を再観測して再設定**してください。
> 旧座標（福井大学）のままだと、たとえ RTK_FIXED になっても出力位置が
> 移動距離ぶんだけズレます。

### ステップ1：新基地局座標の取得（Mac mini）

新しい場所に基地局 F9P を設置し、**TMODE3 を一旦解除して単独測位**で実座標を取得します。
（TMODE3 のままだと「設定済みの固定座標」が出力されるため、解除が必須です）

```bash
cd ~/EVK-F9P/base_station_verify/rtcm_compare
python3 standalone_obs.py --set-rover --duration 120 --save
```

- `--set-rover`: 観測前に `CFG_TMODE_MODE=0`（移動局化）を送信して実測値を出力させる
- `--duration 120`: 観測秒数（上空視界の良い場所で長め推奨）
- 出力の **平均高度（楕円体高 HAE）** を `--alt` に使う（MSL ではない点に注意）
- ポートが見つからない場合は `--port /dev/cu.usbmodemXXXX` を明示指定

### ステップ2：新座標で基地局を再設定（TMODE3 Fixed + RTCM3）

`--skip-config` を**付けずに**、新座標を指定して起動し Flash に書き込みます。

```bash
cd ~/EVK-F9P/udp
python3 udp_base_sender.py \
    --lat <新緯度> --lon <新経度> --alt <新高度HAE> \
    --host <ラズパイのIP/host> --port 50010
```

- Flash 保存後は F9P が再起動しポートが再列挙されるため、5秒待機後に自動再検出
- `all_ok=False` でも、送信開始後に `frames` が増えていれば成功
- 新拠点を常用する場合は、`udp_base_sender.py` の `DEFAULT_LAT/LON/ALT`（49〜51行）を
  新座標に更新しておくと、毎回の引数指定が不要になります

### ステップ3：中継系の起動（ラズパイ→Mac の順）

1. ラズパイ側（先）: `sudo systemctl stop mavlink-router.service` → `udp_mavlink_rover.py --rtscts`
2. Mac mini 側（後）: ステップ2の `udp_base_sender.py`（再設定済みなら2回目以降は `--skip-config` 可）

### ステップ4：テストと記録

開けた場所で待機し、`RTK_FLOAT → RTK_FIXED` への到達を確認。以下を記録します：

- 移動内容（基地局/移動局それぞれどこへ）、基線長、アンテナ上空視界、マルチパスの有無
- RTK 状態の推移（`3D_FIX → RTK_FLOAT → RTK_FIXED`）、衛星数、FIXED 到達までの所要時間

## FIX 判定の観測手順とログ取得（診断）

RTK_FLOAT 到達後に「十分待ったか」「なぜ FIX しないか」を判定するための手順です。

### FIX 判定の目安

- **数秒〜数十秒**: 条件が良ければ FIX することがある
- **1〜2分**: まず確保したい観測時間
- **5分程度**: FIX しないかを判断するには十分な時間
- **10分経っても FIX しない**: 待ち時間不足ではなく観測条件・衛星状態・補正データを調査

> 重要なのは「FLOAT になった瞬間から5分」ではなく、**FLOAT → FIXED の状態遷移を
> タイムスタンプ付きで連続記録**することです。

### ログの見方（`udp_mavlink_rover.py` の [STATUS]）

`[STATUS]` にタイムスタンプ・位置・基線長を追加しました：

```
[STATUS 12:41:56] injected=121 dropped=0 bytes=17427 | GPS:RTK_FLOAT sats=32 nsats=0 base=? pos=36.0757585,136.2136042 | 最終RTCMから0.0秒
```

| フィールド | 意味 |
|---|---|
| `HH:MM:SS` | 観測時刻（FLOAT/FIXED の遷移記録に使用） |
| `GPS:RTK_FLOAT/FIXED` | RTK 状態 |
| `sats` | 捕捉衛星数（GPS_RAW_INT） |
| `nsats` | RTK 使用衛星数（GPS_RTK。ArduPilot が未送出の場合は 0） |
| `base` | 基線長（GPS_RTK。未取得時は `?`。`pos` から代替算出可） |
| `pos` | ローバー RTK 位置（緯度,経度）→ 位置安定性・基線長の算出に使用 |
| `最終RTCMから` | RTCM 受信の連続性（秒） |

### 基地局 C/N0・DOP の取得（`base_ubx_logger.py`）

基地局 F9P の C/N0（信号品質）・DOP を取得する診断スクリプトです。

```bash
# 基地局送信を停止してから実行（シリアル排他アクセスのため）
cd ~/EVK-F9P/udp
python3 base_ubx_logger.py --duration 120 --interval 5
```

出力例（`numSV`=衛星数、`C/N0`=信号品質 min/avg/max）:

```
[12:43:33] PVT numSV=32 pDOP=99.99 fixType=5
[12:43:33] SAT n=62 C/N0 min=0 avg=25.7 max=46
```

> **注意**: 基地局は TMODE3 Fixed モードのため **DOP は 99.99（無効値）**になります。
> DOP の代わりに、ローバー側の `eph/epv`（精度）や基地局の C/N0 で評価します。

### 移動局 RTCM 受信の確認（`f9p_rtcm_monitor.py`）

移動局 F9P（DroneCAN 接続）が **RTCM を受信・CRC確認・使用**できているかを、
**DroneCAN tunnel** 経由で直接確認する診断スクリプトです。

Pixhawk の **USB（MAVLink）** に接続したコンピュータで実行し、DroneCAN の
`uavcan.tunnel.Targetted`（target_node_id=125, serial_id=0）で運ばれる F9P 内部
UART1 のバイト列から `UBX-RXM-RTCM`（class=0x02, id=0x32）を抽出して、RTCM メッセージ種別
（msgType）ごとの受信回数・CRC失敗・used分布を集計し、「受信 / CRC確認 / 使用」の3軸で
OK/NG を判定します。

```bash
source ~/Mavlink_venv/bin/activate
cd ~/EVK-F9P/udp
python3 f9p_rtcm_monitor.py --monitor-rtcm 60
```

| オプション | 既定値 | 説明 |
|---|---|---|
| `--monitor-rtcm` | （必須） | 受信を継続する秒数（例: 30〜60） |
| `--port` | `/dev/cu.usbmodem101` | Pixhawk の MAVLink USB ポート |
| `--target-node` | `125` | F9P/GPS の DroneCAN node_id |
| `--serial-id` | `0` | `uavcan.tunnel.Targetted` の serial_id |
| `--local-node` | `100` | 本スクリプト自身の DroneCAN node_id |
| `--bus-number` | `1` | MAVCAN が接続する CAN バス番号 |

> **注意**: 読み取り専用のため UART Locking は行いませんが、Mission Planner 等が
> 同じポートを同時に使っていないことを事前に確認してください。

### FIX しない場合の切り分け項目

5分待っても FIX しない場合は、以下を同時に記録して原因を絞り込みます：

| 項目 | 取得元 |
|---|---|
| ① 衛星数 | `[STATUS] sats` / `numSV` |
| ② C/N0 | `base_ubx_logger.py`（基地局）。ローバー側は ArduPilot SD ログ |
| ③ DOP | 基地局は無効（TMODE3）。ローバーは `eph/epv` で代替 |
| ④ 基線長 | `[STATUS] base`（または `pos` から算出） |
| ⑤ RTCM 連続性 | `[STATUS] 最終RTCMから` |
| ⑥ FLOAT 継続時間 | `[STATUS]` のタイムスタンプから算出 |

## 進捗報告（2026-08-28）

### 現在のステータス

| 項目 | 状態 |
|---|---|
| Mac mini `udp_base_sender.py` | ✅ 稼働中（RTCM 送信、`frames` 増加中） |
| ラズパイ `udp_mavlink_rover.py` | ✅ 稼働中（`injected` 増加中 / `dropped`≈0） |
| RTCM 中継 | ✅ 正常（RTCM → UDP → MAVLink → DroneCAN まで到達） |
| RTK 状態 | ✅ RTK_FLOAT（浮動解・衛星 30） |
| RTK_FIXED（固定解） | ⏳ 未到達（物理環境に依存） |

### 実施済みのコード修正

- `base_station_verify/rtcm_compare/f9p_configurator_v2.py`
  - 設定キー全40件をハイフン→アンダースコア化（`CFG-TMODE-MODE` → `CFG_TMODE_MODE` 等）
  - QZSS MSM7（TYPE1117）キー除去（pyubx2 に未収録）
  - `UBXMessage.cfgkey_from_string` → `cfgname2key` 修正
- `udp/udp_mavlink_rover.py`
  - `--rtscts` 既定を有効（True）に変更

### 運用上の注意点

- `mavlink-routerd` が `/dev/ttyAMA0` を占有するため、`udp_mavlink_rover.py` 起動前は
  `sudo systemctl stop mavlink-router.service` で停止が必要。
  （GCS を併用する場合は、mavlink-routerd 経由の UDP 注入への恒久対応が望ましい）
- RTK Fixed 到達には、基地局↔移動局の**基線長**とアンテナの**上空視界**が重要。

## 再テスト結果（2026-09-04）

### 実施内容

1週間ぶりに再テストを実施。ローバー（`udp_mavlink_rover.py`）は前回から継続稼働していたため、
基地局送信（`udp_base_sender.py`）のみ再起動して RTCM の流れを確認した。

### システム状態（テスト時点）

| 項目 | 状態 |
|---|---|
| Mac mini `udp_base_sender.py` | ✅ 稼働中（`frames` 増加中、最終受信 0.0秒） |
| ラズパイ `udp_mavlink_rover.py` | ✅ 稼働中（`injected` 増加中） |
| RTCM 中継 | ✅ 正常（RTCM → UDP → MAVLink → DroneCAN、最終RTCM 0.0秒） |

### RTK 状態の推移

| 時点 | GPS 状態 |
|---|---|
| テスト前（RTCM 停止中・約7.5日間） | `3D_FIX`（単独測位に戻っていた） |
| RTCM 再開後 | `RTK_FLOAT`（浮動解・衛星 28〜32） |
| RTK_FIXED（固定解） | ⏳ 未到達 |

### 所見

- 基地局送信の再開により RTCM が正常に流れ、ローバーが `3D_FIX → RTK_FLOAT` に復帰。中継系は正常動作。
- RTK_FIXED 到達は引き続き物理環境（基地局↔移動局の基線長・アンテナの上空視界・マルチパス）に依存。

## 再テスト結果（2026-09-07）— 場所を変えてのテスト

### 実施内容

基地局・移動局の**両方を新拠点へ移動**してテストを実施。基地局座標を単独測位で再取得し、
基地局を再設定して RTK の流れを確認した。

### 新基地局座標（単独測位 120秒平均）

| 項目 | 旧（福井大学） | 新（観測値） |
|---|---|---|
| 緯度 | 36.0751418° | **36.0757511°** |
| 経度 | 136.2133477° | **136.2136128°** |
| 高度（楕円体高 HAE） | 44.80 m | **48.40 m** |

### 重大バグの発見と修正（CFG_TMODE_POS_TYPE）

基地局を再設定しても RTCM Type 1006 が**旧座標（福井大学）のまま**だったため調査したところ、
`f9p_configurator_v2.py` が `CFG_TMODE_POS_TYPE=0`（＝**ECEF**）を設定しながら
`CFG_TMODE_LAT/LON/HEIGHT`（＝**LLH**）を書き込む矛盾があり、LLH 座標が無視され
旧 ECEF 座標が使われ続けていた。

- **修正**: `CFG_TMODE_POS_TYPE` を `0`（ECEF）→ `1`（LAT/LON/HEIGHT）に変更
  - `base_station_verify/rtcm_compare/f9p_configurator_v2.py`
  - `rtk_base_mavlink/f9p_configurator.py`（同一バグ）
- **検証**: 修正後に RTCM Type 1006 をデコードし、`36.0757511, 136.2136128, 48.40` への反映を確認 ✅

> このバグは、`--lat/--lon/--alt` で座標を変えても基地局が旧座標を放送し続けるため、
> 「場所を変える」運用では必ず踏む致命的な問題でした。

### システム状態（テスト時点）

| 項目 | 状態 |
|---|---|
| Mac mini `udp_base_sender.py` | ✅ 稼働中（`frames` 増加中、最終受信 0.0秒） |
| ラズパイ `udp_mavlink_rover.py` | ✅ 稼働中（`injected` 増加中 / `dropped`≈0） |
| RTCM 中継 | ✅ 正常（RTCM → UDP → MAVLink → DroneCAN、最終RTCM 0.0〜2.0秒） |
| 基地局座標 | ✅ 新座標を放送中（Type 1006 デコードで確認） |

### RTK 状態の推移

| 時点 | GPS 状態 |
|---|---|
| RTCM 再開後 | `RTK_FLOAT`（浮動解・衛星 24〜29） |
| RTK_FIXED（固定解） | ⏳ 未到達 |

### 所見

- **中継系・座標設定は正常**。POS_TYPE 修正により新座標が正しく放送されることを確認。
- RTK_FLOAT には到達するものの RTK_FIXED には未到達（観測時点）。
- **UDP ロス切り分けの結果**（当初「約98%ロス＝WiFi 起因」と見えたが誤り）:
  - 真因は診断中にシリアルポートを二重オープンしたことで sender が過渡的に劣化したため。
    sender をクリーン再起動すると **約5%ロス**（送信324/受信307）まで回復。
  - 独立した UDP テストでも、等間隔送信（1〜100パケット/秒）は **0%**、200個バーストは
    **2.5%** のロスで、**WiFi 自体は正常**（Mac -69dBm / Pi -64dBm、5GHz）。
- つまり RTK_FIXED 未到達は UDP ロスではなく、**物理環境（上空視界・マルチパス・基線長）**
  に依存する。フルレートの RTCM が流れているため、開けた場所での再計測で FIXED 到達の見込み。

### 2回目の場所変更（同日・再テスト）

さらに場所を変更して再テストを実施（前回から約1m移動）。

**新基地局座標（単独測位 120秒平均）**

| 項目 | 1回目 | 2回目（今回） |
|---|---|---|
| 緯度 | 36.0757511° | **36.0757561°** |
| 経度 | 136.2136128° | **136.2136025°** |
| 高度（楕円体高 HAE） | 48.40 m | **46.54 m** |

**結果**

- POS_TYPE 修正が機能し、**新座標が正しく RTCM Type 1006 に反映**されたことを再確認
  （デコード結果 `36.0757561, 136.2136025, 46.54` と完全一致 ✅）
- 中継系はフルレート（約30フレーム/秒）で正常動作、UDP ロス約5%
- 移動局は `RTK_FLOAT`（衛星30）に到達、`RTK_FIXED` は未到達
  → 引き続き物理環境（マルチパス・上空視界・基線長）に依存

### 3回目の場所変更（同日・再テスト）

さらに場所を変更（2回目地点から南へ約73m・西へ約19m、元の福井大学地点の近傍）して再テスト。

**新基地局座標（単独測位 120秒平均）**

| 項目 | 2回目 | 3回目（今回） |
|---|---|---|
| 緯度 | 36.0757561° | **36.0750955°** |
| 経度 | 136.2136025° | **136.2133989°** |
| 高度（楕円体高 HAE） | 46.54 m | **47.61 m** |
| 単独測位 std（緯度/経度/高度） | 0.12m / 0.08m / 0.34m | **3.03m / 1.26m / 1.94m** |

**診断ログによる切り分け（Phase A/B の成果）**

| 項目 | 観測値 | 評価 |
|---|---|---|
| 衛星数 | 32（使用44） | ✅ 十分 |
| 基地局 C/N0 | avg 37.6 dBHz / max 46 | ✅ 悪くない |
| 基線長 | 約0.25m（`pos` から算出） | ✅ 極短（ボトルネックではない） |
| RTCM 連続性 | 最終RTCM 0.0秒 | ✅ 断絶なし |
| FLOAT 継続時間 | 約11分 | ⚠️ FIX せず |
| 単独測位 std | 緯度3.0m | ⚠️ 大きい → **マルチパス** |

**結論（Phase 1 解析で訂正済み）**

- 衛星数・C/N0・基線長・RTCM 連続性はいずれも良好。にもかかわらず FLOAT のまま FIX しない。
- 当初「単独測位 std 3m → マルチパス」と見えたが、**起動時の1サンプル（t=0、HDOP=99.99、位置75.8mずれ）によるアーティファクト**と判明。
  - 起動サンプル除外後の 3回目水平 std は **0.42m**（1回目0.18m / 2回目0.08m）。
  - 3地点とも「ゆっくりドリフト（自己相関が高い）」で、ランダムなジャンプではない。
- つまり単独測位データからは**マルチパスを示す強い証拠は得られず**、FIX 未達の原因は場所固有ではなく**別の系統的要因**（基地局座標精度・RTK設定・極短基線など）の可能性が高い。
- タイムスタンプ付き状態遷移ログにより、FLOAT 到達から FIX 未達（約11分）を定量的に記録できた。
