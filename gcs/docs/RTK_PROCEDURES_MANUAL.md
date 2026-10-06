# GCS (RTK-Pipeline) 運用・操作手順書

本手順書は、`gcs` ディレクトリ内に統合された **RTK測位システムの地上管制（GCS）** の運用・操作手順をまとめたものです。
Mac（地上基地局・GCS）と Raspberry Pi 5（ドローン搭載機・Pixhawk接続）を組み合わせた実機運用フローをベースに解説します。

---

## 1. システム構成と準備

このシステムは、以下の2つの主要モジュールから構成されます。

1. **Mac (GCS & 基地局)**: Webダッシュボードの提供、基地局としてのRTCM補正データの配信。
2. **Raspberry Pi 5 (Rover)**: 機体側のMAVLink通信の中継、RTCMデータの受信・注入、およびログ記録。

```text
┌───────────────────────────────────────────────┐
│              Mac (地上基地局 & GCS)            │
│  - IP: 192.168.2.1 (Wi-Fi/有線ルーター親機)    │
│  - 基地局 F9P: USB (/dev/cu.usbmodem112301)   │
│  - RTCM3 配信: TCP 2101                       │
│  - Web GCS ダッシュボード: http://localhost:9000│
│                           (UDP:14550 受信)    │
└───────────────────────┬───────────────────────┘
                        │ 有線LAN (USB-LANアダプタ)
┌───────────────────────▼───────────────────────┐
│         アクセスポイント (BUFFALO AP)          │
│  - IP: 192.168.2.3 (ブリッジ接続)              │
└───────────────┬───────────────────────┬───────┘
                │ Wi-Fi                 │ Wi-Fi
┌───────────────▼───────────────┐   ┌───▼───────────────────────────┐
│ ローバー (Raspberry Pi 5)     │   │ 別のPC (監視 / 作業用ノートPC)│
│  - IP: 192.168.2.x (DHCP)     │   │  - IP: 192.168.2.2 (DHCP)     │
│  - Pixhawk: /dev/ttyAMA0      │   │  - ブラウザ等で GCS を閲覧可能 │
│  - mavlink_bridge.py 実行     │   │    http://192.168.2.1:9000    │
└───────────────────────────────┘   └───────────────────────────────┘
```

### 1.1 仮想環境の構成と依存ライブラリのインストール（重要）

本システムでは、ライブラリの競合を防ぐため **Mac（基地局/GCS側）と Raspberry Pi（Rover側）の双方で独立した Python 仮想環境** を使用して運用します。

| ホスト | 役割 | 仮想環境パス | 有効化コマンド / 実行バイナリ | 主なライブラリ |
|---|---|---|---|---|
| **Mac (基地局 & GCS)** | 基地局RTCM配信・Web UI・解析・プロット | `~/rtk-pipeline-local/.venv` | `source .venv/bin/activate`<br>（または `.venv/bin/python3`） | `fastapi`, `uvicorn`, `pyserial`, `matplotlib`, `numpy`, `pyyaml` 等 |
| **Raspberry Pi 5 (Rover)** | MAVLink中継・RTCM注入・機体ロギング | `~/Mavlink_venv` | `~/Mavlink_venv/bin/python3` | `pymavlink`, `pyserial` |

#### セットアップ手順

**Mac (GCS/基地局側)**
基地局プログラムや Web ダッシュボード、事後解析スクリプトを動かすため、リポジトリ直下に `.venv` を作成します：
```bash
cd ~/rtk-pipeline-local
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install matplotlib numpy  # 誤差ヒストグラム作成用
```
*(※ Mac 側で作業を行うターミナルでは、必ず最初に `source .venv/bin/activate` を実行してください)*

**Raspberry Pi (Rover側)**
ラズパイ上では MAVLink 関連ツール用に独立した仮想環境 `~/Mavlink_venv` を使用します：
```bash
python3 -m venv ~/Mavlink_venv
~/Mavlink_venv/bin/pip install pymavlink pyserial
```

