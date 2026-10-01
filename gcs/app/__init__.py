"""gcs.app — GCS-UmemotoLab 由来の Web バックエンド（FastAPI + MAVLink 通信）。

Phase 0 統合計画書（gcs/PHASE0_INTEGRATION_PLAN.md §5）に基づき、GCS-UmemotoLab の
``app/`` を rtk-pipeline の ``gcs/app/`` へ移行したパッケージ。

サブパッケージ:
- ``gcs.app.api``      : REST API（/api/*）+ WebSocket（/ws/telemetry）
- ``gcs.app.mavlink``  : MAVLink 接続（UDP/Serial）・メッセージルーティング・GPS ログ
- ``gcs.app.rtk_tools``: テレメトリ保持・コマンドディスパッチ・Guided 制御
- ``gcs.app.display``  : テレメトリ → 表示用 dict の純粋変換（実機不要でテスト可能）

エントリポイント（単一コマンド）:
    python3 -m gcs.server

    # または直接 uvicorn で
    uvicorn gcs.app.server:app --host 0.0.0.0 --port 8000
"""
