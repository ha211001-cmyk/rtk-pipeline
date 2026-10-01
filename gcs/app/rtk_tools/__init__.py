"""gcs.app.rtk_tools — テレメトリ保持・機体制御（GCS-UmemotoLab app/rtk_tools/ 由来）。

- ``telemetry_store.TelemetryStore``   : system_id ごとの最新メッセージ保持
- ``command_dispatcher.CommandDispatcher`` : arm/disarm/takeoff/land + ACK/リトライ
- ``guided_control.GuidedControl``     : Guided 位置/速度制御・屋内 RC override
"""
