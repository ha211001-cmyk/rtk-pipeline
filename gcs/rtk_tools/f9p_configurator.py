#!/usr/bin/env python3
"""f9p_configurator.py — F9P 基地局設定の互換ラッパー（★正典は f9p_config_all.py）。

Phase 0 統合計画（§4.2 / §7 Phase 4）に基づき、GCS-UmemotoLab の
``rtk_tools/f9p_configurator.py``（基地局 TMODE3 + RTCM3 出力）は
``gcs/rtk_tools/f9p_config_all.py`` の ``F9pAllConfigurator`` に集約する。

本モジュールは後方互換のための薄いラッパーで、旧 ``F9pConfigurator`` と同等の
``configure()`` 呼び出しを ``F9pAllConfigurator`` へ委譲する。新規コードは
``from gcs.rtk_tools.f9p_config_all import F9pAllConfigurator`` を使うこと。
"""

from __future__ import annotations

import logging
from typing import Optional

try:
    from gcs.rtk_tools.f9p_config_all import (
        F9pAllConfigurator,
        LAYER_RAM,
        LAYER_BBR,
        LAYER_FLASH,
        LAYER_ALL,
    )
except ImportError:  # 単体実行時のフォールバック
    from f9p_config_all import (  # type: ignore
        F9pAllConfigurator,
        LAYER_RAM,
        LAYER_BBR,
        LAYER_FLASH,
        LAYER_ALL,
    )

__all__ = [
    "F9pConfigurator",
    "LAYER_RAM",
    "LAYER_BBR",
    "LAYER_FLASH",
    "LAYER_ALL",
]


class F9pConfigurator:
    """F9P 基地局設定の互換ラッパー。

    ``F9pAllConfigurator`` の基地局書き込み（TMODE3 + RTCM3）へ委譲する。
    """

    def __init__(self, serial_port: str, baudrate: int = 38400,
                 logger: Optional[logging.Logger] = None,
                 port_type: str = "both"):
        self.serial_port = serial_port
        self.baudrate = baudrate
        self.port_type = port_type
        self.logger = logger or logging.getLogger("F9pConfigurator")
        self._cfg = F9pAllConfigurator(
            serial_port=serial_port, baudrate=baudrate,
            logger=self.logger, port_type=port_type,
        )

    # 旧 API 互換メソッド
    def configure_tmode3_fixed(self, lat: float, lon: float, alt: float,
                               save_to_flash: bool = True) -> bool:
        return self._cfg.write_base_tmode3(lat, lon, alt, save_to_flash)

    def enable_rtcm3_output(self, save_to_flash: bool = True) -> bool:
        return self._cfg.write_base_rtcm3(save_to_flash)

    def configure(self, lat: float, lon: float, alt: float,
                  save_to_flash: bool = True) -> dict:
        """旧 ``F9pConfigurator.configure()`` 相当の戻り値スキーマで設定する。"""
        results = {
            "step1_tmode3": False,
            "step2_rtcm3": False,
            "step3_check": {},
            "step3b_rtcm": {},
            "all_ok": False,
        }
        results["step1_tmode3"] = self.configure_tmode3_fixed(
            lat, lon, alt, save_to_flash)
        if results["step1_tmode3"]:
            results["step2_rtcm3"] = self.enable_rtcm3_output(save_to_flash)
        results["all_ok"] = (
            results["step1_tmode3"] and results["step2_rtcm3"]
        )
        return results
