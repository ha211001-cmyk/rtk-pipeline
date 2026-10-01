# PHASE 0 — GCS-UmemotoLab 機能の rtk-pipeline/gcs/ への統合計画書

> バージョン: 0.1（Phase 0 成果物）
> 作成日: 2026-09-28
> ステータス: **計画確定（実装は Phase 1〜4 で実施）**
> 位置づけ: 本フェーズは調査・計画のみ。既存ファイルの改変・削除は行わない。

---

## 1. 目的とスコープ

- **目的**: 本格 GCS（`KeitaTK/GCS-UmemotoLab`）と rtk-pipeline 内の `gcs/`（判定ロジック＋軽量 GUI）を、
  `rtk-pipeline/gcs/` に一本化し、単一の実用的な GCS にする。
- **統合ベース（確定済み）**: GCS-UmemotoLab の Web ダッシュボード『Multi-Drone Dashboard（`web/static/`）』をメイン UI とする。
- **本フェーズの成果物**: 下記 3 点を文書化する。
  1. 重複ロジック・差分の洗い出し（§3）
  2. 統合方針（重複解消・ディレクトリ構成・削除退避対象）の明文化（§4〜§6）
  3. 後続 Phase 1〜4 でそのまま着手できるファイル単位のマイグレーションマップ（§7）

---

## 2. 確定済みの方向性（ユーザー確認済み）

| 項目 | 確定内容 |
|---|---|
| メイン UI | GCS-UmemotoLab の Web ダッシュボード『Multi-Drone Dashboard』（`web/static/`） |
| カードグリッド | 固定 4 スロット（`MAX_SLOTS=4`）、最大 4 機を同時監視 |
| カード内容 | Armed / Flight Mode / バッテリー / GPS Fix（RTK_FIXED 等）/ NED / RTK 精細制御（Heading/Distance + Go/RTL） |
| ブロードキャスト | 下部パネル『ALL DRONES』: ARM ALL / DISARM ALL / TAKEOFF ALL / LAND ALL |
| テーマ | ダークテーマ（背景 `#1a1a2e`、アクセント `#e67e22`）、Plotly.js グラフ、Vanilla JS |
| バックエンド | FastAPI + REST + WebSocket（`app/api/`, `app/server.py`） |
| PySide6 GUI | 任意のセカンダリ。メインは Web ダッシュボードに一本化（`app/ui/` は移行対象外） |
| 既存 GUI の扱い | `gcs/integration/gui.py`(PyQt5), `gcs/preflight/gui.py`(Tkinter) は Web に置換 → 退避 |

---

## 3. 調査結果：両リポジトリの重複ロジックと差分

### 3.1 rtk-pipeline/gcs/ の現状（判定ロジック＋軽量 GUI）

| モジュール | 役割 | 主要クラス/関数 | 依存 |
|---|---|---|---|
| `fix_metrics.py` | RTK FIXED 定量判定（純粋集計ロジック） | `compute_metrics`, `ubx_to_fix_type`, `FIX_NAMES` | 標準ライブラリのみ |
| `fix_type_logger.py` | ライブログ（MAVLink + UBX 直結）＋CSV | `UbxPvtReader` | `fix_metrics`, archive 資産 |
| `analyze_fix_log.py` | CSV 後処理解析 | `read_series` | `fix_metrics`, archive 資産 |
| `rtcm_monitor.py` | RTCM 補正連続監視（コアライブラリ） | `CorrectionMonitor`, `Rtcm3StreamParser`, `UbxParser`, `RtkAgeMonitor` | 標準ライブラリのみ |
| `dronecan_rtcm_monitor.py` | ローバー側 DroneCAN tunnel 監視ドライバ | `main()` | `rtcm_monitor`, `dronecan` |
| `backend/f9p_configurator.py` | F9P Golden 値退行監視・自動修正 | `F9pConfigGuard`, `TcpTransport` | `pyubx2`, archive `f9p_configurator_v2` |
| `integration/` | GCS バックエンドコア（MAVLink 受信 + RTCM UDP 配信 + PyQt5 GUI） | `MavlinkTelemetryReader`, `RtcmCaster`, `GcsBackend`, `GcsMonitorWindow` | `pymavlink`, `PyQt5` |
| `preflight/` | 飛行前セルフテスト（Item1/2/3 + 基地局レート） | `PreflightRunner`, `TcpSession`, `PreflightApp`(Tkinter) | `backend`, `fix_metrics`, `rtcm_monitor` |
| `config/` | Item 7 一元設定（監視・判定基準） | `load_config` (DEFAULT_CONFIG 補完) | `PyYAML` |
| `ekf_failsafe/` | ArduPilot パラメータ golden 照合（RTK→EKF + FS） | `ArduPilotParamGuard` | `backend`, `preflight` |
| `flight_test/` | 実飛行試験（記録・評価・レポート） | `FlightRecorder`, `compute_ekf_consistency` | `fix_metrics`, `ekf_failsafe` |
| `accuracy/` | 機体間相対測位精度の実測 | `compute_baseline_stats` | `relpos` |
| `relpos/` | 複数ローバー RELPOSNED ペアリング | `pairing` | `pyubx2` |
| `hw_verify/` | 物理ハードウェア実地検証の準備 | `check_connectivity.py` | — |

