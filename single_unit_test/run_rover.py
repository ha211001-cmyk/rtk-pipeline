#!/usr/bin/env python3
"""run_rover.py — ローバー側: UDP 受信 → MAVLink 注入 + .rtcm3 保存 + RTK 状態 CSV

archive/rtk_field_test/rover_recorder.py の thin wrapper。
MAVLink 接続（mavlink_comm.MavlinkComm）・RTCM 注入（rtcm_injector.RtcmInjector）・
RTK 状態 CSV 記録ロジックは既存資産をそのまま import して再利用する。

使い方（ローバー側ホスト / Raspberry Pi で先に起動する）:
    python3 run_rover.py --rtscts --log-dir logs

    # ポート等を明示する場合
    python3 run_rover.py --port 50010 --mavlink-port /dev/ttyAMA0 --baud 921600 --rtscts

依存: pyserial pymavlink（専用 venv を推奨）
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ARCHIVE = _REPO_ROOT / "archive"
_SRC_DIR = _ARCHIVE / "rtk_field_test"

if not _SRC_DIR.is_dir():
    print("[ERROR] 再利用元が見つかりません: %s" % _SRC_DIR)
    sys.exit(1)

sys.path.insert(0, str(_SRC_DIR))

import rover_recorder  # noqa: E402

if __name__ == "__main__":
    print("[wrapper] 再利用元: archive/rtk_field_test/rover_recorder.py")
    sys.exit(rover_recorder.main())
