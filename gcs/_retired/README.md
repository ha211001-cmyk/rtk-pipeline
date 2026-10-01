# gcs/_retired — 統合対象外・参照用の退避先

Phase 0 統合計画（`gcs/PHASE0_INTEGRATION_PLAN.md` §5 / §6）に基づき、統合対象外
とした GCS-UmemotoLab 由来のモジュールを参照用に退避する。

## umemotolab_fix_monitors/

RTK Fix 監視の旧実装。判定ロジックの正典は `gcs/fix_metrics.py` に一本化したため、
これらは**移行しない（実行しない）**。将来の差分比較・移行レビュー用の参照コピー。

| ファイル | 元の役割 | 代替（正典） |
|---|---|---|
| `gcs_fix_monitor.py` | GCS REST API ポーリング + carrSoln マッピング | `gcs/fix_metrics.py`（`fix_name` / `ubx_to_fix_type`）＋ `gcs/rtk_tools/fix_monitor_lite.py` |
| `f9p_fix_monitor.py` | UBX-NAV-PVT 直読 Fix 監視（DEPRECATED） | `gcs/fix_metrics.py` |

> 注: これらは `requests` / `pyubx2` に依存する単体スクリプトの参照コピーであり、
> `gcs/` パッケージとして import されない。

## integration_gui_pyqt5/

旧 PyQt5 GUI（`gcs/integration/gui.py` の `GcsMonitorWindow`）。機体ステータス一覧を
`QTableWidget` で表示する GUI だったが、Phase 0 統合計画（§6）に基づき
**Web ダッシュボード（`python3 -m gcs.server`）に置換**し、参照用に退避した。

- 表示行変換の純関数 `format_vehicle_rows` は `gcs/integration/display.py` に移設済み
  （`test_runner.py` が引き続きテスト）。
- `gcs/integration/main.py` は GUI を起動せず、常にヘッドレス（`runner.py`）へ委譲する。

## preflight_gui_tkinter/

旧 Tkinter GUI（`gcs/preflight/gui.py`）。IP+TCP 接続 UI と再接続ボタンを提供する
飛行前セルフテスト GUI だったが、Phase 0 統合計画（§6）に基づき退避した。

- CLI（`gcs/preflight/runner.py`）と `checklist.py` / `session.py` は現状維持
  （GUI 依存なし）。将来 Web ダッシュボードへプレフライトパネルを追加する際の参照。