### 3.2 GCS-UmemotoLab の現状（Web ダッシュボード + 本格 GCS）

| モジュール | 役割 | 主要クラス/関数 | 依存 |
|---|---|---|---|
| `web/static/` | Web ダッシュボード（index.html + css + js 5本） | `renderDroneCard`, `broadcast*`, `updateAlertBar` | Vanilla JS, Plotly.js CDN |
| `app/api/` | FastAPI REST + WebSocket | `routes.py`（コマンド/接続）, `websocket.py`（1Hz broadcast）, `rtk_state.py` | `app/mavlink`, `app/rtk_tools` |
| `app/server.py` | FastAPI エントリ（`app.server:app`） | — | `app/api` |
| `app/main.py` | 起動（`--native`=PySide6 / 既定=Web） | `_setup_tailscale_tunnel` | `app/*` |
| `app/mavlink/` | MAVLink 通信 | `MavlinkConnection`, `MessageRouter` | `pymavlink` |
| `app/rtk_tools/` | 機体制御 | `CommandDispatcher`, `GuidedControl`, `TelemetryStore` | `app/mavlink` |
| `app/ui/` | PySide6 GUI（セカンダリ） | `MainWindow` | PySide6 |
| `rtk_tools/`（ルート直下） | F9P 設定・RTCM 検証・Fix 監視 | `f9p_config_all.py`, `f9p_configurator.py`, `f9p_rover_config.py`, `verify_rtcm_tcp.py`, `gcs_fix_monitor.py`, `f9p_fix_monitor.py`, `rtk_base_station_v2.py`, `rtk_forwarder_service.py` | `pyubx2`, `pyserial` |
| `config/` | 接続設定（YAML） | `gcs.yml`, `gcs_local.yml`, `gcs_production.yml`, `rtk_forwarder.yml` | — |
| `deploy/` | systemd サービス等 | `rtk-uart2-inject.service` | — |
| `tests/` | pytest | `test_command_retry.py` 等 | pytest |

### 3.3 重複ロジックの洗い出し（3 軸）

| 軸 | rtk-pipeline/gcs/ | GCS-UmemotoLab | 関係 |
|---|---|---|---|
| **RTK Fix 判定** | `fix_metrics.py`（純集計・正規化・UBX変換） | `rtk_tools/gcs_fix_monitor.py`（REST API ポーリング＋carrSoln マッピング） / `rtk_tools/f9p_fix_monitor.py`（UBX 直読、**DEPRECATED**） | **重複**（carrSoln/fix_type 正規化が二重定義）。Web は WebSocket で fix_type を直接 push するため、Um 側ポーリング監視は不要 |
| **F9P 設定** | `backend/f9p_configurator.py`（Golden 4 キー退行監視＋TCP/シリアル抽象化） | `rtk_tools/f9p_config_all.py`（基地局12＋移動局18＝全30キー write-verify）＋ `f9p_configurator.py`/`f9p_rover_config.py`/`f9p_verify_config.py`/`f9p_config_monitor.py` | **重複**（退行監視 vs write-verify の概念が分散）。EVK の TCP トランスポートは Um 側に無いユニーク資産 |
| **RTCM 監視** | `rtcm_monitor.py`（CorrectionMonitor：ローバー側 UBX-RXM-RTCM＋RTCM3 フレーム抽出） | `rtk_tools/verify_rtcm_tcp.py`（基地局側 RTCM3 メッセージタイプ解析） | **補完**（監視対象がローバー側 vs 基地局側で異なる）。ただし RTCM3 フレーム抽出・CRC-24Q は共通ロジックで重複 |

