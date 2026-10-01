#!/usr/bin/env python3
"""gui.py — GCS 機体ステータス一覧 GUI（PyQt5）

``GcsBackend`` の ``snapshot()`` を定期ポーリングし、機体（system_id）ごとの
ステータス（fix_type・衛星数・フライトモード・バッテリー等）を表形式で一覧表示する。

起動:
    python3 -m gcs.integration.gui --mavlink-port 14550 \\
        --base-port /dev/ttyACM0 --dest 192.168.1.10:14550
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gcs.integration.runner import GcsBackend  # noqa: E402

try:
    from PyQt5 import QtCore, QtWidgets
    HAS_PYQT = True
except ImportError:  # pragma: no cover - 実行環境依存
    QtCore = None
    QtWidgets = None
    HAS_PYQT = False


COLUMNS = [
    ("system_id", "機体ID"),
    ("type", "種別"),
    ("fix", "Fix"),
    ("sats", "衛星数"),
    ("mode", "フライトモード"),
    ("battery", "バッテリー"),
    ("armed", "ARM"),
    ("age", "最終更新"),
]


def format_vehicle_rows(vehicles: Dict[int, Dict[str, Any]],
                        now: Optional[float] = None) -> List[List[Any]]:
    """機体状態 dict を GUI 表示用の行リストへ変換する（テスト可能な純関数）。"""
    now = time.time() if now is None else now
    rows: List[List[Any]] = []
    for sid in sorted(vehicles):
        v = vehicles[sid]
        age = v.get("last_update")
        age_s = ("%.1fs" % (now - age)) if age is not None else "-"
        batt = v.get("battery_voltage_v")
        if batt is not None and v.get("battery_remaining_pct") is not None:
            batt_s = "%.1fV/%d%%" % (batt, v["battery_remaining_pct"])
        elif batt is not None:
            batt_s = "%.1fV" % batt
        else:
            batt_s = "-"
        rows.append([
            sid,
            v.get("vehicle_type_name") or v.get("vehicle_type") or "-",
            v.get("fix_name") or v.get("fix_type") or "-",
            v.get("satellites") if v.get("satellites") is not None else "-",
            v.get("flight_mode") or "-",
            batt_s,
            "ARM" if v.get("armed") else "DISARM",
            age_s,
        ])
    return rows


class GcsMonitorWindow(QtWidgets.QMainWindow if QtWidgets is not None else object):
    """GCS バックエンドの機体ステータスを一覧表示するメインウィンドウ。"""

    def __init__(self, backend: GcsBackend, refresh_ms: int = 500):
        if QtWidgets is None:
            raise ImportError("PyQt5 が必要です: pip install PyQt5")
        super().__init__()
        self.backend = backend
        self.setWindowTitle("GCS 機体ステータスモニタ")
        self.resize(1000, 480)

        self.table = QtWidgets.QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([c[1] for c in COLUMNS])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.setCentralWidget(self.table)

        self.status_label = QtWidgets.QLabel("")
        self.statusBar().addPermanentWidget(self.status_label)

        self._timer = QtCore.QTimer()
        self._timer.timeout.connect(self.refresh)
        self._timer.start(max(200, int(refresh_ms)))

        self.refresh()

    def refresh(self) -> None:
        snap = self.backend.snapshot()
        rows = format_vehicle_rows(snap.get("vehicles", {}))
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                item = QtWidgets.QTableWidgetItem(str(val))
                if c == 0:
                    item.setTextAlignment(QtCore.Qt.AlignCenter)
                self.table.setItem(r, c, item)
        rtcm = snap.get("rtcm", {})
        self.status_label.setText(
            "機体数=%d | RTCM frames=%d sent=%d dests=%d"
            % (len(rows), rtcm.get("frames_read", 0), rtcm.get("frames_sent", 0),
               len(snap.get("rtcm_destinations", []))))

    def closeEvent(self, event) -> None:
        try:
            self.backend.stop()
        except Exception:  # noqa: BLE001
            pass
        super().closeEvent(event)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="GCS 機体ステータス一覧 GUI（PyQt5）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--mavlink-host", default="0.0.0.0")
    p.add_argument("--mavlink-port", type=int, default=14550)
    p.add_argument("--base-port", default=None)
    p.add_argument("--base-baud", type=int, default=115200)
    p.add_argument("--dest", action="append", default=[], metavar="HOST:PORT")
    p.add_argument("--refresh-ms", type=int, default=500)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    if not HAS_PYQT:
        print("[ERROR] PyQt5 が必要です: pip install PyQt5")
        return 1
    args = _build_arg_parser().parse_args(argv)

    destinations = []
    for text in args.dest:
        from gcs.integration.runner import _parse_dest
        try:
            destinations.append(_parse_dest(text))
        except ValueError as e:
            print("[ERROR] %s" % e)
            return 2

    backend = GcsBackend(
        mavlink_host=args.mavlink_host,
        mavlink_port=args.mavlink_port,
        rtcm_source_port=args.base_port,
        rtcm_source_baud=args.base_baud,
        rtcm_destinations=destinations,
    )
    if not backend.start():
        print("[ERROR] GCS バックエンドを起動できませんでした")
        return 2

    app = QtWidgets.QApplication(sys.argv[:1])
    window = GcsMonitorWindow(backend, refresh_ms=args.refresh_ms)
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
