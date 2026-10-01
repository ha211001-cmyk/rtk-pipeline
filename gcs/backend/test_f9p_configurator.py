#!/usr/bin/env python3
"""gcs/backend/f9p_configurator.py のユニットテスト。

実機（F9P / DroneCAN Serial Forwarding）を使わず、F9P の挙動を模したモック
ストリームを注入して、run_check_and_fix() の PASS / FIXED / FAIL 分岐と
UBX-CFG-VALSET の layer=7 永続化を検証する。
"""

import sys
from pathlib import Path

import pytest

# モジュールの import パスを追加
_BACKEND_DIR = Path(__file__).resolve().parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from f9p_configurator import (  # noqa: E402
    F9pConfigGuard,
    GOLDEN_VALUES,
    LAYER_ALL,
    STATUS_FAIL,
    STATUS_FIXED,
    STATUS_PASS,
)
from pyubx2.ubxhelpers import attsiz, cfgname2key  # noqa: E402


# ---------------------------------------------------------------------------
# F9P を模したフェイクストリーム
# ---------------------------------------------------------------------------
class FakeF9pStream:
    """pyserial 風インターフェースで F9P の挙動を再現する。"""

    def __init__(self, current, apply_fix=True, fail_read=False):
        self.current = dict(current)
        self.apply_fix = apply_fix
        self.fail_read = fail_read
        self._rx = bytearray()
        self.writes = []  # 書かれた生バイト列のリスト
        self.valsets = []  # パース済み VALSET（layer, cfg）

        self._sizes = {}
        self._kid2name = {}
        for name in current:
            kid, typ = cfgname2key(name)
            self._kid2name[kid] = name
            self._sizes[kid] = attsiz(typ)

    # -- pyserial 風インターフェース --
    def write(self, data):
        self.writes.append(bytes(data))
        self._handle(bytes(data))

    def flush(self):
        pass

    def read(self, size):
        if self._rx:
            out = bytes(self._rx[:size])
            del self._rx[:size]
            return out
        return b""

    def reset_input_buffer(self):
        self._rx.clear()

    def close(self):
        pass

    # -- UBX ハンドリング --
    def _handle(self, data):
        if len(data) < 8 or data[0:2] != b"\xb5\x62":
            return
        cls, mid = data[2], data[3]
        length = int.from_bytes(data[4:6], "little")
        payload = data[6:6 + length]
        if cls == 0x06 and mid == 0x8B:  # CFG-VALGET（ポーリング要求）
            self._reply_valget()
        elif cls == 0x06 and mid == 0x8A:  # CFG-VALSET（設定）
            self._apply_valset(payload)

    def _reply_valget(self):
        if self.fail_read:
            return  # 応答なし（読取失敗を再現）
        payload = bytearray([1, 0, 0, 0])  # version=1, layer=0(RAM), position=0
        for name, val in self.current.items():
            kid = cfgname2key(name)[0]
            size = attsiz(cfgname2key(name)[1])
            payload += kid.to_bytes(4, "little") + val.to_bytes(size, "little")
        self._rx.extend(self._frame(0x06, 0x8B, bytes(payload)))

    def _apply_valset(self, payload):
        # payload: version(1) + layers(2) + transaction(1) + kv pairs
        layers = int.from_bytes(payload[1:3], "little")
        pos = 4
        cfg = {}
        while pos + 4 <= len(payload):
            kid = int.from_bytes(payload[pos:pos + 4], "little")
            pos += 4
            name = self._kid2name.get(kid)
            size = self._sizes.get(kid, 1)
            if pos + size > len(payload):
                break
            val = int.from_bytes(payload[pos:pos + size], "little")
            pos += size
            if name is not None:
                cfg[name] = val
        self.valsets.append({"layer": layers, "cfg": cfg})
        if self.apply_fix:
            for name, val in cfg.items():
                self.current[name] = val

    @staticmethod
    def _frame(cls, mid, payload):
        body = bytes([cls, mid]) + len(payload).to_bytes(2, "little") + payload
        ck_a = ck_b = 0
        for b in body:
            ck_a = (ck_a + b) & 0xFF
            ck_b = (ck_b + ck_a) & 0xFF
        return b"\xb5\x62" + body + bytes([ck_a, ck_b])


def make_guard(fake, **kwargs):
    guard = F9pConfigGuard(flash_wait_seconds=0, **kwargs)
    guard._open = lambda: setattr(guard, "_stream", fake)
    guard._close = lambda: None
    return guard


# ---------------------------------------------------------------------------
# テスト
# ---------------------------------------------------------------------------
def test_golden_values_dict():
    assert GOLDEN_VALUES == {
        "CFG_NAVHPG_DGNSSMODE": 3,
        "CFG_NAVSPG_DYNMODEL": 7,
        "CFG_RATE_MEAS": 200,
        "CFG_UART1INPROT_RTCM3X": 1,
    }


def test_layer_all_is_7():
    assert LAYER_ALL == 7


def test_pass_no_regression():
    fake = FakeF9pStream(current=dict(GOLDEN_VALUES))
    guard = make_guard(fake)
    result = guard.run_check_and_fix()
    assert result["status"] == STATUS_PASS
    assert fake.valsets == []  # 修正は行わない


def test_fixed_applies_valset_layer7():
    current = dict(GOLDEN_VALUES)
    current["CFG_NAVHPG_DGNSSMODE"] = 0  # 退行を再現
    fake = FakeF9pStream(current=current, apply_fix=True)
    guard = make_guard(fake)
    result = guard.run_check_and_fix()

    assert result["status"] == STATUS_FIXED
    assert result["fixed"] == ["CFG_NAVHPG_DGNSSMODE"]
    assert result["fix_failed"] == []

    # UBX-CFG-VALSET が layer=7（RAM + BBR + Flash）で送られたことを確認
    assert len(fake.valsets) == 1
    assert fake.valsets[0]["layer"] == 7
    assert fake.valsets[0]["cfg"]["CFG_NAVHPG_DGNSSMODE"] == 3


def test_fix_fail_returns_fail():
    current = dict(GOLDEN_VALUES)
    current["CFG_RATE_MEAS"] = 1000  # 退行を再現
    fake = FakeF9pStream(current=current, apply_fix=False)  # 修正が反映されない
    guard = make_guard(fake)
    result = guard.run_check_and_fix()

    assert result["status"] == STATUS_FAIL
    assert result["fix_failed"] == ["CFG_RATE_MEAS"]
    assert result["fixed"] == []


def test_check_only_no_fix():
    current = dict(GOLDEN_VALUES)
    current["CFG_UART1INPROT_RTCM3X"] = 0
    fake = FakeF9pStream(current=current)
    guard = make_guard(fake)
    result = guard.run_check_and_fix(fix=False)

    assert result["status"] == STATUS_FAIL
    assert fake.valsets == []  # 修正は行わない


def test_connection_failure():
    guard = F9pConfigGuard(flash_wait_seconds=0)
    guard._open = lambda: (_ for _ in ()).throw(OSError("接続タイムアウト"))
    guard._close = lambda: None
    result = guard.run_check_and_fix()
    assert result["status"] == STATUS_FAIL
    assert "接続" in result["summary"]


def test_read_failure():
    fake = FakeF9pStream(current=dict(GOLDEN_VALUES), fail_read=True)
    guard = make_guard(fake)
    result = guard.run_check_and_fix()
    assert result["status"] == STATUS_FAIL


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
