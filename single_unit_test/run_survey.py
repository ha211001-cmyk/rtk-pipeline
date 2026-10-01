#!/usr/bin/env python3
"""run_survey.py — 基地局座標の再測（新規場所のみ）

archive/base_station_verify/rtcm_compare/standalone_obs.py の thin wrapper。
判定・測位ロジックは新規実装せず、既存資産をそのまま import して再利用する。

使い方（単独測位で平均座標を取得し、後続 run_base.py の --lat/--lon/--alt に使う）:
    python3 run_survey.py --set-rover --duration 120 --save
    python3 run_survey.py --set-rover --duration 120 --save --port /dev/cu.usbmodemXXXX

備考:
    - --set-rover で一時的に移動局化（TMODE3 を解除）して実測する
    - 出力の「平均高度（楕円体高 HAE）」を --alt に使う（MSL ではない）
    - 依存: pyserial pyubx2 pyyaml
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ARCHIVE = _REPO_ROOT / "archive"
_SRC_DIR = _ARCHIVE / "base_station_verify" / "rtcm_compare"

if not _SRC_DIR.is_dir():
    print("[ERROR] 再利用元が見つかりません: %s" % _SRC_DIR)
    sys.exit(1)

sys.path.insert(0, str(_SRC_DIR))

import standalone_obs  # noqa: E402

if __name__ == "__main__":
    print("[wrapper] 再利用元: archive/base_station_verify/rtcm_compare/standalone_obs.py")
    sys.exit(standalone_obs.main())