---

## 4. 統合方針（一本化方針の明文化）

### 4.1 RTK Fix 判定 → **`gcs/fix_metrics.py` を正典（canonical）とする**

- **採用**: EVK `fix_metrics.py` を RTK Fix 判定の単一ソースとする。
- **理由**:
  1. 標準ライブラリのみ・既存単体テスト（`test_fix_metrics.py`）完備。
  2. `FIX_NAMES`（MAVLink GPS_FIX_TYPE 0..6 正規化）と `ubx_to_fix_type()`（UBX carrSoln→fix_type）を一箇所に集約。
  3. Web ダッシュボードは WebSocket が `gps.fix_type` / `gps.fix_name` を直接配信するため、Um 側 `gcs_fix_monitor.py` の REST ポーリング型監視は冗長。
- **Um 側の扱い**:
  - `rtk_tools/gcs_fix_monitor.py` → 移行しない（`fix_metrics` が役割を吸収。carrSoln マッピングは `ubx_to_fix_type` と重複）。
  - `rtk_tools/f9p_fix_monitor.py` → 既に DEPRECATED のため移行しない（退避参照のみ）。
  - 既存 `fix_type_logger.py` / `analyze_fix_log.py`（ライブログ・後処理）は現状維持（`fix_metrics` を再利用）。

### 4.2 F9P 設定 → **`rtk_tools/f9p_config_all.py` を正典とし、EVK の TCP トランスポートと退行監視スキーマを統合**

- **採用**: Um `f9p_config_all.py`（全 30 キー・`--role base/rover/both`・write-verify）を F9P 設定の単一ツールとする。
- **理由**: 基地局 12 キー＋移動局 18 キーの網羅性・write-verify 自動化・JSON 出力が揃っており、個別スクリプト（`f9p_configurator.py`/`f9p_rover_config.py`/`f9p_verify_config.py`）を置換可能。
- **EVK 側の統合**（Phase 4）:
  - `backend/f9p_configurator.py` の `TcpTransport`（DroneCAN Serial Forwarding の TCP 抽象化）を `f9p_config_all.py` に移植し、シリアル直結に加えて `--host/--port` 経由の TCP 接続を可能にする。
  - `F9pConfigGuard` の「Golden 退行監視（check only→自動修正→再検証）」の戻り値スキーマ（`status/checked/fixed/fix_failed`）は `f9p_config_all.py` の `--mode verify` が機能的にカバー。ただし既存 `preflight/`・`ekf_failsafe/` が `F9pConfigGuard` に依存しているため、**後方互換の薄いラッパー**として `F9pConfigGuard` を残す（内部実装を `f9p_config_all` へ委譲）。
  - 継続監視 `f9p_config_monitor.py`（ベースライン差分）は `f9p_config_all` の verify と組み合わせて維持。

### 4.3 RTCM 監視 → **`gcs/rtcm_monitor.py` を正典（共有ライブラリ）とし、`verify_rtcm_tcp.py` をその上に再実装**

- **採用**: EVK `rtcm_monitor.py`（`CorrectionMonitor` / `Rtcm3StreamParser` / `rtcm3_crc24q` / `UbxParser`）を RTCM3 フレーム抽出・CRC-24Q・UBX-RXM-RTCM パースの共有ライブラリとする。
- **理由**: ローバー側監視（RTK age・CRC・msgUsed）と基地局側検証（メッセージタイプ分布）は対象が異なる補完関係だが、RTCM3 フレーム抽出と CRC-24Q は共通。`rtcm_monitor.py` は標準ライブラリのみで GCS 非依存のため再利用に最適。
- **Um 側の扱い**: `verify_rtcm_tcp.py` は「基地局 TCP:2101 ストリームのメッセージタイプ解析（1005/1006/1074/1084/1094/1124/1230 + RTK 品質評価）」として維持しつつ、`rtcm_monitor.Rtcm3StreamParser` を再利用する形にリファクタ。`dronecan_rtcm_monitor.py` は現状維持。

