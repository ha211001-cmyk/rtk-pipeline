# gcs — 運用操作（GCS 化）の分類・利用ガイド

Phase 2 で一本化した正典ロジック（`gcs.fix_metrics` / `gcs.rtcm_monitor` /
`gcs.rtk_tools.f9p_config_all` / `verify_rtcm_tcp` / `rtk_forwarder_service` /
`tcp2serial` / `rtk_base_station_v2`）を import して再利用し、**SSH で個別 CLI を
叩かずに Web ダッシュボード（REST API + WebSocket）から運用を完結**できるように
するレイヤーです。

- 実装: `gcs/app/operations/`（`manager` / `handlers` / `util`）
- REST: `gcs/app/api/operations.py`（`/api/ops/*` + `/ws/ops`）
- Web UI: `gcs/web/static/js/operations.js` + `index.html` の「⚙️ 運用」タブ

## 1. 操作の分類

### 制御系（既存 REST が担当・本レイヤーでは重複実装しない）

アーム/ディスアーム/離陸/着陸/Guided/RTL/モード切替は `gcs/app/api/routes.py` の
既存エンドポイント（`/api/arm`, `/api/disarm`, `/api/takeoff`, `/api/land`,
`/api/guided/position`, `/api/guided/velocity`, `/api/rtl`, `/api/set_mode`,
`/api/force_arm`）と、カード操作・broadcast パネルが担当します。

### 設定系・監視系・ロギング系・基地局/注入系（本レイヤーが担当）

| 分類 | op_id | 操作 | 正典モジュール | 危険 |
|---|---|---|---|---|
| 設定系 | `f9p_write_verify` | F9P 設定 write-verify（base/rover・Flash+リセット+検証） | `f9p_config_all.F9pAllConfigurator` | ⚠️ |
| 設定系 | `f9p_verify` | F9P 設定検証（読み取りのみ） | `f9p_config_all.F9pAllConfigurator` | |
| 設定系 | `base_tmode3_set` | 基地局座標再測・TMODE3 設定 | `f9p_config_all.F9pAllConfigurator` | ⚠️ |
| 設定系 | `rtcm_rate_set` | RTCM 出力レート変更（CFG-RATE-MEAS） | `pyubx2`（`set_rtcm_rate.py` 相当を再実装） | ⚠️ |
| 設定系 | `glonass_toggle` | GLONASS RTCM（1087/1230）出力 ON/OFF | `pyubx2`（`glonass_toggle.py` 相当を再実装） | ⚠️ |
| 監視系 | `rtk_fix_monitor` | RTK FIX 監視（FIXED 維持率・TTFF・遷移） | `fix_metrics` + `fix_type_logger.UbxPvtReader` | |
| 監視系 | `rtcm_verify_tcp` | 基地局 RTCM ストリーム検証（メッセージタイプ） | `rtcm_monitor.Rtcm3StreamParser` | |
| 監視系 | `rtcm_rover_monitor` | RTCM 到達・CRC・age 監視 | `rtcm_monitor.CorrectionMonitor` | |
| ロギング系 | `ppk_logger` | PPK（RAWX/SFRBX）ログ | `raspberrypi/ppk_logger.py`（subprocess） | |
| ロギング系 | `rtcm_logger` | RTCM 生フレーム記録（.rtcm3） | `rtcm_monitor.Rtcm3StreamParser` | |
| ロギング系 | `gps_fix_log` | GPS / RTK FIX 時系列 CSV 記録＋集計 | `fix_metrics` + `fix_type_logger.UbxPvtReader` | |
| 基地局・注入系 | `forwarder_start` | RTCM 注入・中継（rtk_forwarder_service） | `rtk_forwarder_service.RtcmForwarderService` | |
| 基地局・注入系 | `tcp2serial_start` | TCP→シリアル注入（tcp2serial） | `tcp2serial.Tcp2SerialBridge` | |
| 基地局・注入系 | `base_station_start` | 基地局サービス起動（v2・F9P設定+TCP:2101+UDP任意） | `rtk_base_station_v2.RtkBaseStation` | ⚠️ |

