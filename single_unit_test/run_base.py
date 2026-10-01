#!/usr/bin/env python3
"""run_base.py — 基地局 F9P: TMODE3/RTCM3 設定 + RTCM 出力 + .rtcm3 保存（＋ UDP 送信）

archive/rtk_field_test/base_recorder.py の thin wrapper。
基地局設定（f9p_configurator_v2.py）・RTCM フレーム抽出・UDP 送信ロジックは
既存資産をそのまま import して再利用する（新規二重実装しない）。

使い方:
    # 新規場所: 座標を指定して基地局を設定（Flash 保存 → 自動再検出）してから記録 + UDP 送信
    python3 run_base.py --lat <新緯度> --lon <新経度> --alt <新高度HAE>

    # RAM のみで設定（Flash に残さない）
    python3 run_base.py --lat <新緯度> --lon <新経度> --alt <新高度HAE> --no-save

    # 設定済みの基地局をそのまま記録（座標指定なし）
    python3 run_base.py

    # 記録のみ（UDP 送信なし / シリアル直結の代案で使用）
    python3 run_base.py --no-udp

    # 送信先を明示（mDNS が効かない場合）
    python3 run_base.py --host 192.168.11.50 --port 50010

依存: pyserial（基地局設定時は pyubx2 も必要）
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

import base_recorder  # noqa: E402

if __name__ == "__main__":
    print("[wrapper] 再利用元: archive/rtk_field_test/base_recorder.py")
    sys.exit(base_recorder.main())
