#!/usr/bin/env python3
"""base_ubx_logger.py — 基地局 F9P の C/N0・DOP・衛星数をログする診断スクリプト

基地局 F9P（Mac USB 直結）から UBX NAV-SAT / NAV-DOP / NAV-PVT をポーリングし、
衛星ごとの C/N0（信号品質）・DOP（測位精度劣化率）・捕捉衛星数を記録します。

RTK_FIXED が到達しないときの原因切り分け（上空視界・マルチパス評価）に使います。

注意:
  - シリアル排他アクセスのため、**udp_base_sender.py 停止中**に実行してください
    （同時に開くとシリアルが競合し、双方が不安定になります）。

使い方:
    python3 base_ubx_logger.py --duration 120 --interval 5
"""

import argparse
import glob
import time
from datetime import datetime

import serial
from pyubx2 import UBXMessage, UBXReader, POLL


def extract_cnos(parsed) -> list:
    """NAV-SAT から C/N0 値のリストを抽出する（未捕捉衛星 cno=0 は除外）"""
    cnos = []
    d = getattr(parsed, "__dict__", {})
    for k, v in d.items():
        if "cno" in k.lower() and isinstance(v, (int, float)) and v > 0:
            cnos.append(v)
    return cnos


def auto_detect_port():
    """基地局 F9P のシリアルポートを自動検出する（macOS / Linux 対応）"""
    for pat in ("/dev/cu.usbmodem*", "/dev/tty.usbmodem*", "/dev/ttyACM*", "/dev/ttyUSB*"):
        m = sorted(glob.glob(pat))
        if m:
            return m[0]
    return None


def main() -> None:
    p = argparse.ArgumentParser(description="基地局 F9P の C/N0・DOP・衛星数をログ")
    p.add_argument("--port", default=None, help="シリアルポート（省略時は自動検出）")
    p.add_argument("--baudrate", type=int, default=115200)
    p.add_argument("--duration", type=int, default=120, help="観測秒数")
    p.add_argument("--interval", type=float, default=5.0, help="ポーリング間隔(秒)")
    a = p.parse_args()

    port = a.port or auto_detect_port()
    if not port:
        print("[ERROR] シリアルポートを検出できません。--port で明示指定してください")
        return
    print("# 使用ポート: %s" % port)
    ser = serial.Serial(port, a.baudrate, timeout=1.0)
    ubr = UBXReader(ser)

    print("# 基地局 C/N0・DOP ログ開始 %s" % datetime.now().strftime("%H:%M:%S"))
    print("# 形式: [時刻] numSV pDOP hDOP vDOP | C/N0 n/min/avg/max")

    start = time.time()
    last_poll = 0.0
    while time.time() - start < a.duration:
        now = time.time()
        if now - last_poll >= a.interval:
            for msg in (UBXMessage("NAV", "NAV-PVT", POLL),
                        UBXMessage("NAV", "NAV-DOP", POLL),
                        UBXMessage("NAV", "NAV-SAT", POLL)):
                try:
                    ser.write(msg.serialize())
                except Exception as e:  # noqa: BLE001
                    print("[WARN] poll send failed:", e)
                time.sleep(0.1)
            last_poll = now

        raw, parsed = ubr.read()
        if parsed is None:
            continue

        ident = parsed.identity
        ts = datetime.now().strftime("%H:%M:%S")
        if ident == "NAV-PVT":
            print("[%s] PVT numSV=%s pDOP=%s fixType=%s" % (
                ts,
                getattr(parsed, "numSV", "?"),
                getattr(parsed, "pDOP", "?"),
                getattr(parsed, "fixType", "?"),
            ))
        elif ident == "NAV-DOP":
            print("[%s] DOP hDOP=%s vDOP=%s pDOP=%s" % (
                ts,
                getattr(parsed, "hDOP", "?"),
                getattr(parsed, "vDOP", "?"),
                getattr(parsed, "pDOP", "?"),
            ))
        elif ident == "NAV-SAT":
            cnos = extract_cnos(parsed)
            if cnos:
                cnos.sort()
                avg = sum(cnos) / len(cnos)
                print("[%s] SAT n=%d C/N0 min=%d avg=%.1f max=%d" % (
                    ts, len(cnos), cnos[0], avg, cnos[-1]))

    ser.close()
    print("# ログ終了")


if __name__ == "__main__":
    main()
