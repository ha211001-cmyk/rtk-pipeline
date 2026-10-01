#!/usr/bin/env python3
"""
[DEPRECATED] F9P Fix Monitor — UBX-NAV-PVT を F9P Rover UART2 TX2 から直接読み取り、
RTK Fix 状態 (carrSoln) を監視するモジュール

⛔ このモジュールは非推奨です。
   Fix監視は gcs_fix_monitor.py（MAVLink GPS_RAW_INT経由）に移行されました。
   UART2 は RTCM注入専用となり、UBX出力は無効化されています。

   移行後:
     python rtk_tools/gcs_fix_monitor.py --gcs-url http://localhost:8000 --timeout 120

UART2 は双方向:
  - Raspi TX → F9P RX2  : RTCM3 補正データ注入
  - F9P TX2 → Raspi RX  : UBX-NAV-PVT 出力 (本モジュールで読み取り)

carrSoln がキーフィールド:
  0 = No RTK
  1 = RTK Float
  2 = RTK Fixed

【使用例】
  # 単発ポーリング
  python rtk_tools/f9p_fix_monitor.py --port /dev/ttyAMA4 --once

  # RTK Fixed 待機 (最大120秒)
  python rtk_tools/f9p_fix_monitor.py --port /dev/ttyAMA4 --timeout 120

  # 連続モニタリング
  python rtk_tools/f9p_fix_monitor.py --port /dev/ttyAMA4 --monitor

【参考】
  - docs/05-implementation/rtk_direct_uart2_injection_plan.md Section 5.3
  - rtk_tools/f9p_configurator.py (UBXReader パターン)
"""

import argparse
import csv
import logging
import os
import sys
import threading
import time
from typing import Callable, Optional

import serial
from pyubx2 import UBXReader, UBX_PROTOCOL

logger = logging.getLogger("f9p_fix_monitor")

# ---------------------------------------------------------------------------
# carrSoln 名マッピング
# ---------------------------------------------------------------------------
CARRSOLN_NAMES: dict[int, str] = {0: "NONE", 1: "FLOAT", 2: "FIXED"}


# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------
def format_nav_pvt(result: dict) -> str:
    """poll_nav_pvt() の戻り値を人間可読な文字列に整形する"""
    if result is None:
        return "NAV-PVT: (no data)"

    return (
        f"carrSoln={result.get('carrSoln', -1)}"
        f"({result.get('carrSoln_name', '?')}) "
        f"fixType={result.get('fixType', -1)} "
        f"numSV={result.get('numSV', 0)} "
        f"lat={result.get('lat', 0):.7f} "
        f"lon={result.get('lon', 0):.7f} "
        f"hMSL={result.get('hMSL', 0):.2f}m "
        f"hAcc={result.get('hAcc', 0):.3f}m "
        f"vAcc={result.get('vAcc', 0):.3f}m"
    )


