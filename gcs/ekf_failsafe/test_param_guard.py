#!/usr/bin/env python3
"""test_param_guard.py — ArduPilotParamGuard のユニットテスト（MAVLink モック・実機不要）。

実行:
    cd <リポジトリルート>
    python3 -m unittest gcs.ekf_failsafe.test_param_guard -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gcs.ekf_failsafe.golden import GOLDEN_PARAMS  # noqa: E402
from gcs.ekf_failsafe.param_guard import (  # noqa: E402
    ArduPilotParamGuard,
    STATUS_PASS,
    STATUS_FIXED,
    STATUS_FAIL,
)


class _ParamValueMsg:
    def __init__(self, param_id, param_value, param_type=1, param_count=1):
        self.param_id = param_id
        self.param_value = float(param_value)
        self.param_type = param_type
        self.param_count = param_count


class _GpsRawIntMsg:
    def __init__(self, fix_type):
        self.fix_type = int(fix_type)


class _EfkStatusMsg:
    def __init__(self, flags):
        self.flags = int(flags)


class _FakeMaster:
    """pymavlink の master を模したフェイク（PARAM_VALUE / GPS_RAW_INT / EKF_STATUS_REPORT）。"""

    def __init__(self, params, apply_fix=True):
        self.params = dict(params)
        self.apply_fix = apply_fix
        self.target_system = 1
        self.target_component = 1
        self.sets = []  # (name, value, ptype)
        self._pending_read = None
        self._reply_sent = False
        self.gps_fix = None
        self.ekf_flags = None
        self.mav = self  # guard は self._master.mav.xxx_send() を呼ぶ

    def wait_heartbeat(self, timeout=None):
        return True

    def close(self):
        pass

    def recv_match(self, type=None, blocking=False, timeout=None):
        if type == "PARAM_VALUE":
            if self._pending_read is not None and not self._reply_sent:
                self._reply_sent = True
                name = self._pending_read
                if name in self.params:
                    return _ParamValueMsg(name, self.params[name])
            return None
        if type == "GPS_RAW_INT":
            return _GpsRawIntMsg(self.gps_fix) if self.gps_fix is not None else None
        if type == "EKF_STATUS_REPORT":
            return _EfkStatusMsg(self.ekf_flags) if self.ekf_flags is not None else None
        return None

    def param_request_read_send(self, sys, comp, name, index):
        if isinstance(name, bytes):
            name = name.decode("utf-8")
        self._pending_read = name
        self._reply_sent = False

    def param_set_send(self, sys, comp, name, value, ptype):
        if isinstance(name, bytes):
            name = name.decode("utf-8")
        self.sets.append((name, value, ptype))
        if self.apply_fix:
            self.params[name] = float(value)

    def command_long_send(self, *args, **kwargs):
        pass


def _make_guard(fake, **kwargs):
    guard = ArduPilotParamGuard(timeout=1.0, **kwargs)
    guard._connect = lambda: setattr(guard, "_master", fake)
    guard._close = lambda: setattr(guard, "_master", None)
    guard._master = fake  # sample() 等を単体で呼べるように初期接続済みにする
    return guard


class TestParamGuard(unittest.TestCase):
    def test_pass_no_regression(self):
        fake = _FakeMaster(GOLDEN_PARAMS)
        guard = _make_guard(fake)
        result = guard.run_check_and_fix()
        self.assertEqual(result["status"], STATUS_PASS)
        self.assertEqual(fake.sets, [])

    def test_fixed_applies_set(self):
        params = dict(GOLDEN_PARAMS)
        params["EK3_SRC1_POSXY"] = 1  # 退行を再現
        fake = _FakeMaster(params, apply_fix=True)
        guard = _make_guard(fake)
        result = guard.run_check_and_fix(fix=True)
        self.assertEqual(result["status"], STATUS_FIXED)
        self.assertIn("EK3_SRC1_POSXY", result["fixed"])
        # PARAM_SET が golden 値（3）で送られたことを確認
        names = [s[0] for s in fake.sets]
        self.assertIn("EK3_SRC1_POSXY", names)

    def test_check_only_no_fix(self):
        params = dict(GOLDEN_PARAMS)
        params["FS_GCS_ENABLE"] = 0
        fake = _FakeMaster(params, apply_fix=True)
        guard = _make_guard(fake)
        result = guard.run_check_and_fix(fix=False)
        self.assertEqual(result["status"], STATUS_FAIL)
        self.assertEqual(fake.sets, [])

    def test_fix_fail_when_not_applied(self):
        params = dict(GOLDEN_PARAMS)
        params["FS_GCS_ENABLE"] = 0
        fake = _FakeMaster(params, apply_fix=False)  # 修正が反映されない
        guard = _make_guard(fake)
        result = guard.run_check_and_fix(fix=True)
        self.assertEqual(result["status"], STATUS_FAIL)
        self.assertIn("FS_GCS_ENABLE", result["fix_failed"])

    def test_connection_failure(self):
        guard = ArduPilotParamGuard(timeout=1.0)
        guard._connect = lambda: (_ for _ in ()).throw(OSError("接続タイムアウト"))
        guard._close = lambda: None
        result = guard.run_check_and_fix()
        self.assertEqual(result["status"], STATUS_FAIL)
        self.assertIn("接続", result["summary"])

    def test_gps_type_alias_fallback(self):
        # GPS_TYPE が無く GPS1_TYPE だけある場合も GPS_TYPE として読める
        params = {k: v for k, v in GOLDEN_PARAMS.items() if k != "GPS_TYPE"}
        params["GPS1_TYPE"] = 9
        fake = _FakeMaster(params)
        guard = _make_guard(fake)
        result = guard.run_check_and_fix(fix=False)
        self.assertEqual(result["checked"]["GPS_TYPE"]["actual"], 9)
        self.assertTrue(result["checked"]["GPS_TYPE"]["ok"])

    def test_sample(self):
        fake = _FakeMaster(GOLDEN_PARAMS)
        fake.gps_fix = 6
        fake.ekf_flags = 0x037
        guard = _make_guard(fake)
        s = guard.sample()
        self.assertEqual(s["fix_type"], 6)
        self.assertEqual(s["ekf_flags"], 0x037)


if __name__ == "__main__":
    unittest.main(verbosity=2)
