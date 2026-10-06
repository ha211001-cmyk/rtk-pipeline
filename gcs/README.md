# gcs — 統合 GCS（rtk-pipeline / GCS-UmemotoLab 一本化）

u-blox ZED-F9P を使った RTK 測位システムの地上管制（GCS）を一本化したパッケージです。
GCS-UmemotoLab の **Web ダッシュボード（Multi-Drone Dashboard）** をメイン UI とし、
rtk-pipeline 側の判定ロジック（RTK-FIXED 定量判定・RTCM 連続監視）と F9P 設定・RTCM
転送ツールを統合しています。

```text
┌─────────────────────────── gcs ───────────────────────────┐
│  Web UI (gcs/web/static/)  ← ブラウザ / Tailscale          │
│         │ REST / WebSocket                                 │
│  FastAPI backend (gcs/app/)  ← MAVLink 通信・機体制御       │
│         │ import                                          │
│  正典ロジック: fix_metrics / rtcm_monitor / rtk_tools       │
│         │                                                  │
│  設定 (gcs/config/) ・ デプロイ (gcs/deploy/, systemd)      │
└────────────────────────────────────────────────────────────┘
```

## 主な機能

| 機能 | 説明 | 主要ファイル |
|---|---|---|
| **Web ダッシュボード** | 最大 4 機を同時監視（Armed / Mode / バッテリー / RTK Fix / NED）し一斉制御 | `gcs/server.py`, `gcs/app/`, `gcs/web/static/` |
| **運用操作パネル** | 設定・監視・ロギング・基地局/注入を REST + WebSocket で実行 | `gcs/app/operations/`, `gcs/app/api/operations.py` |
| **RTK-FIXED 定量判定** | FIXED 維持率・FLOAT 遷移・TTFF を集計 | `gcs/fix_metrics.py`, `gcs/fix_type_logger.py` |
| **補正データ連続監視** | UBX-RXM-RTCM / RTCM3 CRC / RTK age の途切れ検知 | `gcs/rtcm_monitor.py`, `gcs/dronecan_rtcm_monitor.py` |
| **F9P 設定・RTCM 転送** | 全 30 キー write-verify / RTCM 注入・中継 | `gcs/rtk_tools/` |
| **systemd 常駐化** | RTCM 注入系サービスを Raspberry Pi で常駐起動 | `gcs/deploy/` |

正典（canonical）ロジック:
- **RTK Fix 判定** = `fix_metrics.py`
- **RTCM 監視・抽出** = `rtcm_monitor.py`
- **F9P 設定** = `rtk_tools/f9p_config_all.py`
- **設定解決** = `rtk_tools/config_loader.py`

## ディレクトリ構成

```text
gcs/
├── README.md               # 本ドキュメント
├── server.py               # 単一コマンド起動（python3 -m gcs.server）
├── selftest.py             # 実機不要の自己検証（合成データ）
├── fix_metrics.py          # ★ RTK Fix 判定（正典）
├── fix_type_logger.py      # ライブログ + CSV 出力
├── analyze_fix_log.py      # CSV 後処理
├── rtcm_monitor.py         # ★ RTCM 監視・RTCM3 抽出（正典）
├── dronecan_rtcm_monitor.py# DroneCAN 監視ドライバ
│
├── app/                    # FastAPI バックエンド（REST + WebSocket + MAVLink 制御）
│   ├── api/                # /api/* / /ws/telemetry / /ws/ops
│   ├── mavlink/            # MAVLink 接続・ルーティング
│   ├── operations/         # 運用操作（設定・監視・ロギング・基地局/注入）
│   └── rtk_tools/          # 機体制御（command_dispatcher / guided_control）
├── web/static/             # Web UI（index.html / css / js）
├── rtk_tools/              # F9P 設定・RTCM 転送ツール群（正典）
├── config/                 # 設定・スキーマ検証（README 参照）
├── deploy/                 # systemd サービス・Raspberry Pi セットアップ（README 参照）
├── docs/                   # 運用手順・各機能ドキュメント群
├── backend/                # F9pConfigGuard（後方互換ラッパー）
├── integration/            # 統合テストランナー（Phase 1）
├── preflight/              # 飛行前セルフテスト
├── ekf_failsafe/           # EKF/フェイルセーフ golden 照合
├── flight_test/            # 実飛行試験
├── accuracy/  relpos/      # 機体間相対測位
├── hw_verify/              # 物理ハードウェア検証
└── _retired/               # 退避済み GUI（PyQt5 / Tkinter / 旧 fix 監視）
```

