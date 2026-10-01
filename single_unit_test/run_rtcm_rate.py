#!/usr/bin/env python3
"""run_rtcm_rate.py — 基地局 F9P の RTCM 出力レート変更（オプション）

archive/rtk_field_test/set_rtcm_rate.py の thin wrapper。
CFG_RATE_MEAS の読み書き・検証ロジックは既存資産をそのまま import して再利用する。

使い方:
    python3 run_rtcm_rate.py --rate 1             # 1Hz に変更（RAM のみ）
    python3 run_rtcm_rate.py --restore 200        # 200ms（=5Hz）へ復元
    python3 run_rtcm_rate.py --rate 1 --save      # Flash にも保存（永続化）

既定は RAM のみ（電源再投入で自動復元）。--save を付けると Flash にも保存される。
依存: pyserial pyubx2
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

import set_rtcm_rate  # noqa: E402

if __name__ == "__main__":
    print("[wrapper] 再利用元: archive/rtk_field_test/set_rtcm_rate.py")
    sys.exit(set_rtcm_rate.main())
