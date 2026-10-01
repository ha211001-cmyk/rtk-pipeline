#!/usr/bin/env python3
"""test_f9p_config_all.py — gcs.rtk_tools.f9p_config_all のユニットテスト（実機不要）。

実行:
    python3 -m pytest gcs/rtk_tools/test_f9p_config_all.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gcs.rtk_tools.f9p_config_all import (  # noqa: E402
    LAYER_RAM,
    LAYER_BBR,
    LAYER_FLASH,
    LAYER_ALL,
    TcpTransport,
    F9pAllConfigurator,
    _build_key_table,
    _get_keys_by_role,
    _KEY_TMODE_MODE,
    _KEY_UART2_BAUDRATE,
    _KEY_RATE_MEAS,
    _KEY_TMODE_FIXED_POS_ACC,
)

# _parse_single_valget はインスタンスメソッドのため、実機不要のダミーで生成
_PARSE = F9pAllConfigurator(serial_port="/dev/null")._parse_single_valget


def test_layer_constants():
    assert LAYER_RAM == 1
    assert LAYER_BBR == 2
    assert LAYER_FLASH == 4
    assert LAYER_ALL == 7  # RAM + BBR + Flash


def test_key_table_roles():
    tbl = _build_key_table(36.0751418, 136.2133477, 44.80)
    base = _get_keys_by_role(tbl, "base")
    rover = _get_keys_by_role(tbl, "rover")
    assert len(base) == 20
    assert len(rover) == 19
    # 基地局の必須キー（TMODE3 固定モード + RTCM3 出力）を含む
    base_names = {k["key"] for k in base}
    assert "CFG-TMODE-MODE" in base_names
    assert "CFG-MSGOUT-RTCM_3X_TYPE1005_UART1" in base_names
    # 移動局の UART2 入力設定を含む
    rover_names = {k["key"] for k in rover}
    assert "CFG-UART2INPROT-RTCM3X" in rover_names
    assert "CFG-UART2-BAUDRATE" in rover_names


def test_key_table_dynamic_coordinates():
    tbl = _build_key_table(35.0, 139.0, 100.0)
    by_key = {k["key"]: k for k in tbl}
    assert by_key["CFG-TMODE-LAT"]["expected"] == 35_0_000_000  # 35.0 * 1e7
    assert by_key["CFG-TMODE-LON"]["expected"] == 139_0_000_000
    assert by_key["CFG-TMODE-HEIGHT"]["expected"] == 10000  # 100.0m * 100


def _make_ubx_frame(cls: int, mid: int, payload: bytes) -> bytes:
    body = bytes([cls, mid]) + len(payload).to_bytes(2, "little") + payload
    ck_a = ck_b = 0
    for b in body:
        ck_a = (ck_a + b) & 0xFF
        ck_b = (ck_b + ck_a) & 0xFF
    return b"\xb5\x62" + body + bytes([ck_a, ck_b])


def _valget_payload(key_id: int, value_bytes: bytes) -> bytes:
    # [version:1][layer:1][position:2][key:4][value...]
    return bytes([1, 0, 0, 0]) + key_id.to_bytes(4, "little") + value_bytes


def test_parse_single_valget_u1():
    raw = _make_ubx_frame(0x06, 0x8B, _valget_payload(_KEY_TMODE_MODE, bytes([2])))
    key_id, value = _PARSE(raw)
    assert key_id == _KEY_TMODE_MODE
    assert value == 2


def test_parse_single_valget_u4():
    raw = _make_ubx_frame(0x06, 0x8B,
                          _valget_payload(_KEY_UART2_BAUDRATE, (115200).to_bytes(4, "little")))
    key_id, value = _PARSE(raw)
    assert key_id == _KEY_UART2_BAUDRATE
    assert value == 115200


def test_parse_single_valget_u2():
    raw = _make_ubx_frame(0x06, 0x8B,
                          _valget_payload(_KEY_RATE_MEAS, (200).to_bytes(2, "little")))
    key_id, value = _PARSE(raw)
    assert key_id == _KEY_RATE_MEAS
    assert value == 200


def test_parse_single_valget_r8():
    import struct
    raw = _make_ubx_frame(
        0x06, 0x8B,
        _valget_payload(_KEY_TMODE_FIXED_POS_ACC, struct.pack("<d", 10.0)),
    )
    key_id, value = _PARSE(raw)
    assert key_id == _KEY_TMODE_FIXED_POS_ACC
    assert abs(value - 10.0) < 1e-9


def test_tcp_transport_interface_without_connection():
    t = TcpTransport("127.0.0.1", 5001)
    assert t.is_open is False
    assert t.read(10) == b""
    assert t.in_waiting == 0
    t.close()  # no-op で例外にならない