---

## 2. 標準運用フロー（実機運用クイックスタート）

Mac（ルーター親機: `192.168.2.1`）とアクセスポイント（`192.168.2.3`）、Raspberry Pi（Rover）を同一ローカルネットワークで接続し、自動で RTK-FIXED（サブセンチ精度）を達成し、実験ログを保存する手順です。

### Step 1: 基地局 RTCM 配信の起動（Mac側: 192.168.2.1）
第 1 ターミナルを開き、**仮想環境 `.venv` を有効化**した上で、基地局の F9P を固定座標モードで起動します。これにより `TCP:2101` で補正データの配信が始まります。

```bash
cd ~/rtk-pipeline-local
source .venv/bin/activate
python3 gcs/rtk_tools/rtk_base_station_v2.py --config gcs/config/base_station.json --serial-port /dev/cu.usbmodem112301
```
> **確認:** `TCP listening on 0.0.0.0:2101` と表示されれば待機完了です。ポート名は環境に応じて変更してください。

> ⚠️ **【超重要】アンテナ設置場所を変更した場合の注意**:
> `base_station.json` に設定する座標は、**実際のアンテナ位置と数メートル以内で一致している必要があります**。数十〜数百メートルのズレがあると幾何学的な位相差の矛盾により Rover F9P が RTK 計算を拒絶し、`3D_FIX` のまま `RTK_FLOAT / FIXED` に入りません。  
> アンテナを移動した際は、事前に `python3 single_unit_test/run_survey.py --set-rover --duration 30` で実測した緯度・経度・高度（楕円体高 HAE）を `base_station.json` の `fixed_pos` に書き込んでください。

### Step 2: GCS Webダッシュボードの起動（Mac側）
第 2 ターミナルを開き、**仮想環境 `.venv` を有効化**した上で、監視・制御用のWebサーバーを起動します。

```bash
cd ~/rtk-pipeline-local
source .venv/bin/activate
python3 -m gcs.server --port 9000
```
> **確認:** ブラウザで **http://localhost:9000**（または別PCから **http://192.168.2.1:9000**）にアクセスし、右上の **「Connect」** を1回クリックしてデータ待機状態にします。

### Step 3: MAVLink ブリッジ & RTK 注入・ロギング起動（Raspberry Pi側）
機体に搭載したラズパイに SSH 接続し、**仮想環境 `~/Mavlink_venv` の Python を使って**統合ブリッジプログラムを起動します（デフォルトで Mac の IP `192.168.2.1` に接続します）。

```bash
cd ~/rtk-pipeline-local
~/Mavlink_venv/bin/python3 gcs/rtk_tools/mavlink_bridge.py --serial /dev/ttyAMA0 --baud 921600
```
*(※ ターゲットホストのデフォルトは `192.168.2.1` です。明示指定する場合は `--target-host 192.168.2.1`)*  
*(※ `--rtscts`（ハードウェアフロー制御）および `MAVLink 2.0`（`MAVLINK20=1`）が標準で組み込まれており、Pixhawk TELEM1 @ 921600bps での安定通信が担保されています)*

**起動後の動作:**
- Webダッシュボードが緑色の「Online」になり、姿勢・バッテリー・GPS情報がリアルタイム表示されます。
- 基地局から補正データが受信され、GPSステータスが `3D_FIX` → `DGPS` → `RTK_FLOAT` → **`RTK_FIXED`** へと自動で昇格します。
- 測位時系列データ(`csv`)とRTCM3生データ(`rtcm3`)が `logs/rtk_status_YYYYMMDD_HHMMSS.csv` に自動保存されます。

### Step 4: 実験終了と標準偏差の自動集計
実験が完了したら、ラズパイ側のターミナルで **`Ctrl + C`** を 1 回押します。
即座に位置誤差の標準偏差・RTK精度のサマリーがターミナルに出力されます。

