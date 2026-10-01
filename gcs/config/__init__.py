#!/usr/bin/env python3
"""gcs.config — Item 7 一元設定（gcs/config/）

統合テストランナー（gcs/integration/runner.py）が読み込む、座標・ポート・
閾値・PASS/FAIL 判定基準などの一元設定を提供するパッケージ。

利用例:
    from gcs.config import load_config

    cfg = load_config()                # config.yaml（+ config.local.yaml）を読み込み
    cfg = load_config("my_config.yaml")  # 明示パス
"""

from .loader import DEFAULT_CONFIG, load_config  # noqa: F401

__all__ = ["DEFAULT_CONFIG", "load_config"]
