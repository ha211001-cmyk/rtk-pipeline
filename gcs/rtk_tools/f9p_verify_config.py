#!/usr/bin/env python3
"""f9p_verify_config.py — F9P 設定検証の互換ラッパー（★正典は f9p_config_all.py）。

Phase 0 統合計画に基づき、GCS-UmemotoLab の ``rtk_tools/f9p_verify_config.py``
（CFG-VALGET による基地局・移動局の検証）は ``gcs/rtk_tools/f9p_config_all.py``
の ``F9pAllConfigurator.verify_role()`` に集約する。本モジュールは後方互換の薄いラッパー。
"""

from __future__ import annotations

import logging
from typing import Optional

try:
    from gcs.rtk_tools.f9p_config_all import F9pAllConfigurator, _build_key_table
except ImportError:  # 単体実行時のフォールバック
    from f9p_config_all import F9pAllConfigurator, _build_key_table  # type: ignore

__all__ = ["F9pVerifier"]


class F9pVerifier:
    """F9P 設定検証の互換ラッパー。"""

    def __init__(self, serial_port: str, baudrate: int = 115200,
                 logger: Optional[logging.Logger] = None):
        self.serial_port = serial_port
        self.baudrate = baudrate
        self.logger = logger or logging.getLogger("F9pVerifier")
        self._cfg = F9pAllConfigurator(
            serial_port=serial_port, baudrate=baudrate, logger=self.logger)

    def verify_base(self, lat: float = 0, lon: float = 0, alt: float = 0) -> dict:
        return self._cfg.verify_role("base", _build_key_table(lat, lon, alt))

    def verify_rover(self, lat: float = 0, lon: float = 0, alt: float = 0) -> dict:
        return self._cfg.verify_role("rover", _build_key_table(lat, lon, alt))