```text
==================================================================
 📊 実験ロギング & 位置精度解析サマリー
==================================================================
  CSV ログ      : logs/rtk_status_20261001_181637.csv
  総サンプル数  : 1207 点 (1212.7 秒間)

  [測位モード内訳]
  ⭐ RTK_FIXED : 1207 点 (100.0%)

  [位置誤差の標準偏差 (RTK_FIXED 区間)]
  🎯 水平標準偏差 (1σ) : 0.8 cm (0.0078 m)
  🎯 垂直標準偏差 (1σ) : 1.3 cm (0.0131 m)
==================================================================
```

### Step 5: 事後解析とヒストグラムの作成（Mac側）
取得した CSV ログを Mac 側にコピーし、仮想環境 `.venv` を使用して区間比較や誤差ヒストグラムを生成します。

#### 1. 5分・20分・60分の区間精度比較
60分のログから「最初の5分」「最初の20分」「全60分」を自動切り出し、各区間の標準偏差・最大偏位を比較表示します：
```bash
cd ~/rtk-pipeline
source .venv/bin/activate
python3 gcs/analyze_intervals.py <CSVログのパス>
```

#### 2. 誤差ヒストグラム画像の作成
水平誤差（重心からの距離）および垂直誤差（高度偏位）のヒストグラムを高解像度画像（PNG）として出力します：
```bash
cd ~/rtk-pipeline
.venv/bin/python3 gcs/rtk_tools/plot_rtk_histogram.py <CSVログのパス>
```

---

## 3. Web UI (GCS) での運用・監視

