"""gcs.app.operations — GCS 運用操作レイヤー（設定・監視・ロギング・基地局/注入）。

Phase 2 で一本化した正典ロジック（``gcs.fix_metrics`` / ``gcs.rtcm_monitor`` /
``gcs.rtk_tools.f9p_config_all`` / ``verify_rtcm_tcp`` / ``rtk_forwarder_service`` /
``tcp2serial`` / ``rtk_base_station_v2``）を import して再利用し、SSH で個別 CLI を
叩かずに Web ダッシュボード（REST API）から実行できるようにする。

構成:
- ``manager``  : バックグラウンド実行・状態管理（``OperationManager`` / ``Job``）
- ``handlers`` : 操作カタログと各ハンドラ実装
- ``util``     : 設定読み込み・シリアルポート自動検出などのヘルパー

制御系（アーム/離陸/Guided/RTL 等）は ``gcs/app/api/routes.py`` の既存
``/api/*`` エンドポイントが担当するため、本パッケージには重複実装しない。
"""

from gcs.app.operations.manager import (
    OperationManager,
    OperationStopped,
    STATUS_PENDING,
    STATUS_RUNNING,
    STATUS_PASS,
    STATUS_FAIL,
    STATUS_STOPPED,
)

__all__ = [
    "OperationManager",
    "OperationStopped",
    "STATUS_PENDING",
    "STATUS_RUNNING",
    "STATUS_PASS",
    "STATUS_FAIL",
    "STATUS_STOPPED",
]
