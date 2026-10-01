#!/usr/bin/env python3
"""
GCS Fix Monitor — MAVLink GPS_RAW_INT.fix_type を GCS REST API 経由で監視し、
RTK Fix 状態を判別するモジュール

UART2 は RTCM注入専用となったため、Fix監視は MAVLink テレメトリ経由で行う。
GCS の REST API から GPS_RAW_INT.fix_type を定期的にポーリングし、
RTK Float/Fixed 状態を監視する。

MAVLink fix_type マッピング（carrSoln 互換ログ用）:
  fix_type 0-4 (NO_GPS～DGPS) → carrSoln=0 (NONE)
  fix_type 5 (RTK_FLOAT)     → carrSoln=1 (FLOAT)
  fix_type 6 (RTK_FIXED)     → carrSoln=2 (FIXED)

ログフォーマット: rtcm_fix_transition.log との互換性を維持
  timestamp, elapsed_sec, carrSoln, carrSoln_name, numSV, hAcc, vdop, lat, lon, transition

【使用例】
  # RTK Fixed 待機 (最大120秒)
  python rtk_tools/gcs_fix_monitor.py --gcs-url http://localhost:8000 --timeout 120

  # 連続モニタリング
  python rtk_tools/gcs_fix_monitor.py --gcs-url http://localhost:8000 --monitor

  # 単発ポーリング
  python rtk_tools/gcs_fix_monitor.py --gcs-url http://localhost:8000 --once

【参考】
  - docs/ctrl/migration_summary.md (移行サマリ)
  - rtk_tools/f9p_fix_monitor.py (非推奨、UBXベース旧方式)
"""

import argparse
import csv
import json
import logging
import os
import sys
import time
from typing import Optional

import requests

logger = logging.getLogger("gcs_fix_monitor")

# ---------------------------------------------------------------------------
# MAVLink fix_type → carrSoln マッピング（ログ互換性のため）
# ---------------------------------------------------------------------------
FIX_TYPE_TO_CARRSOLN: dict[int, int] = {
    0: 0,  # NO_GPS     → NONE
    1: 0,  # NO_FIX     → NONE
    2: 0,  # 2D_FIX     → NONE
    3: 0,  # 3D_FIX     → NONE
    4: 0,  # DGPS       → NONE
    5: 1,  # RTK_FLOAT  → FLOAT
    6: 2,  # RTK_FIXED  → FIXED
    7: 0,  # STATIC     → NONE
    8: 0,  # PPP        → NONE
}

CARRSOLN_NAMES: dict[int, str] = {0: "NONE", 1: "FLOAT", 2: "FIXED"}

FIX_TYPE_NAMES: dict[int, str] = {
    0: "NO_GPS", 1: "NO_FIX", 2: "2D_FIX", 3: "3D_FIX",
    4: "DGPS", 5: "RTK_FLOAT", 6: "RTK_FIXED",
    7: "STATIC", 8: "PPP",
}


# ---------------------------------------------------------------------------
# GcsFixMonitor
# ---------------------------------------------------------------------------