ブラウザ (http://localhost:9000) 上のGCSダッシュボードでは、以下の操作が可能です。

### 制御操作
- **機体監視:** 最大4機のドローンの状態（Armed / Mode / バッテリー / RTK Fix / NED）を監視。
- **一斉制御:** 『ALL DRONES』パネルから機体への指示（ARM / DISARM / TAKEOFF / LAND）を送信可能。

### 「⚙️ 運用」タブからの高度な操作
Web UIの「⚙️ 運用」タブから、CLIを使わずに各種ツールを実行できます。

- **設定系:** F9Pの各種設定の読み取り(`f9p_verify`)や書き込み(`f9p_write_verify`)。
- **監視系:** RTK FIXEDの維持率やTTFF（Time To First Fix）の監視、RTCMの到達やCRCエラー監視。
- **ロギング系:** PPK用ログ（RAWX/SFRBX）の記録やRTCM生フレームの記録。

> **⚠️ 注意:** 「基地局座標の再設定」や「Flashへの書き込み」などの危険な操作（Dangerous）は、実行前に必ず確認モーダルが表示されます。設定変更前は `f9p_verify` で現在値を確認してください。

---

## 4. F9Pモジュールの設定と保存（RAM / Flash）

F9Pの設定書き込み時、レイヤー（揮発・不揮発）を意識して運用してください。

- **RAMへの一時保存（推奨）:** 
  一時的な実験で設定を変更する場合、不揮発（Flash）には保存せず、RAMのみに書き込みます。電源を再投入すれば元の設定に戻ります。（例: `f9p_config_all.py` 実行時に `--no-flash` を指定）
- **Flashへの永続保存:**
  恒久的に設定を変更する場合はFlashへ保存します。設定を元に戻す場合は、正しい座標と設定値を指定して再度 `f9p_config_all.py` を実行し、上書きする必要があります。

---

## 5. ローカルアクセスポイント環境の運用・接続ポイント

本システムは Tailscale 等の VPN に依存せず、Mac 自身が親機ルーター（`192.168.2.1`）となり、有線接続されたアクセスポイント（AP: `192.168.2.3`）を通じて全機器を同一サブネット内で相互通信させます。

1. **Mac 側のネットワーク設定**:
   - USB-LAN アダプタ経由でアクセスポイント（AP）に有線接続。
   - `bridge100` / 有線インターフェースにて `192.168.2.1`（サブネット `255.255.255.0`）を保持し、DHCP サーバー（bootpd）により配下の機器へ `192.168.2.x` を配布。
2. **アクセスポイント（AP: 192.168.2.3）**:
   - ブリッジモードで動作し、ラズパイおよび作業用別PCからの Wi-Fi 接続を中継。
3. **別PC（ノートPC: 192.168.2.2 等）からのアクセス**:
   - AP の Wi-Fi に接続することで、ブラウザから `http://192.168.2.1:9000` にアクセスし、GCS 画面を共有・監視可能。

---

## 6. よくあるトラブルシューティング

| 症状 | 原因 | 確認・解決手順 |
|---|---|---|
| **RTCM を受信しているのに `3D_FIX` のまま昇格しない** | 基地局のアンテナ固定座標（`base_station.json`）と実機の位置が乖離している | 基地局座標が数百mずれていると、搬送波位相の幾何学的計算が成立せず F9P が補正を拒否します。<br>アンテナを動かした場合は、事前に `python3 single_unit_test/run_survey.py --set-rover --duration 30` で現在位置（楕円体高 HAE 含む）を実測し、`gcs/config/base_station.json` の `fixed_pos` に書き込んでください。 |
| **Pixhawk に補正データが注入されない / RTK にならない** | MAVLink 1.0 によるパケット欠損、またはフロー制御（RTS/CTS）なしによるパケット破壊 | ArduPilot への `GPS_RTCM_DATA` 注入には MAVLink 2.0 が必須です。また 921600bps の高速シリアル通信では RTS/CTS が不可欠です。<br>`mavlink_bridge.py` 冒頭の `os.environ["MAVLINK20"] = "1"` と `serial.Serial(..., rtscts=True)` が有効であることを確認してください。 |
| **ラズパイで `ModuleNotFoundError: No module named 'pymavlink'`** | システム python3 や非対応の venv で実行している | ラズパイ側では `pymavlink` や `pyserial` が `~/Mavlink_venv/` 配下に環境構築されています。<br>`~/Mavlink_venv/bin/python3 gcs/rtk_tools/mavlink_bridge.py ...` で実行してください。 |
| **Pixhawk とのシリアルポート接続エラー** | ポート名間違い、または Linux シリアルコンソールの競合 | Raspberry Pi 5 のピンヘッダ UART は `/dev/ttyAMA0` です（`/dev/serial0` ではありません）。<br>開けない場合は `sudo raspi-config` でシリアルコンソールを無効化してください。 |
| **Connect しても機体が表示されない** | UDP:14550 が届いていない、またはポート競合 | 1. ラズパイ側の `--target-host` が Mac のローカル IP（`192.168.2.1`）になっているか確認。<br>2. Mac 側で `gcs.server` が起動しているか確認。<br>3. 他の GCS（QGroundControl 等）が UDP 14550 を占有していないか確認。 |
| **ローカル AP 経由で Mac とラズパイが通信できない** | 有線 LAN リンク切れ、または DHCP 未取得 | 1. Mac の USB-LAN アダプタが AP に接続され、IP が `192.168.2.1` になっているか確認。<br>2. ラズパイが AP の Wi-Fi に接続され、IP（`192.168.2.x`）を取得しているか確認。<br>3. ラズパイ側から `ping 192.168.2.1` が通るか確認してください。 |
| **基地局 TCP サーバー（2101）への再接続でタイムアウトする** | 複数クライアント接続時の受信キュー競合（旧実装バグ） | `gcs/rtk_tools/rtk_base_station_v2.py` のマルチクライアント・ブロードキャスト版を使用してください。 |
| **NTRIP 接続で 401 エラー / 拒否される** | 認証情報の設定不備 | 認証情報は設定ファイル（YAML）に書かず、環境変数 (`NTRIP_USER` / `NTRIP_PASSWORD`) にセットしてください。 |

設定ファイルのスキーマ検証など、ハードウェアなしのシステム検証を行いたい場合は、以下のコマンドを実行します：
```bash
python3 -m gcs.selftest
```

