#!/usr/bin/env python3
"""fix_type_logger.py — RTK fix_type 時系列のライブログ＋リアルタイム集計

Phase 1 ゴール「地上で安定して RTK-FIXED を定量判定」のためのライブロガー。

以下の 2 ソースを併用して fix_type を記録し、リアルタイム表示と CSV 出力を行う:

  - MAVLink GPS_RAW_INT.fix_type   （ArduPilot / Pixhawk 経由。RTK_FLOAT=5, RTK_FIXED=6）
  - UBX-NAV-PVT の fixType / flags.carrSoln / flags.diffSoln（F9P 直結。carrSoln 2=固定, 1=float）

集計（FIXED 維持率・FLOAT 遷移回数・遷移タイムスタンプ・TTFF）は fix_metrics.py を
再利用し、リアルタイムに表示する。CSV は 1 サンプル 1 行で fix_type 時系列を保存する。

既存資産の再利用:
  - archive/rtk_base_mavlink/mavlink_comm.py の MavlinkComm（MAVLink 受信）
  - archive/udp/base_ubx_logger.py の auto_detect_port（UBX シリアルポート自動検出）

使い方:
    # MAVLink のみ
    python3 fix_type_logger.py --mavlink-port /dev/ttyAMA0

    # UBX のみ（F9P 直結・ポート自動検出）
    python3 fix_type_logger.py --no-mavlink --ubx-port /dev/cu.usbmodemXXXX

    # 両方併用
    python3 fix_type_logger.py --mavlink-port /dev/ttyAMA0 --ubx-port /dev/cu.usbmodemXXXX

    # 集計ロジックのみ自己検証
    python3 fix_type_logger.py --selftest
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
_GCS_DIR = Path(__file__).resolve().parent

# fix_metrics を import パスに追加
sys.path.insert(0, str(_GCS_DIR))
from fix_metrics import (  # noqa: E402
    compute_metrics,
    fix_name,
    format_metrics,
    ubx_to_fix_type,
)

# 既存資産（archive/rtk_base_mavlink / archive/udp）を import パスに追加
_MAVLINK_DIR = _REPO_ROOT / "archive" / "rtk_base_mavlink"
_UDP_DIR = _REPO_ROOT / "archive" / "udp"
if _MAVLINK_DIR.is_dir():
    sys.path.insert(0, str(_MAVLINK_DIR))
if _UDP_DIR.is_dir():
    sys.path.insert(0, str(_UDP_DIR))

try:
    from mavlink_comm import MavlinkComm  # noqa: E402
except ImportError:
    MavlinkComm = None

try:
    from base_ubx_logger import auto_detect_port  # noqa: E402
except ImportError:
    auto_detect_port = None

DEFAULT_MAVLINK_PORT = "/dev/ttyAMA0"
DEFAULT_MAVLINK_BAUD = 921600
DEFAULT_UBX_BAUD = 115200

CSV_FIELDS = [
    "timestamp", "elapsed_sec",
    "mavlink_fix_type", "mavlink_fix_name",
    "ubx_fix_type", "ubx_carr_soln", "ubx_diff_soln",
    "merged_fix_type", "merged_fix_name",
]


class UbxPvtReader:
    """F9P 直結シリアルから UBX-NAV-PVT をポーリングして最新状態を保持する。

    carrSoln / diffSoln は NAV-PVT の flags ビットフィールド由来で、pyubx2 が
    フラットな属性（parsed.carrSoln / parsed.diffSoln）として展開する。
    """

    def __init__(self, port: str, baud: int = DEFAULT_UBX_BAUD,
                 poll_interval: float = 1.0):
        self.port = port
        self.baud = baud
        self.poll_interval = poll_interval
        self._ser = None
        self._ubr = None
        self._running = False
        self._thread = None
        self._fix_type: Optional[int] = None
        self._carr_soln: Optional[int] = None
        self._diff_soln: Optional[int] = None
        self._num_sv: Optional[int] = None
        self._updated = False

    def start(self) -> bool:
        try:
            import serial  # noqa: PLC0415
            from pyubx2 import UBXMessage, UBXReader, POLL  # noqa: PLC0415
        except ImportError as e:
            print("[UBX] 依存ライブラリ不足: %s (pyserial/pyubx2 が必要)" % e)
            return False

        try:
            self._ser = serial.Serial(self.port, self.baud, timeout=1.0)
            self._ubr = UBXReader(self._ser)
        except Exception as e:  # noqa: BLE001
            print("[UBX] シリアル接続に失敗: %s" % e)
            return False

        self._running = True
        import threading  # noqa: PLC0415
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print("[UBX] NAV-PVT ポーリング開始: %s @ %d bps" % (self.port, self.baud))
        return True

    def _loop(self) -> None:
        from pyubx2 import UBXMessage, POLL  # noqa: PLC0415

        while self._running:
            try:
                self._ser.write(UBXMessage("NAV", "NAV-PVT", POLL).serialize())
            except Exception:  # noqa: BLE001
                pass

            parsed = None
            try:
                _raw, parsed = self._ubr.read()
            except Exception:  # noqa: BLE001
                parsed = None

            if parsed is not None and parsed.identity == "NAV-PVT":
                self._fix_type = getattr(parsed, "fixType", None)
                self._carr_soln = getattr(parsed, "carrSoln", None)
                self._diff_soln = getattr(parsed, "diffSoln", None)
                self._num_sv = getattr(parsed, "numSV", None)
                self._updated = True
            time.sleep(self.poll_interval)

    def latest(self) -> Dict[str, Any]:
        return {
            "fix_type": self._fix_type,
            "carr_soln": self._carr_soln,
            "diff_soln": self._diff_soln,
            "num_sv": self._num_sv,
            "updated": self._updated,
        }

    def close(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        if self._ser:
            try:
                self._ser.close()
            except Exception:  # noqa: BLE001
                pass


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="RTK fix_type 時系列ライブログ＋リアルタイム集計",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--mavlink-port", default=DEFAULT_MAVLINK_PORT, help="Pixhawk MAVLinkポート")
    p.add_argument("--baud", type=int, default=DEFAULT_MAVLINK_BAUD, help="MAVLinkボーレート")
    p.add_argument("--rtscts", action=argparse.BooleanOptionalAction, default=True,
                   help="MAVLink RTS/CTSフロー制御（既定: 有効）")
    p.add_argument("--no-mavlink", action="store_true", help="MAVLink を使用しない")
    p.add_argument("--ubx-port", default=None,
                   help="UBX F9P シリアルポート（省略時は自動検出）")
    p.add_argument("--ubx-baud", type=int, default=DEFAULT_UBX_BAUD, help="UBXボーレート")
    p.add_argument("--no-ubx", action="store_true", help="UBX を使用しない")
    p.add_argument("--csv", default=None,
                   help="CSV出力先（省略時: gcs/logs/fix_type_<ts>.csv）")
    p.add_argument("--interval", type=float, default=1.0, help="サンプリング間隔(秒)")
    p.add_argument("--display-interval", type=float, default=5.0,
                   help="リアルタイム集計表示の間隔(秒)")
    p.add_argument("--duration", type=float, default=0.0,
                   help="記録秒数（0 で無限。Ctrl+C で停止）")
    p.add_argument("--selftest", action="store_true", help="集計ロジックの自己検証のみ実行")
    return p


def resolve_ubx_port(explicit: Optional[str]) -> Optional[str]:
    if explicit:
        return explicit
    if auto_detect_port is not None:
        return auto_detect_port()
    return None


def main() -> int:
    args = build_parser().parse_args()

    if args.selftest:
        from fix_metrics import self_test
        ok = self_test()
        print("fix_type_logger selftest: %s" % ("OK" if ok else "FAILED"))
        return 0 if ok else 1

    use_mavlink = (not args.no_mavlink) and MavlinkComm is not None
    use_ubx = not args.no_ubx

    # CSV 出力先
    if args.csv is None:
        log_dir = _GCS_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.csv = str(log_dir / ("fix_type_%s.csv" % ts))

    csv_fh = open(args.csv, "w", newline="")
    writer = csv.DictWriter(csv_fh, fieldnames=CSV_FIELDS)
    writer.writeheader()
    csv_fh.flush()
    print("[LOG] CSV: %s" % args.csv)

    # --- MAVLink 接続 ---
    mavlink = None
    if use_mavlink:
        mavlink = MavlinkComm(port=args.mavlink_port, baud=args.baud, rtscts=args.rtscts)
        if not mavlink.connect():
            print("[WARN] MAVLink 接続に失敗（MAVLink をスキップ）: %s" % args.mavlink_port)
            mavlink = None
        else:
            mavlink.start_gps_stream()
            time.sleep(1)

    # --- UBX 接続 ---
    ubx = None
    if use_ubx:
        port = resolve_ubx_port(args.ubx_port)
        if not port:
            print("[WARN] UBX ポートを検出できません（--ubx-port で明示指定）")
        else:
            ubx = UbxPvtReader(port, baud=args.ubx_baud, poll_interval=args.interval)
            if not ubx.start():
                ubx = None

    if mavlink is None and ubx is None:
        print("[ERROR] 有効な入力ソースがありません（MAVLink / UBX を確認）")
        csv_fh.close()
        return 1

    print("=" * 60)
    print("RTK fix_type ライブログ開始（Ctrl+C で停止）")
    print("=" * 60)

    series: list = []
    start_time = time.time()
    last_sample = 0.0
    last_display = 0.0
    prev_merged: Optional[int] = None

    try:
        while True:
            now = time.time()
            elapsed = now - start_time
            if args.duration > 0 and elapsed >= args.duration:
                break
            if now - last_sample < args.interval:
                time.sleep(0.05)
                continue
            last_sample = now

            mav_fix: Optional[int] = None
            mav_name: Optional[str] = None
            ubx_fix: Optional[int] = None
            ubx_carr: Optional[int] = None
            ubx_diff: Optional[int] = None
            merged: Optional[int] = None

            if mavlink is not None:
                pos = mavlink.get_gps_position()
                if pos.get("updated"):
                    mav_fix = int(pos.get("fix_type", 0))
                    mav_name = pos.get("fix_name")

            if ubx is not None:
                u = ubx.latest()
                if u.get("updated"):
                    ubx_fix = u.get("fix_type")
                    ubx_carr = u.get("carr_soln")
                    ubx_diff = u.get("diff_soln")

            # マージ: MAVLink を優先、無ければ UBX carrSoln から変換
            if mav_fix is not None:
                merged = mav_fix
            elif ubx_fix is not None:
                merged = ubx_to_fix_type(ubx_fix, ubx_carr if ubx_carr is not None else 0,
                                         ubx_diff)
            else:
                continue  # どちらも未更新なら記録しない

            merged_name = fix_name(merged)
            row = {
                "timestamp": datetime.now().strftime("%H:%M:%S.%f")[:-3],
                "elapsed_sec": "%.2f" % elapsed,
                "mavlink_fix_type": mav_fix if mav_fix is not None else "",
                "mavlink_fix_name": mav_name or "",
                "ubx_fix_type": ubx_fix if ubx_fix is not None else "",
                "ubx_carr_soln": ubx_carr if ubx_carr is not None else "",
                "ubx_diff_soln": ubx_diff if ubx_diff is not None else "",
                "merged_fix_type": merged,
                "merged_fix_name": merged_name,
            }
            writer.writerow(row)
            csv_fh.flush()

            series.append({"t": elapsed, "ts": row["timestamp"], "fix_type": merged})

            # 遷移検出（リアルタイム表示）
            if prev_merged is not None and merged != prev_merged:
                print("[遷移 %s] %s → %s" % (
                    row["timestamp"], fix_name(prev_merged), merged_name))
            prev_merged = merged

            # 定期集計表示
            if now - last_display >= args.display_interval:
                m = compute_metrics(series)
                ttff = ("%.1fs" % m["ttff_sec"]) if m["ttff_sec"] is not None else "n/a"
                print("[%s] fix=%s | FIXED維持率=%.1f%% | FLOAT遷移=%d回 | TTFF=%s | n=%d" % (
                    row["timestamp"], merged_name, m["fixed_rate_pct"],
                    m["float_transition_count"], ttff, m["total_samples"]))
                last_display = now
    except KeyboardInterrupt:
        print("\n[INFO] Ctrl+C で終了します")
    finally:
        if mavlink is not None:
            mavlink.disconnect()
        if ubx is not None:
            ubx.close()
        csv_fh.close()

    # 最終サマリー
    print()
    if series:
        print(format_metrics(compute_metrics(series)))
    else:
        print("[WARN] サンプルが記録されませんでした")
    print("[LOG] 保存先: %s" % args.csv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())