class GcsFixMonitor:
    """GCS REST API から GPS_RAW_INT.fix_type をポーリングし RTK Fix 状態を監視する

    Parameters
    ----------
    gcs_url : str
        GCS REST API のベースURL (例: http://localhost:8000)
    system_id : int
        監視対象のドローン system_id (default: 1)
    poll_interval : float
        ポーリング間隔 [秒] (default: 1.0)
    """

    FIX_TRANSITION_LOG_DIR = "logs"
    FIX_TRANSITION_LOG_FILE = os.path.join(FIX_TRANSITION_LOG_DIR, "rtcm_fix_transition.log")
    FIX_JSON_LOG_FILE = os.path.join(FIX_TRANSITION_LOG_DIR, "rtcm_fix_transition.jsonl")

    def __init__(
        self,
        gcs_url: str = "http://localhost:8000",
        system_id: int = 1,
        poll_interval: float = 1.0,
    ):
        self.gcs_url = gcs_url.rstrip("/")
        self.system_id = system_id
        self.poll_interval = poll_interval

    # ------------------------------------------------------------------
    # API ポーリング
    # ------------------------------------------------------------------

    def _fetch_drone_data(self) -> Optional[dict]:
        """GCS REST API (/api/drones) から対象 drone のテレメトリを取得する。"""
        try:
            resp = requests.get(
                f"{self.gcs_url}/api/drones",
                timeout=5.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.ConnectionError:
            logger.debug(f"GCS connection refused: {self.gcs_url}")
            return None
        except requests.exceptions.Timeout:
            logger.debug(f"GCS request timeout: {self.gcs_url}")
            return None
        except Exception as e:
            logger.debug(f"GCS request failed: {e}")
            return None

        drones = data.get("drones", [])
        if not isinstance(drones, list):
            drones = []

        for drone in drones:
            if drone.get("system_id") == self.system_id:
                fix_type = drone.get("gps_fix", -1)
                carr_soln = FIX_TYPE_TO_CARRSOLN.get(fix_type, 0)
                return {
                    "fix_type": fix_type,
                    "fix_name": FIX_TYPE_NAMES.get(fix_type, f"UNKNOWN({fix_type})"),
                    "carrSoln": carr_soln,
                    "carrSoln_name": CARRSOLN_NAMES.get(carr_soln, f"UNKNOWN({carr_soln})"),
                    "numSV": drone.get("gps_sats", 0),
                    "lat": drone.get("lat"),
                    "lon": drone.get("lon"),
                    "alt": drone.get("alt"),
                    "hdop": drone.get("hdop"),
                    "vdop": drone.get("vdop"),
                }

        return None

    # ------------------------------------------------------------------
    # CSV ログ管理 (rtcm_fix_transition.log 互換)
    # ------------------------------------------------------------------

    def _open_fix_transition_log(self) -> tuple:
        """RTCM→FIX遷移ログを開きCSV writerを返す。(csv_file, csv_writer)"""
        os.makedirs(self.FIX_TRANSITION_LOG_DIR, exist_ok=True)
        csv_file = open(self.FIX_TRANSITION_LOG_FILE, "a", newline="")
        csv_writer = csv.writer(csv_file)
        if os.path.getsize(self.FIX_TRANSITION_LOG_FILE) == 0:
            csv_writer.writerow([
                "timestamp",
                "elapsed_sec",
                "carrSoln",
                "carrSoln_name",
                "numSV",
                "hAcc",
                "lat",
                "lon",
                "transition",
            ])
            csv_file.flush()
        if os.path.getsize(self.FIX_TRANSITION_LOG_FILE) == 0:
            csv_writer.writerow([
                "timestamp",
                "elapsed_sec",
                "carrSoln",
                "carrSoln_name",
                "numSV",
                "hAcc",
                "vdop",
                "lat",
                "lon",
                "transition",
            ])
            csv_file.flush()
        return csv_file, csv_writer

    def _write_json_record(self, record: dict) -> None:
        """Write a single JSON line record for structured analysis."""
        os.makedirs(self.FIX_TRANSITION_LOG_DIR, exist_ok=True)
        with open(self.FIX_JSON_LOG_FILE, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        return csv_file, csv_writer

    # ------------------------------------------------------------------
    # RTK Fixed 待機
    # ------------------------------------------------------------------

    def wait_for_rtk_fixed(self, timeout: float = 120.0) -> bool:
        """GCS API をポーリングし fix_type=6 (RTK_FIXED) になるまで待つ

        Parameters
        ----------
        timeout : float
            最大待機時間 [秒]

        Returns
        -------
        bool
            RTK Fixed 達成で True、タイムアウトで False
        """
        csv_file, csv_writer = self._open_fix_transition_log()
        prev_carrsoln = -1
        time_to_float = None
        time_to_fixed = None
        start = time.monotonic()

        try:
            while time.monotonic() - start < timeout:
                result = self._fetch_drone_data()
                elapsed = time.monotonic() - start
                now_str = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())

                if result is None:
                    logger.info(
                        f"  t={elapsed:5.1f}s  (no GCS telemetry yet)"
                    )
                    time.sleep(self.poll_interval)
                    continue

                cs = result["carrSoln"]
                fix_type = result["fix_type"]

                # 遷移検出
                transition = ""
                if prev_carrsoln != -1 and cs != prev_carrsoln:
                    if prev_carrsoln == 0 and cs == 1:
                        transition = ">>> FLOAT (0→1) <<<"
                        time_to_float = elapsed
                        logger.info(
                            "  >>> RTK FLOAT reached at t=%.1fs <<<", elapsed
                        )
                    elif prev_carrsoln == 1 and cs == 2:
                        transition = ">>> FIXED (1→2) <<<"
                        time_to_fixed = elapsed

                prev_carrsoln = cs

                # CSV行書き込み
                csv_writer.writerow([
                    now_str,
                    f"{elapsed:.1f}",
                    cs,
                    result.get("carrSoln_name", "?"),
                    result.get("numSV", 0),
                    f"{result.get('hdop', 0) or 0:.3f}",
                    f"{result.get('vdop', '') or ''}",
                    f"{result.get('lat', 0) or 0:.7f}",
                    f"{result.get('lon', 0) or 0:.7f}",
                    transition,
                ])
                csv_file.flush()

                # JSON Lines record
                json_rec = {
                    "timestamp": now_str,
                    "elapsed_sec": round(elapsed, 1),
                    "carrSoln": cs,
                    "carrSoln_name": result.get("carrSoln_name", "?"),
                    "numSV": result.get("numSV", 0),
                    "hdop": result.get("hdop"),
                    "vdop": result.get("vdop"),
                    "lat": result.get("lat"),
                    "lon": result.get("lon"),
                    "alt": result.get("alt"),
                    "transition": transition or None,
                }
                self._write_json_record(json_rec)

                logger.info(
                    f"  t={elapsed:5.1f}s  fix_type={fix_type}"
                    f"({result['fix_name']})  "
                    f"carrSoln={cs}({result['carrSoln_name']})  "
                    f"numSV={result['numSV']}  "
                    f"hdop={result.get('hdop', 'N/A')}"
                )

                if fix_type == 6:  # RTK_FIXED
                    logger.info("=" * 60)
                    logger.info("  RTK FIXED ACHIEVED!")
                    logger.info(
                        f"  Position: lat={result['lat']} "
                        f"lon={result['lon']} "
                        f"alt={result['alt']}m"
                    )
                    logger.info(f"  HDOP: {result.get('hdop', 'N/A')}")
                    logger.info(f"  Time to fix: {elapsed:.1f}s")
                    logger.info("=" * 60)

                    # 最終サマリ行
                    float_str = f"{time_to_float:.1f}" if time_to_float else "N/A"
                    fixed_str = f"{elapsed:.1f}"
                    csv_writer.writerow([
                        f"# SUMMARY",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        f"time_to_float={float_str}s  time_to_fixed={fixed_str}s",
                    ])
                    csv_file.flush()
                    return True

                time.sleep(self.poll_interval)

            # タイムアウト時サマリ
            csv_writer.writerow([
                f"# TIMEOUT",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                f"time_to_float={time_to_float or 'N/A'}s  time_to_fixed=N/A (timeout={timeout}s)",
            ])
            csv_file.flush()
            logger.warning(f"RTK Fixed not achieved within {timeout}s")
            return False

        finally:
            try:
                csv_file.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 単発ポーリング
    # ------------------------------------------------------------------

    def poll_once(self) -> Optional[dict]:
        """GCS API から1回テレメトリを取得する"""
        return self._fetch_drone_data()

    # ------------------------------------------------------------------
    # 連続モニタリング
    # ------------------------------------------------------------------

    def monitor(self, interval: float = 1.0) -> None:
        """連続モニタリングモード (Ctrl+C で停止)"""
        logger.info(
            f"Continuous monitoring via GCS API: {self.gcs_url}/api/drones"
        )
        start_time = time.monotonic()

        try:
            while True:
                result = self._fetch_drone_data()
                elapsed = time.monotonic() - start_time

                if result is None:
                    print(f"{elapsed:6.1f}s  {'(no data)':>10}")
                else:
                    fix_type = result["fix_type"]
                    print(
                        f"{elapsed:6.1f}s  "
                        f"{result['fix_name']:<10s}  "
                        f"carrSoln={result['carrSoln']}({result['carrSoln_name']})  "
                        f"sats={result['numSV']:>3d}  "
                        f"hdop={result.get('hdop', 'N/A')}"
                    )

                time.sleep(interval)

        except KeyboardInterrupt:
            print("\nStopped by user")


# ---------------------------------------------------------------------------
# __main__: CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="GCS Fix Monitor — MAVLink GPS_RAW_INT.fix_type を GCS API 経由で監視",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "使用例:\n"
            "  python rtk_tools/gcs_fix_monitor.py --gcs-url http://localhost:8000 --timeout 120\n"
            "  python rtk_tools/gcs_fix_monitor.py --gcs-url http://localhost:8000 --monitor\n"
            "  python rtk_tools/gcs_fix_monitor.py --gcs-url http://localhost:8000 --once\n"
        ),
    )
    parser.add_argument(
        "--gcs-url",
        default="http://localhost:8000",
        help="GCS REST API のベースURL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--system-id",
        type=int,
        default=1,
        help="監視対象ドローンの system_id (default: 1)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="wait_for_rtk_fixed の最大待機時間 [秒] (default: 120)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="ポーリング間隔 [秒] (default: 1.0)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="GCS API を1回ポーリングして結果を表示",
    )
    parser.add_argument(
        "--monitor",
        action="store_true",
        help="連続モニタリングモード (Ctrl+C で終了)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="ログレベル (default: INFO)",
    )
    args = parser.parse_args()

    # ログ設定
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    monitor = GcsFixMonitor(
        gcs_url=args.gcs_url,
        system_id=args.system_id,
        poll_interval=args.interval,
    )

    try:
        if args.once:
            print(f"Polling GCS API: {args.gcs_url}/api/drones ...")
            result = monitor.poll_once()
            if result is None:
                print("(no data — GCS not reachable or drone offline)")
                sys.exit(1)
            print(
                f"fix_type={result['fix_type']}({result['fix_name']}) "
                f"carrSoln={result['carrSoln']}({result['carrSoln_name']}) "
                f"sats={result['numSV']} "
                f"hdop={result.get('hdop', 'N/A')} "
                f"lat={result.get('lat')} lon={result.get('lon')} alt={result.get('alt')}"
            )
            sys.exit(0 if result["fix_type"] == 6 else 1)

        elif args.monitor:
            monitor.monitor(interval=args.interval)

        else:
            # デフォルト: RTK Fixed 待機
            print(f"Waiting for RTK Fixed via GCS API (timeout={args.timeout}s) ...")
            print(f"  GCS URL: {args.gcs_url}/api/drones")
            ok = monitor.wait_for_rtk_fixed(timeout=args.timeout)
            if ok:
                print("RTK FIXED achieved!")
                sys.exit(0)
            else:
                print("RTK Fixed NOT achieved (timeout)")
                sys.exit(1)

    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