### 4.4 設定ファイル → **`gcs/config/` に接続設定＋監視判定を統合（2 ファイル体制）**

- Um `config/gcs.yml`（MAVLink 接続：`connection_type` / `drones` / `rtcm`）と EVK `gcs/config/config.yaml`（監視・判定：`monitor` / `pass_criteria` / `base_station`）は**関心が異なる**ため、1 つの `gcs/config/` に同居させる。
- 優先順位解決は Um `rtk_tools/config_loader.py`（`$GCS_CONFIG_PATH` > `gcs.user.local.yml` > `gcs_local.yml` > `gcs.yml`）を拡張し、EVK `config/loader.py` の「DEFAULT_CONFIG 補完（deep merge）」を統合する。

---

## 5. 最終ディレクトリ構成（案）

GCS-UmemotoLab の `app/`・`web/static/`・`rtk_tools/` を `gcs/` 配下に自然にマージする。既存 EVK の判定ロジック（`fix_metrics.py` 等）は `gcs/` 直下に残す。

```
rtk-pipeline/
└── gcs/
    ├── PHASE0_INTEGRATION_PLAN.md   # 本計画書
    ├── __init__.py
    ├── fix_metrics.py               # ★正典: RTK Fix 判定（現状維持）
    ├── fix_type_logger.py           # ライブログ（現状維持）
    ├── analyze_fix_log.py           # 後処理（現状維持）
    ├── rtcm_monitor.py              # ★正典: RTCM3 抽出・CRC-24Q・UBX-RXM-RTCM（現状維持）
    ├── dronecan_rtcm_monitor.py     # DroneCAN 監視ドライバ（現状維持）
    │
    ├── app/                         # ← GCS-UmemotoLab/app/（Web バックエンド）
    │   ├── __init__.py
    │   ├── main.py                  # Web 起動（uvicorn）。--native 分岐は整理
    │   ├── server.py                # FastAPI エントリ（app.server:app）
    │   ├── logging_config.py
    │   ├── dummy_sitl.py            # 任意
    │   ├── api/
    │   │   ├── __init__.py
    │   │   ├── server.py            # /api/health, /api/drones, /api/telemetry
    │   │   ├── routes.py            # /api/connect|disconnect|arm|...|rtl|set_mode
    │   │   ├── websocket.py         # /ws/telemetry（1Hz broadcast）
    │   │   └── rtk_state.py         # スレッドセーフ RTK 状態
    │   ├── mavlink/
    │   │   ├── __init__.py
    │   │   ├── connection.py        # MavlinkConnection（UDP/Serial）
    │   │   ├── message_router.py    # MessageRouter
    │   │   └── gps_logger.py        # 任意
    │   └── rtk_tools/
    │       ├── __init__.py
    │       ├── command_dispatcher.py # コマンド送信（ACK/リトライ）
    │       ├── guided_control.py     # Guided 制御
    │       └── telemetry_store.py    # テレメトリ保持
    │
    ├── web/                         # ← GCS-UmemotoLab/web/static/（メイン UI）
    │   └── static/
    │       ├── index.html
    │       ├── preview.html          # 任意
    │       ├── css/style.css
    │       └── js/{websocket,dashboard,controls,graph,rawdata}.js
    │
    ├── rtk_tools/                   # ← GCS-UmemotoLab/rtk_tools/（F9P 設定等）
    │   ├── config_loader.py         # 設定解決（§4.4 で統合）
    │   ├── f9p_config_all.py        # ★正典: 全30キー write-verify（TcpTransport 統合）
    │   ├── f9p_configurator.py      # 基地局設定（f9p_config_all に集約予定）
    │   ├── f9p_rover_config.py      # Rover 設定（同）
    │   ├── f9p_verify_config.py     # 検証（同）
    │   ├── f9p_config_monitor.py    # 継続監視（維持）
    │   ├── f9p_relposned_monitor.py # RELPOSNED 監視
    │   ├── verify_rtcm_tcp.py       # 基地局ストリーム検証（rtcm_monitor 再利用へ）
    │   ├── rtk_base_station_v2.py   # 基地局統合サービス
    │   ├── rtk_forwarder_service.py # RTCM 転送サービス
    │   ├── rtk_data_collector.py    # RTK データ収集
    │   └── tcp2serial.py            # TCP↔シリアル
    │
    ├── config/                      # ← 接続設定＋監視判定を統合
    │   ├── gcs.yml                  # MAVLink 接続（Um 由来）
    │   ├── gcs_local.yml            # ローカル開発
    │   ├── config.yaml              # 監視・判定（EVK 由来）
    │   └── rtk_forwarder.yml        # RTK 転送
    │
    ├── backend/                     # F9pConfigGuard（後方互換ラッパーへ）
    │   ├── f9p_configurator.py      # 薄いラッパー（内部は f9p_config_all に委譲）
    │   └── test_f9p_configurator.py
    │
    ├── integration/                 # 既存（GUI のみ退避、sources/runner は app/mavlink に置換）
    ├── preflight/                   # 既存（gui.py 退避、runner/checklist は維持）
    ├── ekf_failsafe/                # 既存（維持）
    ├── flight_test/                 # 既存（維持）
    ├── accuracy/                    # 既存（維持）
    ├── relpos/                      # 既存（維持）
    ├── hw_verify/                   # 既存（維持）
    └── _retired/                    # ★退避先（後方参照用にコピー）
        ├── integration_gui_pyqt5/   # gcs/integration/gui.py
        ├── preflight_gui_tkinter/   # gcs/preflight/gui.py
        └── umemotolab_ui_pyside6/   # GCS-UmemotoLab/app/ui/（任意）
```

