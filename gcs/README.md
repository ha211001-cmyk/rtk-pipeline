# gcs — 統合 GCS（EVK-F9P / GCS-UmemotoLab 一本化）

u-blox ZED-F9P を使った RTK 測位システムの地上管制（GCS）を一本化したパッケージです。
GCS-UmemotoLab の **Web ダッシュボード（Multi-Drone Dashboard）** をメイン UI とし、
EVK-F9P 側の判定ロジック（RTK-FIXED 定量判定・RTCM 連続監視）と F9P 設定・RTCM
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
├── backend/                # F9pConfigGuard（後方互換ラッパー）
├── integration/            # 統合テストランナー（Phase 1）
├── preflight/              # 飛行前セルフテスト
├── ekf_failsafe/           # EKF/フェイルセーフ golden 照合
├── flight_test/            # 実飛行試験
├── accuracy/  relpos/      # 機体間相対測位
├── hw_verify/              # 物理ハードウェア検証
└── _retired/               # 退避済み GUI（PyQt5 / Tkinter / 旧 fix 監視）
```

関連文書: `OPERATIONS.md`（運用操作カタログ）、`PHASE0_INTEGRATION_PLAN.md`（統合計画）、
`config/README.md`、`deploy/README.md`、`RELEASE_CHECKLIST.md`（リリース手順）。

## セットアップ

### 依存ライブラリ

```bash
cd ~/EVK-F9P
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Raspberry Pi（Rover 側）で RTCM 注入サービスを動かす場合:
pip install -r gcs/deploy/requirements_raspi.txt
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

### 🚀 実機運用クイックスタート（Pixhawk TELEM1 接続構成・標準運用）

Mac（地上基地局・GCS）と Raspberry Pi 5（ドローン搭載機・Pixhawk 接続）を **Tailscale (VPN)** で連携し、**RTK-FIXED（サブセンチ精度）達成・リアルタイム監視・実験ロギング・位置誤差標準偏差（std）算出** を完全自動で行う標準運用フローです。

```text
┌───────────────────────── Mac (地上基地局 & GCS) ─────────────────────────┐
│ 1. 基地局 RTCM3 配信 : TCP 2101 (F9P /dev/cu.usbmodem112301)             │
│ 2. Web ダッシュボード : http://localhost:9000 (UDP:14550 受信)            │
└───────────────────▲───────────────────────────────────▲──────────────────┘
                    │ RTCM3 補正データ (Tailscale)       │ MAVLink テレメトリ
┌───────────────────▼───────────────────────────────────┴──────────────────┐
│ mavlink_bridge.py (Raspberry Pi 5)                                       │
│   ├── [1] Pixhawk (/dev/ttyAMA0) ↔ Mac GCS の MAVLink 双方向中継         │
│   ├── [2] Mac 基地局 (TCP:2101) から RTCM3 受信 → Pixhawk へ MAVLink 注入│
│   ├── [3] RTK 測位 CSV & RTCM3 生バイナリの自動保存                      │
│   └── [4] 終了時 (Ctrl+C) に「位置誤差の標準偏差 (1σ)」を自動解析・出力 │
└───────────────────▲──────────────────────────────────────────────────────┘
                    │ MAVLink (TELEM1 @ 921600bps)
┌───────────────────▼───────────────────┐
│ Pixhawk 6C ──(GPS ポート)──> Rover F9P│ (★ RTK-FIXED 達成!)
└───────────────────────────────────────┘
```

#### Step 1: 基地局 RTCM 配信の起動（Mac 側）
Mac の第 1 ターミナルで、基地局 F9P を固定座標モードで起動し TCP:2101 で配信します：
```bash
cd ~/EVK-F9P
python3 gcs/rtk_tools/rtk_base_station_v2.py --config gcs/config/base_station.json --serial-port /dev/cu.usbmodem112301
```
*(※ `TCP listening on 0.0.0.0:2101` が出れば待機完了)*

#### Step 2: GCS Web ダッシュボードの起動（Mac 側）
Mac の第 2 ターミナルで、Web サーバーを起動します：
```bash
cd ~/EVK-F9P
python3 -m gcs.server --port 9000
```
ブラウザで **http://localhost:9000** を開き、右上の **「Connect」** を 1 回クリックします（データ待機状態）。

#### Step 3: MAVLink ブリッジ & RTK 注入・ロギング起動（Raspberry Pi 側）
ラズパイのターミナルで、統合ブリッジを実行します：
```bash
cd ~/EVK-F9P
source .venv/bin/activate
python3 mavlink_bridge.py --target-host 100.80.225.4
```

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

### 🏫 大学・学内 Wi-Fi 環境での運用手順

大学や研究室の Wi-Fi（学内 LAN / eduroam 等）を利用する場合のネットワーク運用ガイドです。

#### 1. Mac ↔ ラズパイ間の通信（Tailscale を推奨）
学内 Wi-Fi はセキュリティ上、**同じ Wi-Fi に接続している端末同士の直接通信（端末間通信）がブロック（AP アイソレーション）されている** ことがほとんどです。
- **解決策**: 学内 Wi-Fi に接続した状態でも、**Mac とラズパイの両方で Tailscale を起動** してください。
- Tailscale は大学の NAT / ファイアウォールを自動で越えて 1 対 1 の暗号化トンネル（）を確立するため、**学内でもテザリング時と全く同じ IP・設定で通信できます**。

#### 2. 学内プロキシ（Proxy）が必要な場合
大学のネットワークポリシーで外部インターネットへのアクセスにプロキシが必要な場合：

- **プロキシ設定の一時適用（pip や git pull 等を実行する際）**:
  ```bash
  export http_proxy="http://proxy.xxxx.ac.jp:ポート番号"
  export https_proxy="http://proxy.xxxx.ac.jp:ポート番号"
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
cd ~/EVK-F9P
source .venv/bin/activate

# 既定（0.0.0.0:8000）
python3 -m gcs.server

# ポート指定
python3 -m gcs.server --port 9000
```

## テスト

単一コマンドで全テストを実行できます（実機不要）。

```bash
cd ~/EVK-F9P
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

## トラブルシューティング

| 症状 | 確認事項 |
|---|---|
| Web サーバーが起動しない | `pip install -r requirements.txt` 済みか、`uvicorn`/`fastapi` が入っているか |
| Connect しても機体が出ない | `gcs/config/` の接続設定（`connection_type` / `endpoint`）と mavlink-router の UDP:14550 を確認 |
| RTCM が Rover に届かない | `systemctl status rtk-uart4-inject.service` と `journalctl -u rtk-uart4-inject.service -f`、基地局 TCP:2101 の疎通、`/dev/ttyAMA4` の有効化 |
| NTRIP 接続で 401/拒否 | `NTRIP_USER` / `NTRIP_PASSWORD` 環境変数が設定されているか（YAML には書かない） |
| 設定が読み込まれない | `GCS_CONFIG_PATH` と優先順位（gcs.user.local.yml > gcs_local.yml > gcs.yml）を確認 |
| テストが失敗する | `python3 -m pytest gcs/ -v` で該当テストを特定、`python3 -m gcs.selftest` で切り分け |

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
