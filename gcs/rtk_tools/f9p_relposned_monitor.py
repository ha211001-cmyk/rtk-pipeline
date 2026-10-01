#!/usr/bin/env python3
"""
F9P RELPOSNED Monitor — UBX-NAV-RELPOSNED (0x01 0x10) を F9P Rover UART2 から
直接読み取り、RTK Fix 状態 (carrSoln) を監視する。

NAV-RELPOSNED flags ビットフィールド:
  bits 0-7:    gnssFixOk
  bit 8:       diffSoln
  bit 9:       relPosValid
  bits 10-11:  refPosMiss
  bit 12:      refObsMiss
  bits 16-18:  carrSoln (0=NONE, 1=FLOAT, 2=FIXED) ★

Usage:
  python rtk_tools/f9p_relposned_monitor.py --port /dev/ttyAMA4
  python rtk_tools/f9p_relposned_monitor.py --interval 15 --count 20
"""

import argparse
import csv
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Optional

import serial
from pyubx2 import UBXReader, UBX_PROTOCOL

logger = logging.getLogger("f9p_relposned_monitor")

CARRSOLN_NAMES: dict[int, str] = {0: "NONE", 1: "FLOAT", 2: "FIXED"}

NAV_RELPOSNED_CLS = b'\x01'
NAV_RELPOSNED_MID = b'\x3c'  # F9P HPG 1.32 firmware: RELPOSNED moved from 0x10 to 0x3C

_CARRSOLN_SHIFT = 16
_CARRSOLN_MASK = 0x07


def extract_carrsoln_from_flags(flags: int) -> int:
    return (flags >> _CARRSOLN_SHIFT) & _CARRSOLN_MASK


def format_relposned(result: Optional[dict]) -> str:
    if result is None:
        return "NAV-RELPOSNED: (no data)"
    cs = result.get("carrSoln", -1)
    cs_name = CARRSOLN_NAMES.get(cs, f"UNKNOWN({cs})")
    rel_n = result.get("relPosN", 0)
    rel_e = result.get("relPosE", 0)
    rel_d = result.get("relPosD", 0)
    dist = (rel_n ** 2 + rel_e ** 2 + rel_d ** 2) ** 0.5
    return (
        f"carrSoln={cs}({cs_name}) "
        f"relPosValid={result.get('relPosValid', False)} "
        f"relPos(N,E,D)=({rel_n:.3f}, {rel_e:.3f}, {rel_d:.3f})m "
        f"dist={dist:.3f}m "
        f"acc(N,E,D)=({result.get('accN', 0):.4f}, "
        f"{result.get('accE', 0):.4f}, {result.get('accD', 0):.4f})m "
        f"refStationId={result.get('refStationId', 0)}"
    )