> 注: 最終配置（`gcs/app/` 等）は **Phase 1 でディレクトリを作成してから**確定させる。本計画書は配置案を定めるもので、本フェーズではディレクトリを新設しない。

---

## 6. 削除・退避対象

| 対象 | 現状 | 方針 | 代替 |
|---|---|---|---|
| `gcs/integration/gui.py`（PyQt5） | 機体ステータス一覧 GUI | **退避**（`gcs/_retired/`） | Web ダッシュボードのカードグリッドが代替 |
| `gcs/preflight/gui.py`（Tkinter） | 飛行前セルフテスト GUI | **退避**（`gcs/_retired/`） | Web ダッシュボードにプレフライトパネルを将来追加（現段階は CLI `runner.py` を維持） |
| GCS-UmemotoLab `app/ui/`（PySide6） | ネイティブ GUI | **移行対象外（任意セカンダリ）** | Web ダッシュボードがメイン。必要なら `gcs/_retired/umemotolab_ui_pyside6/` に参照コピー |
| `gcs/integration/sources.py` の `MavlinkTelemetryReader` | MAVLink UDP 受信 | **置換**（削除は Phase 3 以降） | `gcs/app/mavlink/connection.py` + `message_router.py` + `telemetry_store.py` が代替 |
| `gcs/integration/rtcm_caster.py` の `RtcmCaster` | RTCM UDP ファンアウト | **維持 or 置換を検討** | `rtk_tools/rtk_base_station_v2.py`（TCP 配信）と役割が近い（§8 参照） |
| `gcs/backend/f9p_configurator.py` の `F9pConfigGuard` | Golden 退行監視 | **後方互換ラッパー化**（削除しない） | `rtk_tools/f9p_config_all.py` が代替（preflight/ekf_failsafe が依存） |
| Um `rtk_tools/gcs_fix_monitor.py` / `f9p_fix_monitor.py` | REST ポーリング / UBX 直読 Fix 監視 | **移行しない（退避参照のみ）** | `gcs/fix_metrics.py` が代替 |

---

## 7. ファイル単位のマイグレーションマップ（Phase 1〜4）

各 Phase は「依存関係を満たす順」に並べる。移行先パスは `gcs/` 配下の最終配置（§5）。**移行＝コピー/移植＋ import パス修正**。削除・退避は各 Phase の「後処理」で実施。