# ---------------------------------------------------------------------------
# F9pFixMonitor
# ---------------------------------------------------------------------------
class F9pFixMonitor:
    """UART2 TX2 から UBX-NAV-PVT を読み取り RTK Fix 状態を監視する

    Parameters
    ----------
    serial_port : str
        F9P に接続された RPi UART4 ポート (default: /dev/ttyAMA4)
    baudrate : int
        ボーレート (default: 115200)
    """

    # UBX-NAV-PVT メッセージ識別子
    NAV_PVT_CLS = 0x01
    NAV_PVT_MID = 0x07

    def __init__(self, serial_port: str = "/dev/ttyAMA4", baudrate: int = 115200):
        self.serial_port = serial_port
        self.baudrate = baudrate
        self._ser: Optional[serial.Serial] = None
        self._reader: Optional[UBXReader] = None
        # Stream monitor control
        self._stream_thread: Optional[threading.Thread] = None
        self._stream_running = False

    # ------------------------------------------------------------------
    # シリアルポート管理
    # ------------------------------------------------------------------

    def open(self) -> None:
        """シリアルポートを開き UBXReader を初期化する"""
        if self._ser and self._ser.is_open:
            logger.warning(f"Serial port already open: {self.serial_port}")
            return

        self._ser = serial.Serial(
            port=self.serial_port,
            baudrate=self.baudrate,
            timeout=1.0,
        )
        self._ser.reset_input_buffer()
        self._reader = UBXReader(self._ser, protfilter=UBX_PROTOCOL)
        logger.info(
            f"F9pFixMonitor opened: {self.serial_port} @ {self.baudrate} bps"
        )

    def close(self) -> None:
        """シリアルポートを閉じる"""
        # Stop stream monitor first
        if self._stream_running:
            self._stop_stream()

        if self._ser and self._ser.is_open:
            self._ser.close()
            logger.info(f"F9pFixMonitor closed: {self.serial_port}")
        self._ser = None
        self._reader = None

    # ------------------------------------------------------------------
    # NAV-PVT ポーリング
    # ------------------------------------------------------------------

    def poll_nav_pvt(self, timeout: float = 3.0) -> Optional[dict]:
        """UBX-NAV-PVT (cls=0x01, mid=0x07) を1件読み取る

        Parameters
        ----------
        timeout : float
            メッセージ受信を待つ最大時間 [秒]

        Returns
        -------
        dict or None
            取得成功時:
                carrSoln      : int   (0=NONE, 1=FLOAT, 2=FIXED)
                carrSoln_name : str
                fixType       : int
                numSV         : int   (衛星数)
                lat           : float (度)
                lon           : float (度)
                hMSL          : float (m, MSL高度)
                hAcc          : float (m, 水平精度)
                vAcc          : float (m, 垂直精度)
            タイムアウト/エラー時: None
        """
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

            if parsed.msg_cls == self.NAV_PVT_CLS and parsed.msg_id == self.NAV_PVT_MID:
                cs = getattr(parsed, "carrSoln", -1)
                return {
                    "carrSoln": cs,
                    "carrSoln_name": CARRSOLN_NAMES.get(cs, f"UNKNOWN({cs})"),
                    "fixType": getattr(parsed, "fixType", -1),
                    "numSV": getattr(parsed, "numSV", 0),
                    "lat": getattr(parsed, "lat", 0) * 1e-7,
                    "lon": getattr(parsed, "lon", 0) * 1e-7,
                    "hMSL": getattr(parsed, "hMSL", 0) * 0.001,
                    "hAcc": getattr(parsed, "hAcc", 0) * 0.001,
                    "vAcc": getattr(parsed, "vAcc", 0) * 0.001,
                }

        logger.debug(f"poll_nav_pvt timed out after {timeout}s")
        return None

    # ------------------------------------------------------------------
    # RTK Fixed 待機
    # ------------------------------------------------------------------

    FIX_TRANSITION_LOG_DIR = "logs"
    FIX_TRANSITION_LOG_FILE = os.path.join(FIX_TRANSITION_LOG_DIR, "rtcm_fix_transition.log")

    def _open_fix_transition_log(self) -> tuple:
        """RTCM→FIX遷移ログを開きCSV writerを返す。(csv_file, csv_writer)"""
        os.makedirs(self.FIX_TRANSITION_LOG_DIR, exist_ok=True)
        csv_file = open(self.FIX_TRANSITION_LOG_FILE, "a", newline="")
        csv_writer = csv.writer(csv_file)
        # ファイルが空ならヘッダを書き込む
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
        return csv_file, csv_writer

    def wait_for_rtk_fixed(self, timeout: float = 120.0) -> bool:
        """carrSoln=2 (RTK Fixed) になるまでループで待つ

        Parameters
        ----------
        timeout : float
            最大待機時間 [秒]

        Returns
        -------
        bool
            RTK Fixed 達成で True、タイムアウトで False

        Notes
        -----
        carrSoln遷移（0→1 FLOAT, 1→2 FIXED）を
        logs/rtcm_fix_transition.log に記録する。
        """
        if self._reader is None:
            logger.error("Not opened. Call open() first.")
            return False

        csv_file, csv_writer = self._open_fix_transition_log()
        prev_carrsoln = -1
        time_to_float = None
        time_to_fixed = None
        start = time.monotonic()

        try:
            while time.monotonic() - start < timeout:
                result = self.poll_nav_pvt(timeout=3.0)
                elapsed = time.monotonic() - start
                now_str = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())

                if result is None:
                    logger.info(
                        f"  t={elapsed:5.1f}s  (no NAV-PVT received yet)"
                    )
                    time.sleep(0.5)
                    continue

                cs = result["carrSoln"]

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
                    f"{result.get('hAcc', 0):.3f}",
                    f"{result.get('lat', 0):.7f}",
                    f"{result.get('lon', 0):.7f}",
                    transition,
                ])
                csv_file.flush()

                logger.info(
                    f"  t={elapsed:5.1f}s  carrSoln={result['carrSoln']}"
                    f"({result['carrSoln_name']})  "
                    f"fixType={result['fixType']}  "
                    f"numSV={result['numSV']}  "
                    f"hAcc={result['hAcc']:.3f}m"
                )

                if cs == 2:
                    logger.info("=" * 60)
                    logger.info("  RTK FIXED ACHIEVED!")
                    logger.info(
                        f"  Position: lat={result['lat']:.7f} "
                        f"lon={result['lon']:.7f} "
                        f"hMSL={result['hMSL']:.2f}m"
                    )
                    logger.info(
                        f"  Accuracy: hAcc={result['hAcc']:.3f}m "
                        f"vAcc={result['vAcc']:.3f}m"
                    )
                    logger.info(f"  Time to fix: {elapsed:.1f}s")
                    logger.info("=" * 60)

                    # 最終サマリ行をCSVに書き込み
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

                time.sleep(0.5)

            # タイムアウト時もサマリを記録
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
    # 連続モニタリング (スレッド)
    # ------------------------------------------------------------------

    def get_fix_status_stream(
        self, callback: Callable[[dict], None], interval: float = 0.5
    ) -> None:
        """NAV-PVT を定期的にポーリングしコールバックに渡すスレッドを開始する

        Parameters
        ----------
        callback : callable
            poll_nav_pvt() の結果 dict を受け取るコールバック関数。
            None が渡されることもある（タイムアウト時）。
        interval : float
            ポーリング間隔 [秒]
        """
        if self._stream_running:
            logger.warning("Stream monitor already running")
            return

        self._stream_running = True

        def _loop():
            logger.info(
                f"Fix status stream started (interval={interval}s)"
            )
            while self._stream_running:
                result = self.poll_nav_pvt(timeout=max(interval, 1.0))
                try:
                    callback(result)
                except Exception as e:
                    logger.error(f"Callback error: {e}")
                time.sleep(interval)
            logger.info("Fix status stream stopped")

        self._stream_thread = threading.Thread(target=_loop, daemon=True)
        self._stream_thread.start()

    def stop(self) -> None:
        """連続モニタリングを停止する"""
        if not self._stream_running:
            return
        self._stream_running = False
        if self._stream_thread:
            self._stream_thread.join(timeout=5.0)
            self._stream_thread = None

    def _stop_stream(self) -> None:
        """内部用: ストリーム停止（close() から呼ばれる）"""
        self.stop()


