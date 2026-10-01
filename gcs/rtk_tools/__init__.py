"""gcs.rtk_tools — F9P 設定・RTCM 検証・設定解決（GCS-UmemotoLab rtk_tools/ 由来）。

Phase 0 統合計画（`gcs/PHASE0_INTEGRATION_PLAN.md` §4 / §7 Phase 4）に基づき、
GCS-UmemotoLab の ``rtk_tools/`` を ``gcs/rtk_tools/`` へ移行し、rtk-pipeline/gcs/ 側の
正典モジュールと一本化した。

正典（canonical）の所在:
- **RTK Fix 判定**    : `gcs/fix_metrics.py`（``gcs_fix_monitor.py`` / ``f9p_fix_monitor.py`` は移行対象外）
- **F9P 設定**        : `f9p_config_all.py`（全30キー write-verify。``f9p_configurator.py`` / ``f9p_rover_config.py`` / ``f9p_verify_config.py`` は薄い互換ラッパー）
- **RTCM 監視・抽出** : `gcs/rtcm_monitor.py`（``verify_rtcm_tcp.py`` はこれを再利用）
- **設定解決**        : `config_loader.py`

モジュール一覧:
- ``config_loader``        : 環境別 YAML 自動選択 + DEFAULT_CONFIG 補完（deep merge）
- ``f9p_config_all``       : ★正典 F9P 設定（基地局12キー+移動局18キー write-verify、TCP/シリアル）
- ``f9p_config_monitor``   : 設定ベースライン差分監視（継続監視）
- ``f9p_configurator``     : 基地局設定の互換ラッパー（f9p_config_all へ委譲）
- ``f9p_rover_config``     : 移動局設定の互換ラッパー
- ``f9p_verify_config``    : 設定検証の互換ラッパー
- ``f9p_relposned_monitor``: UBX-NAV-RELPOSNED carrSoln 監視
- ``fix_monitor_lite``     : fix_metrics 正典を使った RTK FIXED 待機（REST ポーリング）
- ``verify_rtcm_tcp``      : 基地局 TCP ストリームの RTCM3 メッセージタイプ検証
- ``rtk_base_station_v2``  : 基地局統合サービス（TCP:2101 配信 + UDP ブロードキャスト）
- ``rtk_forwarder_service``: RTCM 転送サービス（tcp/ntrip/serial → serial/udp）
- ``rtk_data_collector``   : 基地局+移動局の同時データ収集・誤差分析
- ``tcp2serial``           : TCP→シリアル橋渡し（RTCM 注入用）
"""

# 正典設定ツールを import しやすくするための再公開
try:
    from .f9p_config_all import (  # noqa: F401
        F9pAllConfigurator,
        TcpTransport,
        LAYER_RAM,
        LAYER_BBR,
        LAYER_FLASH,
        LAYER_ALL,
    )
except Exception:  # noqa: BLE001  # pyubx2/pyserial が無い環境でも import を成立させる
    pass

__all__ = [
    "config_loader",
    "f9p_config_all",
    "f9p_config_monitor",
    "f9p_configurator",
    "f9p_rover_config",
    "f9p_verify_config",
    "f9p_relposned_monitor",
    "fix_monitor_lite",
    "verify_rtcm_tcp",
    "rtk_base_station_v2",
    "rtk_forwarder_service",
    "rtk_data_collector",
    "tcp2serial",
]
