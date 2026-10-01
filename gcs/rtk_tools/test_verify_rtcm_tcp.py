#!/usr/bin/env python3
"""test_verify_rtcm_tcp.py — verify_rtcm_tcp の RTCM3 メッセージタイプ検証テスト。

RTCM3 フレーム抽出・メッセージタイプ取得が正典 ``gcs.rtcm_monitor`` を再利用して
いることを検証する（実機・ネットワーク不要）。

実行:
    python3 -m pytest gcs/rtk_tools/test_verify_rtcm_tcp.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gcs.rtcm_monitor import rtcm3_crc24q  # noqa: E402
from gcs.rtk_tools.verify_rtcm_tcp import (  # noqa: E402
    RTCM_MSG_NAMES,
    _KEY_TYPES,
    _frame_message_type,
    verify_rtcm_stream,
)


def _rtcm3_frame(msg_type_12bit: int, payload: bytes = b"\x00\x00\x00\x00") -> bytes:
    """メッセージタイプ（DF002 12bit）を先頭に埋め込んだ RTCM3 フレームを構築する。"""
    # payload[0] = (msg_type >> 4) & 0xFF, payload[1] = (msg_type << 4) & 0xF0
    body = bytes([(msg_type_12bit >> 4) & 0xFF, (msg_type_12bit << 4) & 0xFF]) + payload
    length = len(body)
    header = bytes([0xD3, (length >> 8) & 0x03, length & 0xFF])
    crc = rtcm3_crc24q(header + body)
    return header + body + bytes([(crc >> 16) & 0xFF, (crc >> 8) & 0xFF, crc & 0xFF])


def test_message_type_extraction():
    frame = _rtcm3_frame(1005)
    assert _frame_message_type(frame) == 1005
    assert RTCM_MSG_NAMES[1005] == "Stationary RTK Ref ARP"


def test_key_types_present_in_names():
    for mt in _KEY_TYPES:
        assert mt in RTCM_MSG_NAMES


def test_frame_message_type_returns_none_for_short_frame():
    assert _frame_message_type(b"\xd3") is None


def test_verify_rtcm_stream_connect_failure_returns_ok_false():
    # 未使用ポートへ接続し、即失敗して ok=False になることを確認（ネットワーク不要）。
    result = verify_rtcm_stream("127.0.0.1", 1, duration=0.1)
    assert result["ok"] is False
    assert result["total_frames"] == 0


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
