#!/usr/bin/env python3
"""run_analyze.py — RTK FIXED 到達判定（TTFF・維持時間・std・衛星数）

archive/rtk_field_test/analyze_status.py の thin wrapper。
判定ロジック（FIX 状態遷移・RTK FIXED 到達判定・TTFF・位置安定性）は既存資産を
そのまま import して再利用する（新規に書き起こさない）。

使い方（run_rover.py が出力した RTK 状態 CSV を指定）:
    python3 run_analyze.py logs/rtk_status_YYYYMMDD_HHMMSS.csv

出力に「✅ RTK_FIXED 到達（開始から N 秒後）」が含まれれば再現成功。
「❌ RTK_FIXED 未到達」の場合は FIX 別継続時間・衛星数・基線長を見て切り分ける。
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

import analyze_status  # noqa: E402

if __name__ == "__main__":
    print("[wrapper] 再利用元: archive/rtk_field_test/analyze_status.py")
    sys.exit(analyze_status.main())