### Phase 1: Web フロントエンド移行（静的ファイル、依存なし）

| # | 移行元（GCS-UmemotoLab） | 移行先（rtk-pipeline/gcs/） | 依存 | 順序 | 備考 |
|---|---|---|---|---|---|
| 1 | `web/static/index.html` | `gcs/web/static/index.html` | なし | 1 | タイトル・UI は既存どおり |
| 2 | `web/static/css/style.css` | `gcs/web/static/css/style.css` | index.html | 1 | ダークテーマ継承 |
| 3 | `web/static/js/websocket.js` | `gcs/web/static/js/websocket.js` | index.html | 1 | `/ws/telemetry` 契約を維持 |
| 4 | `web/static/js/dashboard.js` | `gcs/web/static/js/dashboard.js` | websocket.js | 2 | `MAX_SLOTS=4` カード描画 |
| 5 | `web/static/js/controls.js` | `gcs/web/static/js/controls.js` | websocket.js, dashboard.js | 2 | ブロードキャスト/個別制御 |
| 6 | `web/static/js/graph.js` | `gcs/web/static/js/graph.js` | websocket.js | 3 | Plotly.js CDN 前提 |
| 7 | `web/static/js/rawdata.js` | `gcs/web/static/js/rawdata.js` | websocket.js | 3 | Raw Data 表示 |
| 8 | `web/static/preview.html` | （任意）`gcs/web/static/preview.html` | なし | 4 | 移行任意 |

**検証**: Phase 2 のバックエンド起動後にブラウザで `/` を開き、`/ws/telemetry` 接続と 4 カード描画を確認。

### Phase 2: FastAPI バックエンド移行（Web サーバー）

| # | 移行元 | 移行先 | 依存 | 順序 | 備考 |
|---|---|---|---|---|---|
| 1 | `app/logging_config.py` | `gcs/app/logging_config.py` | なし | 1 | ロギング共通 |
| 2 | `app/api/rtk_state.py` | `gcs/app/api/rtk_state.py` | なし | 1 | スレッドセーフ状態 |
| 3 | `app/api/server.py` | `gcs/app/api/server.py` | rtk_state | 2 | REST（health/drones/telemetry） |
| 4 | `app/api/websocket.py` | `gcs/app/api/websocket.py` | api.server | 2 | 1Hz broadcast |
| 5 | `app/api/routes.py` | `gcs/app/api/routes.py` | api.server | 2 | コマンド/接続 REST |
| 6 | `app/api/__init__.py` | `gcs/app/api/__init__.py` | なし | 1 | パッケージ |
| 7 | `app/server.py` | `gcs/app/server.py` | api.* | 3 | `app.server:app` |
| 8 | `app/main.py` | `gcs/app/main.py` | server | 4 | `--native` 分岐を整理（PySide6 参照を除去/遅延化） |
| 9 | `app/dummy_sitl.py` | （任意）`gcs/app/dummy_sitl.py` | なし | 4 | 移行任意 |

**依存（Phase 3 との関係）**: `routes.py` は `app/mavlink` / `app/rtk_tools` を import するため、**Phase 3 完了までは import が解決しない**。Phase 2 ではファイル配置までを行い、動作確認は Phase 3 後とする（または Phase 2+3 を同一 PR で実施）。

### Phase 3: MAVLink 通信・機体制御の移行（Web バックエンドの実体）

| # | 移行元 | 移行先 | 依存 | 順序 | 備考 |
|---|---|---|---|---|---|
| 1 | `app/mavlink/__init__.py` | `gcs/app/mavlink/__init__.py` | なし | 1 | |
| 2 | `app/mavlink/connection.py` | `gcs/app/mavlink/connection.py` | config_loader（§4.4） | 1 | UDP/Serial 接続 |
| 3 | `app/rtk_tools/telemetry_store.py` | `gcs/app/rtk_tools/telemetry_store.py` | なし | 1 | |
| 4 | `app/mavlink/message_router.py` | `gcs/app/mavlink/message_router.py` | connection, telemetry_store | 2 | COMMAND_ACK/STATUSTEXT |
| 5 | `app/rtk_tools/command_dispatcher.py` | `gcs/app/rtk_tools/command_dispatcher.py` | connection | 2 | arm/disarm/takeoff/land/force_arm |
| 6 | `app/rtk_tools/guided_control.py` | `gcs/app/rtk_tools/guided_control.py` | connection | 2 | Guided 位置/速度 |
| 7 | `app/mavlink/gps_logger.py` | （任意）`gcs/app/mavlink/gps_logger.py` | connection | 3 | 移行任意 |

