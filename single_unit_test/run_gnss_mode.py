#!/usr/bin/env python3
"""run_gnss_mode.py — ローバー側 GLONASS の ON/OFF（オプション）

archive/rtk_field_test/set_gnss_mode.py の thin wrapper。
ArduPilot の GNSS_MODE ビット操作ロジックは既存資産をそのまま import して再利用する。

使い方:
    python3 run_gnss_mode.py --no-glonass        # GLONASS 無効化（画面の「元値」を控える）
    python3 run_gnss_mode.py --restore <元値>     # 実験後の復元（必須）

注意:
    GPS_GNSS_MODE は Pixhawk に永続保存される。実験後に必ず --restore で元値へ戻すこと。
    変更反映には Pixhawk / GPS の再起動が必要。
依存: pymavlink
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

import set_gnss_mode  # noqa: E402

if __name__ == "__main__":
    print("[wrapper] 再利用元: archive/rtk_field_test/set_gnss_mode.py")
    sys.exit(set_gnss_mode.main())