class F9pRelposnedMonitor:
    """UART2 TX2 から UBX-NAV-RELPOSNED を読み取り RTK Fix 状態を監視する"""

    def __init__(self, serial_port: str = "/dev/ttyAMA4", baudrate: int = 115200):
        self.serial_port = serial_port
        self.baudrate = baudrate
        self._ser: Optional[serial.Serial] = None
        self._reader: Optional[UBXReader] = None

    def open(self) -> None:
        if self._ser and self._ser.is_open:
            logger.warning(f"Serial port already open: {self.serial_port}")
            return
        self._ser = serial.Serial(
            port=self.serial_port, baudrate=self.baudrate, timeout=2.0
        )
        self._ser.reset_input_buffer()
        self._reader = UBXReader(self._ser, protfilter=UBX_PROTOCOL)
        logger.info(
            f"F9pRelposnedMonitor opened: {self.serial_port} @ {self.baudrate} bps"
        )

    def close(self) -> None:
        if self._ser and self._ser.is_open:
            self._ser.close()
            logger.info(f"F9pRelposnedMonitor closed: {self.serial_port}")
        self._ser = None
        self._reader = None

    def poll_relposned(self, timeout: float = 5.0) -> Optional[dict]:
        if self._reader is None:
            logger.error("Not opened. Call open() first.")
            return None

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                raw, parsed = self._reader.read()
            except Exception as e:
                logger.debug(f"UBXReader read error: {e}")
                time.sleep(0.05)
                continue
            if parsed is None:
                continue
            if (
                parsed.msg_cls == NAV_RELPOSNED_CLS
                and parsed.msg_id == NAV_RELPOSNED_MID
            ):
                flags = getattr(parsed, "flags", 0)
                cs = extract_carrsoln_from_flags(flags)
                scale = 0.0001  # 0.1 mm → m
                return {
                    "carrSoln": cs,
                    "carrSoln_name": CARRSOLN_NAMES.get(cs, f"UNKNOWN({cs})"),
                    "relPosValid": bool(flags & (1 << 9)),
                    "relPosN": getattr(parsed, "relPosN", 0) * scale,
                    "relPosE": getattr(parsed, "relPosE", 0) * scale,
                    "relPosD": getattr(parsed, "relPosD", 0) * scale,
                    "accN": getattr(parsed, "accN", 0) * scale,
                    "accE": getattr(parsed, "accE", 0) * scale,
                    "accD": getattr(parsed, "accD", 0) * scale,
                    "refStationId": getattr(parsed, "refStationId", 0),
                    "gnssFixOk": bool(flags & 1),
                    "diffSoln": bool(flags & (1 << 8)),
                    "refPosMiss": (flags >> 10) & 0x03,
                    "refObsMiss": bool(flags & (1 << 12)),
                    "flags": flags,
                }
        logger.debug(f"poll_relposned timed out after {timeout}s")
        return None

    def batch_poll(
        self,
        interval_sec: float = 30.0,
        count: int = 10,
        csv_path: Optional[str] = None,
    ) -> dict:
        if self._reader is None:
            logger.error("Not opened. Call open() first.")
            return {"verdict": "ERROR: not opened"}

        if csv_path is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            os.makedirs("logs", exist_ok=True)
            csv_path = os.path.join("logs", f"relposned_monitor_{ts}.csv")

        csv_file = open(csv_path, "w", newline="")
        csv_writer = csv.writer(csv_file)
        csv_writer.writerow([
            "poll", "timestamp", "elapsed_sec",
            "carrSoln", "carrSoln_name", "relPosValid",
            "relPosN_m", "relPosE_m", "relPosD_m",
            "accN_m", "accE_m", "accD_m",
            "refStationId", "flags_raw", "verdict",
        ])
        csv_file.flush()

        samples: list[dict] = []
        max_cs = -1
        fixed_count = 0
        float_count = 0
        none_count = 0
        first_fixed_poll: Optional[int] = None
        start_time = time.monotonic()

        print()
        print("=" * 80)
        print(f"  F9P RELPOSNED バッチポーリング開始")
        print(f"  間隔: {interval_sec}s x {count}回 (総時間: 約{interval_sec * count:.0f}s)")
        print(f"  CSV: {csv_path}")
        print("=" * 80)
        print()
        print(f"{'Poll':>4} {'経過(s)':>7} {'carrSoln':>10} "
              f"{'N(m)':>8} {'E(m)':>8} {'D(m)':>8} "
              f"{'accN(m)':>9} {'判定':>12}")
        print("-" * 100)

        for i in range(1, count + 1):
            poll_start = time.monotonic()
            result = self.poll_relposned(timeout=5.0)
            elapsed = time.monotonic() - start_time
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            if result is None:
                print(f"{i:4d} {elapsed:7.1f} {'---':>10} "
                      f"{'---':>8} {'---':>8} {'---':>8} "
                      f"{'---':>9} {'NO_RESPONSE':>12}")
                csv_writer.writerow([
                    i, timestamp, f"{elapsed:.1f}", -1, "NO_RESPONSE",
                    "", "", "", "", "", "", "", "", "NO_RESPONSE",
                ])
            else:
                cs_val = result["carrSoln"]
                cs_name = result["carrSoln_name"]
                if cs_val == 2:
                    verdict = "FIXED"
                    fixed_count += 1
                    if first_fixed_poll is None:
                        first_fixed_poll = i
                elif cs_val == 1:
                    verdict = "FLOAT"
                    float_count += 1
                elif cs_val == 0:
                    verdict = "NONE"
                    none_count += 1
                else:
                    verdict = f"UNKNOWN({cs_val})"

                max_cs = max(max_cs, cs_val)
                rel_n = result["relPosN"]
                rel_e = result["relPosE"]
                rel_d = result["relPosD"]
                acc_n = result.get("accN", 0)
                print(f"{i:4d} {elapsed:7.1f} "
                      f"{cs_val}({cs_name}) "
                      f"{rel_n:8.3f} {rel_e:8.3f} {rel_d:8.3f} "
                      f"{acc_n:9.4f} {verdict:>12}")

                samples.append({
                    "poll": i, "timestamp": timestamp,
                    "elapsed_sec": round(elapsed, 1),
                    "carrSoln": cs_val, "carrSoln_name": cs_name,
                    "relPosValid": result["relPosValid"],
                    "relPosN": rel_n, "relPosE": rel_e, "relPosD": rel_d,
                    "accN": result.get("accN", 0),
                    "accE": result.get("accE", 0),
                    "accD": result.get("accD", 0),
                    "refStationId": result["refStationId"],
                    "flags": result["flags"], "verdict": verdict,
                })
                csv_writer.writerow([
                    i, timestamp, f"{elapsed:.1f}",
                    cs_val, cs_name, result["relPosValid"],
                    rel_n, rel_e, rel_d,
                    result.get("accN", 0), result.get("accE", 0),
                    result.get("accD", 0),
                    result["refStationId"], result["flags"], verdict,
                ])

            csv_file.flush()

            if i < count:
                poll_elapsed = time.monotonic() - poll_start
                wait = max(0.0, interval_sec - poll_elapsed)
                if wait > 0:
                    time.sleep(wait)

        csv_file.close()

        # 最終判定
        max_cs_name = CARRSOLN_NAMES.get(max_cs, "UNKNOWN")
        if max_cs == 2:
            overall_verdict = "SUCCESS"
        elif max_cs == 1:
            overall_verdict = "SEMI-SUCCESS"
        else:
            overall_verdict = "NEED_DIAGNOSIS"

        final_cs = samples[-1]["carrSoln"] if samples else -1
        final_cs_name = CARRSOLN_NAMES.get(final_cs, "N/A")

        print("-" * 100)
        print()
        print("=" * 60)
        print("  ポーリング結果サマリ")
        print("=" * 60)
        print(f"  総ポーリング数      : {count}")
        print(f"  成功ポーリング数    : {len(samples)}")
        s = " ★" if fixed_count > 0 else ""
        print(f"  carrSoln=FIXED(2)   : {fixed_count} 回{s}")
        print(f"  carrSoln=FLOAT(1)   : {float_count} 回")
        print(f"  carrSoln=NONE(0)    : {none_count} 回")
        print(f"  NO_RESPONSE         : {count - len(samples)} 回")
        print(f"  最高到達 carrSoln   : {max_cs}({max_cs_name})")
        print(f"  最終 carrSoln       : {final_cs}({final_cs_name})")
        if first_fixed_poll:
            print(f"  初回 FIXED 到達     : ポーリング #{first_fixed_poll}")
        print(f"  CSV                 : {csv_path}")
        print("-" * 60)
        if overall_verdict == "SUCCESS":
            print("  ✅ SUCCESS — carrSoln=FIXED(2) に到達")
        elif overall_verdict == "SEMI-SUCCESS":
            print("  ⚠️  SEMI-SUCCESS — FLOAT(1) まで到達。FIXED未達")
        else:
            print("  ❌ NEED_DIAGNOSIS — FIXED/FLOAT未達。再診断が必要")
        print("=" * 60)
        print()

        return {
            "total_polls": count,
            "successful_polls": len(samples),
            "max_carrsoln": max_cs,
            "max_carrsoln_name": max_cs_name,
            "fixed_count": fixed_count,
            "float_count": float_count,
            "none_count": none_count,
            "final_carrsoln": final_cs,
            "final_carrsoln_name": final_cs_name,
            "first_fixed_poll": first_fixed_poll,
            "csv_path": csv_path,
            "samples": samples,
            "verdict": overall_verdict,
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="F9P RELPOSNED Monitor — UBX-NAV-RELPOSNED carrSoln 監視",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "使用例:\n"
            "  python rtk_tools/f9p_relposned_monitor.py\n"
            "  python rtk_tools/f9p_relposned_monitor.py --once\n"
            "  python rtk_tools/f9p_relposned_monitor.py --interval 15 --count 20\n"
        ),
    )
    parser.add_argument("--port", default="/dev/ttyAMA4",
                        help="F9P接続 RPi UART4 ポート (default: /dev/ttyAMA4)")
    parser.add_argument("--baud", type=int, default=115200,
                        help="ボーレート (default: 115200)")
    parser.add_argument("--interval", type=float, default=30.0,
                        help="ポーリング間隔 [秒] (default: 30)")
    parser.add_argument("--count", type=int, default=10,
                        help="ポーリング回数 (default: 10)")
    parser.add_argument("--once", action="store_true",
                        help="単発ポーリングして終了")
    parser.add_argument("--csv", default=None,
                        help="CSV出力先パス (default: logs/relposned_monitor_<ts>.csv)")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="ログレベル (default: INFO)")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    monitor = F9pRelposnedMonitor(serial_port=args.port, baudrate=args.baud)

    try:
        monitor.open()

        if args.once:
            print("単発 RELPOSNED ポーリング ...")
            result = monitor.poll_relposned(timeout=5.0)
            print(format_relposned(result))
            if result:
                cs = result["carrSoln"]
                sys.exit(0 if cs == 2 else (1 if cs == 1 else 2))
            else:
                sys.exit(3)

        summary = monitor.batch_poll(
            interval_sec=args.interval,
            count=args.count,
            csv_path=args.csv,
        )

        verdict = summary.get("verdict", "ERROR")
        if verdict == "SUCCESS":
            sys.exit(0)
        elif verdict == "SEMI-SUCCESS":
            sys.exit(1)
        else:
            sys.exit(2)

    except KeyboardInterrupt:
        print("\n中断されました")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        monitor.close()


if __name__ == "__main__":
    main()