「⚠️ 危険」の操作は Web UI 上で**確認モーダル**を表示します（Flash 書き込み・
基地局座標の上書き・GLONASS 切替・RTCM レート変更・基地局起動）。

## 2. REST API

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/api/ops` | 操作カタログ（カテゴリ・パラメータ・危険フラグ） |
| POST | `/api/ops/{op_id}/start` | 操作開始。`{"params": {...}}` → `{"job_id": ...}` |
| GET | `/api/ops/jobs` | ジョブ一覧 |
| GET | `/api/ops/jobs/{job_id}` | ジョブ詳細（status/progress/logs/result/error） |
| POST | `/api/ops/jobs/{job_id}/stop` | 停止要求（サービス系・継続系を中断） |
| DELETE | `/api/ops/jobs/{job_id}` | 終了済みジョブの除去 |

ジョブの `status` は `PENDING / RUNNING / PASS / FAIL / STOPPED`。`progress`（0..100、
サービス系は不定値）と `logs`（リングバッファ・最大 500 行）で進捗・結果を返します。

## 3. WebSocket

- `/ws/ops` … ジョブ状態の 1Hz ブロードキャスト
  `{"type": "ops", "active": N, "total": N, "jobs": [{id, op_id, status, progress, message, error}]}`

## 4. CLI のまま残すスクリプト（デバッグ・開発・検証専用）

以下は **GCS に載せず CLI のまま**維持します。これらはルーチン運用ではなく、
原因切り分け・開発・受入検証のためのツールです。

| 分類 | スクリプト | 理由 |
|---|---|---|
| デバッグ・検証 | `raspberrypi/test/*`（`debug_rawx_attrs.py`, `debug_rtcm_crc_compare.py`, `test_*`） | 開発・検証専用 |
| デバッグ・検証 | `raspberrypi/gps_statistics_debug.py` | デバッグ専用 |
| 退避済み | `gcs/_retired/**` | Phase 0 統合計画 §6 で退避済み |
| 退避済み | `archive/**`（構成A・旧 Windows 版・各種検証） | 参照用。運用では使用しない |
| 解析・後処理 | `gcs/analyze_fix_log.py` | CSV 後処理（運用中は Web がリアルタイム集計） |
| 解析・後処理 | `gcs/accuracy/*`, `gcs/relpos/*` | 機体間相対測位の実測解析 |
| 飛行試験 | `gcs/flight_test/*` | 実飛行試験の記録・評価 |
| EKF 監視 | `gcs/ekf_failsafe/*` | ArduPilot パラメータ golden 照合（開発検証） |
| 統合テスト | `gcs/integration/*`, `gcs/preflight/*` | 飛行前/統合セルフテスト（CLI runner） |
| デバッグ監視 | `gcs/rtk_tools/f9p_relposned_monitor.py`, `gcs/rtk_tools/fix_monitor_lite.py` | RELPOSNED / REST ポーリング監視 |
| デバッグ監視 | `gcs/dronecan_rtcm_monitor.py` | ローバー側 DroneCAN tunnel 監視（CLI ドライバ） |
| 基地局検証 | `archive/rtk_field_test/set_rtcm_rate.py`, `archive/udp/glonass_toggle.py` | 原因切り分け用（GCS 側は再実装済み） |

## 5. 注意（セキュリティ・安全）

- **認証情報・シークレットはハードコードしない**: NTRIP の `username` / `password`
  は `${NTRIP_USER}` / `${NTRIP_PASSWORD}` の環境変数参照で解決されます
  （`gcs/rtk_tools/rtk_forwarder_service.py` の `_expand_env`）。平文設定は
  `*.example.yml` のみリポジトリにコミットし、実設定は `.gitignore` 対象です。
- **危険操作は確認必須**: `dangerous=True` の操作は Web UI で確認モーダルを出します。
  さらに REST 単体で呼ぶ場合も、運用上は必ず事前に `f9p_verify` で現在値を確認して
  から書き込みを行ってください（write-verify の原則）。
- **RAM のみ / Flash 保存の区別**: 設定系の `save` / `save_to_flash` を OFF にすると
  RAM のみ書き込み（電源再投入で復元）となり、実験後の復元が不要で安全です。
