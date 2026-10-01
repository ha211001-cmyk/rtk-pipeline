#!/usr/bin/env python3
"""test_f9p_config_monitor.py — f9p_config_monitor の差分エンジンのユニットテスト。

実行:
    python3 -m pytest gcs/rtk_tools/test_f9p_config_monitor.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gcs.rtk_tools.f9p_config_monitor import (  # noqa: E402
    _diff_against_baseline,
    _sanitize_port,
    _baseline_path,
)


def _verify_result(checks):
    return {"role": "base", "port": "/dev/tty.X",
            "device_alive": True, "checks": checks}


def _baseline(keys_map):
    return {"role": "base", "port": "/dev/tty.X", "keys": keys_map}


def test_no_changes():
    checks = [
        {"key": "CFG-TMODE-MODE", "status": "ok", "actual": 2},
        {"key": "CFG-TMODE-POS_TYPE", "status": "ok", "actual": 0},
    ]
    baseline_keys = {
        "CFG-TMODE-MODE": {"actual": 2, "status": "ok"},
        "CFG-TMODE-POS_TYPE": {"actual": 0, "status": "ok"},
    }
    diff = _diff_against_baseline(_verify_result(checks), _baseline(baseline_keys))
    assert diff["has_changes"] is False
    assert diff["unchanged_count"] == 2
    assert diff["changed"] == [] and diff["missing"] == [] and diff["new"] == []


def test_changed_value():
    checks = [{"key": "CFG-TMODE-MODE", "status": "ok", "actual": 0}]
    baseline_keys = {"CFG-TMODE-MODE": {"actual": 2, "status": "ok"}}
    diff = _diff_against_baseline(_verify_result(checks), _baseline(baseline_keys))
    assert diff["has_changes"] is True
    assert len(diff["changed"]) == 1
    assert diff["changed"][0]["key"] == "CFG-TMODE-MODE"
    assert diff["changed"][0]["baseline_actual"] == 2
    assert diff["changed"][0]["current_actual"] == 0


def test_missing_key():
    checks = []  # 現在応答なし
    baseline_keys = {"CFG-TMODE-MODE": {"actual": 2, "status": "ok"}}
    diff = _diff_against_baseline(_verify_result(checks), _baseline(baseline_keys))
    assert diff["has_changes"] is True
    assert len(diff["missing"]) == 1
    assert diff["missing"][0]["key"] == "CFG-TMODE-MODE"


def test_new_key():
    checks = [{"key": "CFG-TMODE-MODE", "status": "ok", "actual": 2}]
    baseline_keys = {}  # ベースラインには存在しない
    diff = _diff_against_baseline(_verify_result(checks), _baseline(baseline_keys))
    assert diff["has_changes"] is True
    assert len(diff["new"]) == 1
    assert diff["new"][0]["key"] == "CFG-TMODE-MODE"


def test_status_not_ok_is_change():
    checks = [{"key": "CFG-TMODE-MODE", "status": "warn", "actual": 2}]
    baseline_keys = {"CFG-TMODE-MODE": {"actual": 2, "status": "ok"}}
    diff = _diff_against_baseline(_verify_result(checks), _baseline(baseline_keys))
    assert diff["has_changes"] is True


def test_sanitize_port_and_baseline_path():
    assert _sanitize_port("/dev/tty.usbmodem114301") == "dev_tty_usbmodem114301"
    p = _baseline_path("base", "/dev/tty.X", custom_dir="/tmp")
    assert p == "/tmp/f9p_config_baseline_base_dev_tty_X.json"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
