#!/usr/bin/env python3
"""f9p_rover_config.py — F9P 移動局（Rover）設定の互換ラッパー（★正典は f9p_config_all.py）。

Phase 0 統合計画に基づき、GCS-UmemotoLab の ``rtk_tools/f9p_rover_config.py``
（Rover UART2 RTCM3 入力 + GNSS 信号設定）は ``gcs/rtk_tools/f9p_config_all.py``
の ``F9pAllConfigurator`` に集約する。本モジュールは後方互換の薄いラッパー。
"""

from __future__ import annotations

import logging
from typing import Optional

try:
    from gcs.rtk_tools.f9p_config_all import F9pAllConfigurator
except ImportError:  # 単体実行時のフォールバック
    from f9p_config_all import F9pAllConfigurator  # type: ignore

__all__ = ["F9pRoverConfigurator"]


class F9pRoverConfigurator:
    """F9P Rover（UART2 RTCM3 入力 + GNSS）設定の互換ラッパー。"""

    def __init__(self, serial_port: str, baudrate: int = 115200,
                 logger: Optional[logging.Logger] = None):
        self.serial_port = serial_port
        self.baudrate = baudrate
        self.logger = logger or logging.getLogger("F9pRoverConfigurator")
        self._cfg = F9pAllConfigurator(
            serial_port=serial_port, baudrate=baudrate, logger=self.logger)

    def configure_uart2_for_rtcm(self, save_to_flash: bool = True) -> bool:
        return self._cfg.write_rover_uart2(save_to_flash)

    def enable_gnss_signals(self, save_to_flash: bool = True) -> bool:
        return self._cfg.write_rover_gnss(save_to_flash)

    def configure(self, save_to_flash: bool = True) -> dict:
        """旧 ``F9pRoverConfigurator.configure()`` 相当の戻り値スキーマ。"""
        uart2_ok = self.configure_uart2_for_rtcm(save_to_flash)
        return {
            "uart2_rtcm3_configured": uart2_ok,
            "uart2_verified": {},
            "all_ok": uart2_ok,
        }