# ---------------------------------------------------------------------------
# __main__: CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="F9P Fix Monitor — UBX-NAV-PVT から RTK Fix 状態を監視",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "使用例:\n"
            "  python rtk_tools/f9p_fix_monitor.py --once\n"
            "  python rtk_tools/f9p_fix_monitor.py --timeout 120\n"
            "  python rtk_tools/f9p_fix_monitor.py --monitor\n"
            "  python rtk_tools/f9p_fix_monitor.py --port /dev/ttyUSB1 --once\n"
        ),
    )
    parser.add_argument(
        "--port",
        default="/dev/ttyAMA4",
        help="F9P に接続された RPi UART4 ポート (default: /dev/ttyAMA4)",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=115200,
        help="ボーレート (default: 115200)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="wait_for_rtk_fixed の最大待機時間 [秒] (default: 120)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="NAV-PVT を1回だけポーリングして結果を表示",
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

    monitor = F9pFixMonitor(serial_port=args.port, baudrate=args.baud)

    try:
        monitor.open()

        if args.once:
            # 単発ポーリング
            print("Polling NAV-PVT once ...")
            result = monitor.poll_nav_pvt(timeout=5.0)
            print(format_nav_pvt(result))
            if result:
                sys.exit(0 if result["carrSoln"] == 2 else 1)

        elif args.monitor:
            # 連続モニタリング
            print("Continuous monitoring mode (Ctrl+C to stop)")
            print(
                f"{'elapsed':>7}  {'carrSoln':>10}  {'fixType':>8}  "
                f"{'numSV':>6}  {'lat':>12}  {'lon':>12}  "
                f"{'hMSL':>9}  {'hAcc':>8}  {'vAcc':>8}"
            )
            print("-" * 110)

            start_time = time.monotonic()

            def monitor_callback(result: Optional[dict]):
                elapsed = time.monotonic() - start_time
                if result is None:
                    print(f"{elapsed:6.1f}s  {'(no data)':>10}")
                else:
                    print(
                        f"{elapsed:6.1f}s  "
                        f"{result['carrSoln']}({result['carrSoln_name']})"
                        f"{'':6s}  "
                        f"{result['fixType']:>8}  "
                        f"{result['numSV']:>6}  "
                        f"{result['lat']:>11.7f}  "
                        f"{result['lon']:>11.7f}  "
                        f"{result['hMSL']:>8.2f}  "
                        f"{result['hAcc']:>7.3f}  "
                        f"{result['vAcc']:>7.3f}"
                    )

            monitor.get_fix_status_stream(callback=monitor_callback, interval=0.5)

            # メインスレッドは Ctrl+C まで待機
            try:
                while True:
                    time.sleep(0.5)
            except KeyboardInterrupt:
                print("\nStopping ...")
            finally:
                monitor.stop()

        else:
            # デフォルト: RTK Fixed 待機
            print(f"Waiting for RTK Fixed (timeout={args.timeout}s) ...")
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
    finally:
        monitor.close()


if __name__ == "__main__":
    main()
