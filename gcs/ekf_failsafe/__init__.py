#!/usr/bin/env python3
"""gcs.ekf_failsafe — Phase 3（RTK→EKF 取り込み・フェイルセーフ）飛行試験準備

RTK-FIXED を ArduPilot の EKF に正しく取り込み、飛行中も測位精度を維持しつつ、
測位劣化時にフェイルセーフ（FS）が正しく働くよう、ArduPilot パラメータの
Golden 管理・照合・自動修正と、RTK 喪失時挙動の検証を行うモジュール群。

- ``golden.py``       : Golden 値（EKF ソース群 / フェイルセーフ群）+ 型・ラベル定義
- ``param_guard.py``  : ``ArduPilotParamGuard``（MAVLink 照合・自動修正・RTK 観測）
- ``checklist.py``    : Item 判定（純粋関数）と ``Phase3Report`` チェックリスト整形
- ``runner.py``       : ``Phase3Runner``（52eb5 F9P golden + 本モジュール golden の一括実行）

利用例:
    from gcs.ekf_failsafe.param_guard import ArduPilotParamGuard
    from gcs.ekf_failsafe.checklist import evaluate_ekf_sources, evaluate_failsafe
    from gcs.ekf_failsafe.runner import Phase3Runner
"""

from .golden import (  # noqa: F401
    GROUP_EKF_SOURCES, GROUP_FAILSAFE, GROUP_ORDER, PARAM_GROUPS,
    ALL_PARAM_NAMES, GOLDEN_PARAMS, LABELS, PARAM_TYPES,
    decode_gnss_mode, param_value_repr, synthetic_guard_result,
)
from .param_guard import ArduPilotParamGuard  # noqa: F401
from .checklist import (  # noqa: F401
    ITEM_F9P_GOLDEN, ITEM_EKF_SRC, ITEM_FAILSAFE, ITEM_RTK_LOSS,
    ITEM_ORDER, ITEM_NAMES,
    CheckItem, Phase3Report,
    evaluate_f9p_golden, evaluate_ekf_sources, evaluate_failsafe,
    evaluate_rtk_loss_behavior,
    ekf_position_healthy,
)
from .runner import Phase3Runner, DEFAULT_CONFIG, load_phase3_config  # noqa: F401

__all__ = [
    "GROUP_EKF_SOURCES", "GROUP_FAILSAFE", "GROUP_ORDER", "PARAM_GROUPS",
    "ALL_PARAM_NAMES", "GOLDEN_PARAMS", "LABELS", "PARAM_TYPES",
    "decode_gnss_mode", "param_value_repr", "synthetic_guard_result",
    "ArduPilotParamGuard",
    "ITEM_F9P_GOLDEN", "ITEM_EKF_SRC", "ITEM_FAILSAFE", "ITEM_RTK_LOSS",
    "ITEM_ORDER", "ITEM_NAMES",
    "CheckItem", "Phase3Report",
    "evaluate_f9p_golden", "evaluate_ekf_sources", "evaluate_failsafe",
    "evaluate_rtk_loss_behavior",
    "ekf_position_healthy",
    "Phase3Runner", "DEFAULT_CONFIG", "load_phase3_config",
]
