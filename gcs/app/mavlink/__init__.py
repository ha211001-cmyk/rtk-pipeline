"""gcs.app.mavlink — MAVLink 通信・メッセージルーティング・GPS ログ。

GCS-UmemotoLab ``app/mavlink/`` を移行したパッケージ。

- ``connection.MavlinkConnection`` : UDP / Serial 接続管理（再接続・バックオフ付き）
- ``message_router.MessageRouter`` : 受信ループとメッセージ分類・ディスパッチ
- ``gps_logger.GpsLogger``         : GPS メッセージの CSV / JSONL 継続ログ
- ``telemetry``                    : メッセージ → 機体状態（flattened）抽出の正典ロジック
                                  （旧 gcs/integration/sources.py の二重実装を一本化）

利用例:
    from gcs.app.mavlink.connection import MavlinkConnection
    from gcs.app.mavlink.message_router import MessageRouter
    from gcs.app.rtk_tools.telemetry_store import TelemetryStore

    mav_conn = MavlinkConnection("config/gcs.yml")
    store = TelemetryStore()
    router = MessageRouter(mav_conn, store)
    router.start()
"""