**後処理（EVK 既存との重複解消）**:
- `gcs/integration/sources.py` の `MavlinkTelemetryReader` は `app/mavlink/*` に置換（`integration` 側の参照を `app/mavlink` へ切替。ただし本 Phase では削除せず、`RoverUbxReader` 等の後方互換は `preflight/session.py` が依存するため残置）。
### Phase 4: RTK ツール・重複解消・設定統合

| # | 移行元 | 移行先 | 依存 | 順序 | 備考 |
|---|---|---|---|---|---|
| 1 | `rtk_tools/config_loader.py` | `gcs/rtk_tools/config_loader.py` | なし | 1 | 設定解決（§4.4 で EVK `config/loader.py` の DEFAULT_CONFIG 補完を統合） |
| 2 | `rtk_tools/f9p_config_all.py` | `gcs/rtk_tools/f9p_config_all.py` | pyubx2 | 1 | ★正典 F9P 設定 |
| 3 | `rtk_tools/f9p_configurator.py` | `gcs/rtk_tools/f9p_configurator.py` | f9p_config_all | 2 | 集約 or 薄いラッパー |
| 4 | `rtk_tools/f9p_rover_config.py` | `gcs/rtk_tools/f9p_rover_config.py` | f9p_config_all | 2 | 同 |
| 5 | `rtk_tools/f9p_verify_config.py` | `gcs/rtk_tools/f9p_verify_config.py` | f9p_config_all | 2 | 同 |
| 6 | `rtk_tools/f9p_config_monitor.py` | `gcs/rtk_tools/f9p_config_monitor.py` | f9p_config_all | 3 | 継続監視（維持） |
| 7 | `rtk_tools/verify_rtcm_tcp.py` | `gcs/rtk_tools/verify_rtcm_tcp.py` | `gcs/rtcm_monitor.py` | 3 | RTCM3 抽出を rtcm_monitor 再利用へ |
| 8 | `rtk_tools/f9p_relposned_monitor.py` | `gcs/rtk_tools/f9p_relposned_monitor.py` | pyubx2 | 3 | `gcs/relpos/` と関連（重複なら統合検討） |
| 9 | `rtk_tools/rtk_base_station_v2.py` | `gcs/rtk_tools/rtk_base_station_v2.py` | f9p_config_all | 3 | 基地局サービス |
| 10 | `rtk_tools/rtk_forwarder_service.py` | `gcs/rtk_tools/rtk_forwarder_service.py` | config_loader | 3 | RTCM 転送 |
| 11 | `rtk_tools/rtk_data_collector.py` | `gcs/rtk_tools/rtk_data_collector.py` | pyubx2 | 4 | 任意 |
| 12 | `rtk_tools/tcp2serial.py` | `gcs/rtk_tools/tcp2serial.py` | pyserial | 4 | 任意 |
| 13 | `config/*.yml`（Um） | `gcs/config/` | — | 1 | gcs.yml/gcs_local.yml/rtk_forwarder.yml を統合 |
| 14 | `gcs/backend/f9p_configurator.py`（EVK） | 薄いラッパー化（内部を f9p_config_all へ委譲） | f9p_config_all | 2 | preflight/ekf_failsafe の依存維持 |

**後処理（重複解消）**:
- `gcs/preflight/gui.py`（Tkinter）を `gcs/_retired/preflight_gui_tkinter/` へ退避（`runner.py` / `checklist.py` / `session.py` は維持）。
- Um `rtk_tools/gcs_fix_monitor.py` / `f9p_fix_monitor.py` は移行せず、参考として `gcs/_retired/` に参照コピー（`fix_metrics.py` が代替）。
- GCS-UmemotoLab `app/ui/`（PySide6）は移行対象外（任意）。必要なら参照コピー。

