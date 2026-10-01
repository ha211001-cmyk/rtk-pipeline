"""gcs.app.api — REST API + WebSocket（GCS-UmemotoLab app/api/ 由来）。

- ``server``    : FastAPI アプリ定義（/api/health, /api/drones, /api/telemetry）
- ``routes``    : コマンド/接続管理 REST（/api/connect|disconnect|arm|...|rtl|set_mode）
- ``websocket`` : /ws/telemetry（1Hz broadcast）
- ``rtk_state`` : スレッドセーフ RTK 状態（forwarder stats / F9P fix state）
"""