---

## 📂 フォルダ整理ガイド：RTK FIXED ログ取得に使用したスクリプト一覧

本システムで **`RTK_FIXED`（fix_type: 6）を達成し、ログ（CSV / RTCM3）を取得する際に実際に稼働・必須となるファイル群** の一覧です。`gcs/` フォルダの整理や仕分けの基準として参照してください。

### 🏆 1. 直接実行するコアスクリプト（最重要・削除厳禁）

| 実行ホスト | 役割 | ファイルパス | 実行内容・用途 |
|---|---|---|---|
| **Mac (基地局)** | 基地局配信 | [`gcs/rtk_tools/rtk_base_station_v2.py`](file:///Users/taitai0123/rtk-pipeline/gcs/rtk_tools/rtk_base_station_v2.py) | F9Pを基地局設定し、RTCM3をTCP:2101でブロードキャスト配信 |
| **Mac (設定)** | 基地局座標 | [`gcs/config/base_station.json`](file:///Users/taitai0123/rtk-pipeline/gcs/config/base_station.json) | 実測した正確なアンテナ固定座標（lat/lon/alt） |
| **Raspi (中継)** | 中継＆注入 | [`gcs/rtk_tools/mavlink_bridge.py`](file:///Users/taitai0123/rtk-pipeline/gcs/rtk_tools/mavlink_bridge.py) | TCP:2101からRTCM受信、PixhawkへMAVLink2.0/RTS-CTS注入、ログCSV記録 |
| **Mac (GCS)** | Web UI起動 | [`gcs/server.py`](file:///Users/taitai0123/rtk-pipeline/gcs/server.py) | Webダッシュボード起動エントリポイント（port: 9000） |
| **Mac (GCS)** | Web UI画面 | [`gcs/web/static/`](file:///Users/taitai0123/rtk-pipeline/gcs/web/static/) (`index.html`, `js/`, `css/`) | ブラウザにドローンカード・RTK FIXEDバッジを表示するUI |

### 🧩 2. 内部で import されている必須依存モジュール（削除厳禁）

上記コアスクリプトが正常に動作するために内部でインポートされているライブラリ群です：

- **基地局側 (`rtk_base_station_v2.py`) の依存**:
  - [`gcs/rtk_tools/f9p_config_all.py`](file:///Users/taitai0123/rtk-pipeline/gcs/rtk_tools/f9p_config_all.py): F9P の設定を CFG-VALSET で書き込み・全キー検証する正典ロジック。
  - [`gcs/rtk_tools/config_loader.py`](file:///Users/taitai0123/rtk-pipeline/gcs/rtk_tools/config_loader.py): 設定パス解決。
- **GCS サーバー側 (`server.py`) の依存**:
  - `gcs/app/server.py`: FastAPI アプリケーション定義。
  - `gcs/app/api/`: `server.py`（REST API）, `routes.py`（MAVLink接続）, `websocket.py`（テレメトリ配信）, `operations.py`（運用API）。
  - `gcs/app/mavlink/`: `connection.py`（UDP:14550通信）, `message_router.py`（パケット振り分け）。
  - `gcs/app/rtk_tools/`: `telemetry_store.py`（機体ステータス管理）。
  - `gcs/app/display.py`: モード名変換。
  - `gcs/config/gcs.user.local.yml`: GCS 通信設定。

### 🛠️ 3. 検証・実測・解析用ツール（残すことを推奨）

- [`single_unit_test/run_survey.py`](file:///Users/taitai0123/rtk-pipeline/single_unit_test/run_survey.py): 基地局アンテナを移動した際、その場の現在地（HAE楕円体高含む）を自動実測するスクリプト。
- [`gcs/fix_metrics.py`](file:///Users/taitai0123/rtk-pipeline/gcs/fix_metrics.py) & [`gcs/analyze_fix_log.py`](file:///Users/taitai0123/rtk-pipeline/gcs/analyze_fix_log.py): 取得した CSV ログから RTK 維持率や位置標準偏差を事後解析するスクリプト。

### 📦 4. 今回の運用では使用していないファイル（整理・退避候補）

- **別構成の注入サービス**: `gcs/rtk_tools/rtk_forwarder_service.py`（UART4直結注入用）、`gcs/rtk_tools/tcp2serial.py`、`gcs/deploy/` 配下のスクリプト群
- **退避・過去実験コード**: `gcs/_retired/`、`gcs/relpos/`（相対測位実験）、`gcs/ekf_failsafe/`、`gcs/flight_test/`、`gcs/hw_verify/`
- **単体テストコード**: `gcs/**/test_*.py`

---

関連文書: `OPERATIONS.md`（運用操作カタログ）、`PHASE0_INTEGRATION_PLAN.md`（統合計画）、
`config/README.md`、`deploy/README.md`、`RELEASE_CHECKLIST.md`（リリース手順）。

## セットアップ

### 依存ライブラリ

```bash
cd ~/rtk-pipeline
python3 -m venv .venv
source .venv/bin/activate
# Raspberry Pi（Rover 側 / MAVLink ブリッジ）:
#   既存の ~/Mavlink_venv/bin/python3 を使用、または新規作成時:
#   python3 -m venv ~/Mavlink_venv && ~/Mavlink_venv/bin/pip install pymavlink pyserial
```

### 設定

```bash
# 接続設定（serial / udp / drones）
#   既定: gcs/config/gcs.yml（コミット済み）
#   個人差: gcs/config/gcs.user.local.yml に上書き（gitignore 対象）

# 監視・判定基準の統合テスト設定
#   既定: gcs/config/config.yaml
#   個人差: gcs/config/config.local.yaml（テンプレート: config.local.example.yaml）

# 設定の妥当性はスキーマ検証で確認（詳細: gcs/config/README.md）
python3 -c "from gcs.config.schema import validate_bundled_configs; print(validate_bundled_configs())"
```

> 認証情報・シークレットは **環境変数参照（`${NTRIP_USER}` 等）** で扱い、
> YAML に平文で書きません（`gcs/config/README.md` 参照）。

## 起動

### 🚀 実機運用クイックスタート（ローカルネットワーク接続・標準運用）

Mac（地上基地局・GCS・ルーター親機）とアクセスポイント（BUFFALO AP）、Raspberry Pi 5（ドローン搭載機・Pixhawk 接続）、および作業用ノートPC（別PC）を **ローカルネットワーク（Tailscale不要）** で連携し、**RTK-FIXED（サブセンチ精度）達成・リアルタイム監視・実験ロギング・位置誤差標準偏差（std）算出** を完全自動で行う標準運用フローです。

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

#### Step 1: 基地局 RTCM 配信の起動（Mac 側: 192.168.2.1）
Mac の第 1 ターミナルで、基地局 F9P を固定座標モードで起動し TCP:2101 で配信します：
```bash
cd ~/rtk-pipeline-local
source .venv/bin/activate
python3 gcs/rtk_tools/rtk_base_station_v2.py --config gcs/config/base_station.json --serial-port /dev/cu.usbmodem112301
```
*(※ `TCP listening on 0.0.0.0:2101` が出れば待機完了)*

> ⚠️ **【重要】アンテナ設置場所を変更した場合の注意**:
> `base_station.json` に設定する座標は、**実際のアンテナ位置と数メートル以内で一致している必要があります**。数十〜数百メートルのズレがあると幾何学的な位相差の矛盾により Rover F9P が RTK 計算を拒絶し、`3D_FIX` のまま `RTK_FLOAT / FIXED` に入りません。アンテナを移動した際は、事前に `python3 single_unit_test/run_survey.py --set-rover --duration 30` で実測した緯度・経度・高度（楕円体高 HAE）を `base_station.json` に反映してください。

#### Step 2: GCS Web ダッシュボードの起動（Mac 側）
Mac の第 2 ターミナルで、Web サーバーを起動します：
```bash
cd ~/rtk-pipeline-local
source .venv/bin/activate
python3 -m gcs.server --port 9000
```
ブラウザで **http://localhost:9000**（または別PCから **http://192.168.2.1:9000**）を開き、右上の **「Connect」** を 1 回クリックします（データ待機状態）。

#### Step 3: MAVLink ブリッジ & RTK 注入・ロギング起動（Raspberry Pi 側）
ラズパイのターミナルで、統合ブリッジを実行します（デフォルトで Mac の IP `192.168.2.1` に接続します）：
```bash
cd ~/rtk-pipeline-local
~/Mavlink_venv/bin/python3 gcs/rtk_tools/mavlink_bridge.py --serial /dev/ttyAMA0 --baud 921600
```
*(※ ターゲットホストのデフォルトは `192.168.2.1` です。明示する場合は `--target-host 192.168.2.1` を付与してください)*
*(※ `--rtscts`（ハードウェアフロー制御）および `MAVLink 2.0`（`MAVLINK20=1`）が標準で組み込まれており、Pixhawk TELEM1 @ 921600bps での安定通信が担保されています)*
*(※ `pymavlink` や `pyserial` は `~/Mavlink_venv/` 配下にインストールされているため、必ず `~/Mavlink_venv/bin/python3` を使用してください)*

- **実行中の動作**:
  1. Web ダッシュボードが **緑色の「Online」** に切り替わり、姿勢・バッテリー・GPS がリアルタイム表示されます。
  2. 基地局から補正情報が届き、GPS 欄が `3D_FIX` → `DGPS` → `RTK_FLOAT` → **`RTK_FIXED`** へ自動昇格します。
  3. `logs/rtk_status_YYYYMMDD_HHMMSS.csv`（測位時系列）と `logs/rtcm_rover_YYYYMMDD_HHMMSS.rtcm3`（生データ）が自動記録されます。

#### Step 4: 実験終了と標準偏差の自動集計
実験が終わったら、ラズパイのターミナルで **`Ctrl + C`** を 1 回押します。
その場で即座に以下のような **位置誤差の標準偏差・RTK 精度サマリー** が自動集計・出力されます：

```text
==================================================================
 📊 実験ロギング & 位置精度解析サマリー
==================================================================
  CSV ログ      : logs/rtk_status_20260928_214631.csv
  総サンプル数  : 199 点 (208.2 秒間)

  [測位モード内訳]
  ⭐ RTK_FIXED :  199 点 (100.0%)

  [位置誤差の標準偏差 (RTK_FIXED 区間, 199 点)]
  平均緯度 / 経度 : 36.0746333, 136.2096358
  平均高度 (MSL)  : 11.38 m
  --------------------------------------------------
  🎯 水平標準偏差 (1σ) : 0.7 cm (0.0071 m)
     - 緯度方向 (1σ)   : 0.6 cm (0.0056 m)
     - 経度方向 (1σ)   : 0.4 cm (0.0045 m)
  🎯 垂直標準偏差 (1σ) : 0.6 cm (0.0063 m)
  最大水平偏位         : 0.8 cm (0.0077 m)
==================================================================
```

---

### 🌐 ローカルアクセスポイント環境の運用・接続ポイント

本システムは Tailscale 等の VPN に依存せず、Mac 自身が親機ルーター（`192.168.2.1`）となり、有線接続されたアクセスポイント（AP）を通じて全機器を同一サブネット内で相互通信させます。

1. **Mac 側のネットワーク設定**:
   - USB-LAN アダプタ（Lenovo 等）経由でアクセスポイント（AP）に有線接続。
   - `bridge100` / 有線インターフェースにて `192.168.2.1`（サブネット `255.255.255.0`）を保持し、DHCP サーバー（bootpd）により配下の機器へ `192.168.2.x` を配布。
2. **アクセスポイント（AP: 192.168.2.3）**:
   - ブリッジモードで動作し、ラズパイおよび作業用別PCからの Wi-Fi 接続を中継。
3. **別PC（ノートPC: 192.168.2.2 等）からのアクセス**:
   - AP の Wi-Fi に接続することで、ブラウザから `http://192.168.2.1:9000` にアクセスし、GCS 画面を共有・監視可能。
  ```

- **テザリングや自宅 Wi-Fi（学外）に切り替えた場合の解除**:
  学外回線で学内プロキシが残っていると `ProxyError: timed out` になるため、必ず解除してください：
  ```bash
  unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY
  ```

- **Tailscale 通信とプロキシの共存**:
  Tailscale 経由の通信（`100.x.x.x`）やローカル通信（`127.0.0.1`）がプロキシに巻き込まれないよう、必要に応じて除外設定（`no_proxy`）を入れておきます：
  ```bash
  export no_proxy="localhost,127.0.0.1,100.64.0.0/10"
  ```

---

### 単一ホストでの直接起動

```bash
cd ~/rtk-pipeline
source .venv/bin/activate

# 既定（0.0.0.0:8000）
python3 -m gcs.server

# ポート指定
python3 -m gcs.server --port 9000
```

## テスト

単一コマンドで全テストを実行できます（実機不要）。

```bash
cd ~/rtk-pipeline
source .venv/bin/activate

# 全テスト（ユニット + 結合 + 合成データ自己検証）
python3 -m pytest gcs/

# 実機不要の自己検証（合成 RTCM3 / 合成 fix 系列 / 設定スキーマ）
python3 -m gcs.selftest
```

- テストは `pytest` が unittest 形式の既存テストも収集します（`pytest.ini` 参照）。
- ハードウェア不要の検証は `gcs/selftest.py` と `gcs/test_selftest.py` が担当します。
- デプロイ（systemd テンプレート）の検証は `gcs/deploy/test_deploy.py`。
- 設定スキーマ検証は `gcs/config/test_schema.py`。
- 平文シークレットが無いことは `gcs/config/test_no_hardcoded_secrets.py`。

## 操作方法

- **Web UI**: `http://<host>:<port>/` のカードグリッド（最大 4 機）と『ALL DRONES』
  パネルで監視・一斉制御（ARM / DISARM / TAKEOFF / LAND）。
- **運用操作**: ⚙️ 運用タブから設定（F9P write-verify）・監視・ロギング・
  基地局/注入を実行。カタログは `OPERATIONS.md` を参照。
- **CLI**: RTK 判定・監視・F9P 設定は `gcs/rtk_tools/README.md`、各モジュールの
  ヘッダコメントを参照。

## トラブルシューティング（実機運用での主要トラブルと対処法）

| 症状 | 原因 | 確認・解決手順 |
|---|---|---|
| **RTCM を受信しているのに `3D_FIX` のまま昇格しない** | 基地局のアンテナ固定座標（`base_station.json`）と実機の位置が乖離している | 基地局座標が数百mずれていると、搬送波位相の幾何学的計算が成立せず F9P が補正を拒否します。<br>アンテナを動かした場合は、事前に `python3 single_unit_test/run_survey.py --set-rover --duration 30` で現在位置（楕円体高 HAE 含む）を実測し、`gcs/config/base_station.json` の `fixed_pos` に書き込んでください。 |
| **Pixhawk に補正データが注入されない / RTK にならない** | MAVLink 1.0 によるパケット欠損、またはフロー制御（RTS/CTS）なしによるパケット化合 | ArduPilot への `GPS_RTCM_DATA` 注入には MAVLink 2.0 が必須です。また 921600bps の高速シリアル通信では RTS/CTS が不可欠です。<br>`mavlink_bridge.py` 冒頭の `os.environ["MAVLINK20"] = "1"` と `serial.Serial(..., rtscts=True)` が有効であることを確認してください。 |
| **ラズパイで `ModuleNotFoundError: No module named 'pymavlink'`** | システム python3 や非対応の venv で実行している | ラズパイ側では `pymavlink` や `pyserial` が `~/Mavlink_venv/` 配下に環境構築されています。<br>`~/Mavlink_venv/bin/python3 gcs/rtk_tools/mavlink_bridge.py ...` で実行してください。 |
| **Pixhawk とのシリアルポート接続エラー** | ポート名間違い、または Linux シリアルコンソールの競合 | Raspberry Pi 5 のピンヘッダ UART は `/dev/ttyAMA0` です（`/dev/serial0` ではありません）。<br>開けない場合は `sudo raspi-config` → `Interface Options` → `Serial Port` で「login shell over serial: No」「hardware enabled: Yes」になっているか確認してください。 |
| **Web UI で Connect しても機体が表示されない** | UDP:14550 が届いていない、またはポート競合 | 1. ラズパイ側の `--target-host` が Mac のローカル IP（`192.168.2.1`）になっているか確認。<br>2. Mac 側で `python3 -m gcs.server --port 9000` が起動しているか確認。<br>3. 他の GCS（QGroundControl や Mission Planner）が UDP 14550 を占有していないか確認。 |
| **基地局 TCP サーバー（2101）への再接続でタイムアウトする** | 複数クライアント接続時の受信キュー競合（旧実装バグ） | `gcs/rtk_tools/rtk_base_station_v2.py` のマルチクライアント・ブロードキャスト版を使用してください（クライアントごとに独立した Queue を割り当て、自動切断・破棄されるため安定動作します）。 |
| **ローカル AP 経由で Mac とラズパイが通信できない** | 有線 LAN リンク切れ、または DHCP 未取得 | 1. Mac の USB-LAN アダプタが AP に接続され、IP が `192.168.2.1` になっているか確認（`ifconfig`）。<br>2. ラズパイが AP の Wi-Fi に接続され、IP（`192.168.2.x`）を取得しているか確認。<br>3. ラズパイ側から `ping 192.168.2.1` が通るか確認してください。 |
| **Web サーバーが起動しない** | 依存パッケージ不足 | `pip install -r requirements.txt` を実行し、`fastapi` / `uvicorn` がインストールされているか確認してください。 |

## セキュリティ・シークレット

- NTRIP の認証情報は **環境変数参照**（`${NTRIP_USER}` / `${NTRIP_PASSWORD}`）で解決。
- 平文設定は `*.example.yml` のみコミットし、実設定は `.gitignore` 対象。
- 平文シークレットが無いことはテスト（`test_no_hardcoded_secrets.py`）で担保。

## 関連ドキュメント

- `OPERATIONS.md` — 運用操作の分類・REST/WebSocket API
- `PHASE0_INTEGRATION_PLAN.md` — GCS-UmemotoLab 統合計画・移行マップ
- `config/README.md` — 設定ファイル・優先順位・スキーマ検証・シークレット
- `deploy/README.md` — systemd 常駐化・Raspberry Pi セットアップ
- `RELEASE_CHECKLIST.md` — リリース手順・動作確認チェックリスト
- `rtk_tools/README.md` — F9P 設定・RTCM 転送ツール詳細