### 移行順序サマリー

```
Phase 1（静的UI）→ Phase 2（API骨格）→ Phase 3（MAVLink/制御）→ Phase 4（RTKツール・重複解消）
        └─ 依存なし      └─ Phase 3 依存      └─ config_loader 依存   └─ fix_metrics / rtcm_monitor / f9p_config_all 正典化
```

---

## 8. 判断に迷う点（選択肢と推奨）

| # | 論点 | 選択肢 | 推奨 | 理由 |
|---|---|---|---|---|
| 1 | RTK Fix 判定の正典 | A) `fix_metrics.py`（EVK） / B) `gcs_fix_monitor.py`（Um） | **A** | 純集計・正規化・UBX変換が集約済み・テスト完備。Web は WebSocket 直接配信でポーリング不要 |
| 2 | F9P 設定の正典 | A) `f9p_config_all.py`（Um）/ B) `F9pConfigGuard`（EVK） | **A** | 全30キー網羅＋write-verify。ただし EVK の TCP トランスポート＋退行監視スキーマは A に統合し、B は後方互換ラッパーとして残す |
| 3 | RTCM 監視の統合 | A) `rtcm_monitor.py` を共有ライブラリ化 / B) 個別維持 | **A** | RTCM3 抽出・CRC-24Q は共通。ローバー側（CorrectionMonitor）と基地局側（verify_rtcm_tcp）で役割を分離 |
| 4 | `RtcmCaster`（EVK, UDP ファンアウト） | A) 維持 / B) `rtk_base_station_v2.py`（TCP）に置換 | **A を維持しつつ評価** | 用途（UDP マルチキャスト vs TCP:2101）が異なる可能性。Phase 4 で実運用を確認して判断 |
| 5 | `app/ui/`（PySide6） | A) 移行対象外 / B) セカンダリとして移行 | **A** | 確定済み方針で「任意のセカンダリ」。メインは Web。必要時は参照コピーのみ |
| 6 | 設定ファイル統合 | A) 単一 `gcs/config/` に 2 ファイル共存 / B) 完全単一 YAML | **A** | 接続設定（gcs.yml）と監視判定（config.yaml）は関心が異なる。deep merge で統合可能 |
| 7 | 既存 GUI（PyQt5/Tkinter） | A) 即時削除 / B) `gcs/_retired/` へ退避 | **B** | 後方参照・差分比較のため。削除は統合完了後に判断 |

---

## 9. 受け入れ基準との対応

| 受け入れ基準 | 本計画書での対応 |
|---|---|
| Web ダッシュボードをメイン UI とする統合方針と、重複解消・ディレクトリ構成が明文化 | §2（確定済み方向性）、§4（統合方針）、§5（ディレクトリ構成） |
| 後続 Phase 1〜4 でそのまま着手できるファイル単位の移行マップ | §7（移行元→移行先・依存関係・順序） |
| 既存ファイルを勝手に改変・削除しない（本フェーズは調査・計画のみ） | §1・§6 に明記。本フェーズの成果物は本計画書（新規ファイル）のみ |

---

## 付録: 主要ファイルの規模・依存早見表

| ファイル | 行数（概算） | 外部依存 | 統合後の位置づけ |
|---|---|---|---|
| `fix_metrics.py` | 327 | なし | ★正典 RTK Fix 判定 |
| `rtcm_monitor.py` | 730 | なし | ★正典 RTCM 監視 |
| `f9p_config_all.py` | 1317 | pyubx2/pyserial | ★正典 F9P 設定 |
| `app/api/routes.py` | 564 | fastapi/pydantic | Web コマンド REST |
| `app/api/websocket.py` | 379 | fastapi | Web テレメトリ push |
| `app/mavlink/connection.py` | 545 | pymavlink/pyserial | MAVLink 接続 |
| `app/rtk_tools/command_dispatcher.py` | 335 | pymavlink | 機体制御 |
| `web/static/js/dashboard.js` | 703 | Vanilla JS | カード描画 |
| `web/static/js/controls.js` | 776 | Vanilla JS | 一斉/個別制御 |
| `web/static/js/websocket.js` | 242 | Vanilla JS | WS 接続/NED 変換 |
