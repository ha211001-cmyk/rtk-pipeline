#!/usr/bin/env python3
"""main.py — GCS バックエンド（ヘッドレス）の統合エントリポイント。

Phase 0 統合計画（§6）に基づき、旧 PyQt5 GUI（``gcs.integration.gui``）は
``gcs/_retired/integration_gui_pyqt5/`` へ退避した。以後のメイン UI は
Web ダッシュボード（``python3 -m gcs.server``）であるため、本モジュールは
コンソール監視（ヘッドレス）のバックエンド単体としてのみ動作する。

使い方:
    python3 -m gcs.integration.main --base-port /dev/ttyACM0 --dest 192.168.1.10:14550
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_DEPRECATED_FLAGS = ("--gui", "--no-gui", "--headless")


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # 旧 GUI フラグが残っていても後方互換で無視し、常にヘッドレスで起動する。
    if any(a in _DEPRECATED_FLAGS for a in argv):
        print("[notice] PyQt5 GUI は gcs/_retired/ へ退避しました。"
              " Web ダッシュボードは `python3 -m gcs.server` で起動してください。",
              file=sys.stderr)
        argv = [a for a in argv if a not in _DEPRECATED_FLAGS]

    from gcs.integration.runner import main as headless_main
    return headless_main(argv)


if __name__ == "__main__":
    sys.exit(main())
