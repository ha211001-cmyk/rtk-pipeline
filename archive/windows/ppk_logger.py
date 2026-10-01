#!/usr/bin/env python3
"""
PPK (後処理RTK) 用 生観測値ロガー
=================================

u-blox ZED-F9P から UBX-RXM-RAWX / RXM-SFRBX を取得し、
後処理RTK (PPK) 用に CSV へ保存する本番用スクリプト。
【Windows 対応版】

出力ファイル:
  - ppk_raw_YYYYMMDD_HHMMSS.csv  : 生観測値 (RAWX)
  - ppk_nav_YYYYMMDD_HHMMSS.csv  : 航法フレーム統計 (SFRBX)
  - ppk_pos_YYYYMMDD_HHMMSS.csv  : 参照位置 (NMEA-GGA)

使い方:
  python ppk_logger.py --duration 1800
  python ppk_logger.py --out ./log
"""

import sys

# Windows CP932 環境での Unicode 出力エラーを防ぐ
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import os
import time
import argparse
import csv
import signal
from datetime import datetime, UTC
from collections import defaultdict
from typing import Any, cast

try:
    import serial
except ImportError:
    print("Error: pyserial が必要です。pip install pyserial")
    sys.exit(1)

try:
    from pyubx2 import UBXReader, UBXMessage, UBX_PROTOCOL, NMEA_PROTOCOL, SET_LAYER_RAM, TXN_NONE
except ImportError:
    print("Error: pyubx2 が必要です。pip install pyubx2")
    sys.exit(1)

SERIAL_PORT = "COM6"
BAUD = 38400
DEFAULT_OUTDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "log")

GNSS_NAMES = {
    0: "GPS", 1: "SBAS", 2: "Galileo", 3: "BeiDou",
    4: "IMES", 5: "QZSS", 6: "GLONASS",
}

TRKSTAT_PRVALID = 0x01
TRKSTAT_CPVALID = 0x02
TRKSTAT_HALFCYC = 0x04

running = True


def handle_sigint(signum, frame):
    global running
    running = False
    print("\n[INFO] 停止シグナル受信。終了処理に入ります…")


signal.signal(signal.SIGINT, handle_sigint)
# SIGTERM は Windows でも Python の signal モジュールでサポートされている
try:
    signal.signal(signal.SIGTERM, handle_sigint)
except (OSError, ValueError):
    pass  # Windows 環境によっては SIGTERM が使えない場合がある


def enable_rawx(ser):
    cfg = cast(list[tuple[int | str, object]], [
        ("CFG_USBOUTPROT_UBX", 1),
        ("CFG_MSGOUT_UBX_RXM_RAWX_USB", 1),
        ("CFG_MSGOUT_UBX_RXM_SFRBX_USB", 1),
    ])
    msg = UBXMessage.config_set(SET_LAYER_RAM, TXN_NONE, cfg)
    if isinstance(msg, (bytes, bytearray)):
        ser.write(msg)
    else:
        ser.write(msg.serialize())

    ubr = UBXReader(ser, protfilter=UBX_PROTOCOL | NMEA_PROTOCOL)
    deadline = time.time() + 3.0
    while time.time() < deadline:
        try:
            _, parsed = ubr.read()
            if parsed is None:
                continue
            identity = parsed.identity if hasattr(parsed, "identity") else ""
            if identity == "ACK-ACK":
                print("  [ACK] CFG-VALSET 成功")
                return True
            if identity == "ACK-NAK":
                print("  [NAK] CFG-VALSET 失敗")
                return False
        except Exception:
            pass
    print("  [INFO] ACK 応答なし (受信データで継続判定します)")
    return True


RAWX_HEADER = [
    "tow_s", "week", "leap_s",
    "gnss", "sv_id", "sig_id", "freq_id",
    "pseudorange_m", "carrier_phase_cyc", "doppler_hz",
    "cno_dbhz", "lock_time_ms",
    "pr_stdev_raw", "cp_stdev_raw", "do_stdev_raw",
    "pr_valid", "cp_valid", "half_cyc_valid",
    "recv_utc",
]

SFRBX_HEADER = ["recv_utc", "gnss", "sv_id", "freq_id", "num_words"]
POS_HEADER = ["recv_utc", "tow_s", "lat_deg", "lon_deg", "alt_m", "fix_quality", "num_sv", "hdop"]


def x1_to_int(value) -> int:
    if isinstance(value, (bytes, bytearray)):
        return value[0] if len(value) > 0 else 0
    if value is None:
        return 0
    return int(value)


def x1_to_csv(value):
    if value is None:
        return ""
    return x1_to_int(value)


def main():
    parser = argparse.ArgumentParser(description="PPK logger for rtk-pipeline (Windows)")
    parser.add_argument("--port", default=SERIAL_PORT)
    parser.add_argument("--baud", type=int, default=BAUD)
    parser.add_argument("--duration", type=int, default=0, help="秒数。0 は無制限")
    parser.add_argument("--out", default=DEFAULT_OUTDIR)
    parser.add_argument("--no-enable", action="store_true")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    rawx_path = os.path.join(args.out, f"ppk_raw_{ts}.csv")
    nav_path = os.path.join(args.out, f"ppk_nav_{ts}.csv")
    pos_path = os.path.join(args.out, f"ppk_pos_{ts}.csv")

    print("=" * 60)
    print("PPK Logger (Windows)")
    print("=" * 60)
    print(f"Port      : {args.port} @ {args.baud}")
    print(f"Duration  : {'unlimited' if args.duration == 0 else str(args.duration) + 's'}")
    print(f"RAWX CSV  : {rawx_path}")
    print(f"NAV  CSV  : {nav_path}")
    print(f"POS  CSV  : {pos_path}")

    try:
        ser = serial.Serial(args.port, args.baud, timeout=1)
    except serial.SerialException as e:
        print(f"[ERROR] serial open failed: {e}")
        print(f"  ヒント: デバイスマネージャーで COM ポート番号を確認してください")
        sys.exit(1)

    if not args.no_enable:
        print("\n[設定] RAWX/SFRBX を有効化")
        enable_rawx(ser)

    rawx_f = open(rawx_path, "w", newline="", encoding="utf-8")
    nav_f = open(nav_path, "w", newline="", encoding="utf-8")
    pos_f = open(pos_path, "w", newline="", encoding="utf-8")
    rawx_w = csv.writer(rawx_f)
    nav_w = csv.writer(nav_f)
    pos_w = csv.writer(pos_f)
    rawx_w.writerow(RAWX_HEADER)
    nav_w.writerow(SFRBX_HEADER)
    pos_w.writerow(POS_HEADER)

    ubr = UBXReader(ser, protfilter=UBX_PROTOCOL | NMEA_PROTOCOL, parsebitfield=0)
    stats = defaultdict(int)
    start = time.time()
    deadline = start + args.duration if args.duration > 0 else float("inf")
    last_print = start

    while running and time.time() < deadline:
        try:
            raw, parsed = ubr.read()
            if parsed is None:
                continue

            identity = parsed.identity if hasattr(parsed, "identity") else ""
            now_ut = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

            if identity == "RXM-RAWX":
                tow = getattr(parsed, "rcvTow", 0.0)
                week = getattr(parsed, "week", 0)
                leapS = getattr(parsed, "leapS", 18)
                numMeas = getattr(parsed, "numMeas", 0)
                uniq_sat = set()
                uniq_sig = set()

                for i in range(1, numMeas + 1):
                    gnssId = getattr(parsed, f"gnssId_{i:02d}", 0)
                    svId = getattr(parsed, f"svId_{i:02d}", 0)
                    sigId = getattr(parsed, f"sigId_{i:02d}", 0)
                    freqId = getattr(parsed, f"freqId_{i:02d}", 0)
                    prMes = getattr(parsed, f"prMes_{i:02d}", None)
                    cpMes = getattr(parsed, f"cpMes_{i:02d}", None)
                    doMes = getattr(parsed, f"doMes_{i:02d}", None)
                    cno = getattr(parsed, f"cno_{i:02d}", None)
                    locktime = getattr(parsed, f"locktime_{i:02d}", None)
                    prStd = x1_to_csv(getattr(parsed, f"prStdev_{i:02d}", None))
                    cpStd = x1_to_csv(getattr(parsed, f"cpStdev_{i:02d}", None))
                    doStd = x1_to_csv(getattr(parsed, f"doStdev_{i:02d}", None))
                    trkStat = getattr(parsed, f"trkStat_{i:02d}", 0)
                    trkInt = x1_to_int(trkStat)
                    uniq_sat.add((gnssId, svId))
                    uniq_sig.add((gnssId, svId, sigId))

                    rawx_w.writerow([
                        f"{tow:.6f}", week, leapS,
                        GNSS_NAMES.get(gnssId, str(gnssId)), svId, sigId, freqId,
                        f"{prMes:.6f}" if prMes is not None else "",
                        f"{cpMes:.6f}" if cpMes is not None else "",
                        f"{doMes:.4f}" if doMes is not None else "",
                        cno if cno is not None else "",
                        locktime if locktime is not None else "",
                        prStd, cpStd, doStd,
                        int(bool(trkInt & TRKSTAT_PRVALID)),
                        int(bool(trkInt & TRKSTAT_CPVALID)),
                        int(bool(trkInt & TRKSTAT_HALFCYC)),
                        now_ut,
                    ])
                stats["rawx"] += 1
                stats["meas"] += numMeas
                sat_count = len(uniq_sat)
                sig_count = len(uniq_sig)
                stats["sat_last"] = sat_count
                stats["sig_last"] = sig_count
                stats["sat_sum"] += sat_count
                stats["sig_sum"] += sig_count
                stats["sat_max"] = max(stats["sat_max"], sat_count)
                stats["sig_max"] = max(stats["sig_max"], sig_count)

            elif identity == "RXM-SFRBX":
                gnssId = getattr(parsed, "gnssId", 0)
                svId = getattr(parsed, "svId", 0)
                freqId = getattr(parsed, "freqId", 0)
                numWords = getattr(parsed, "numWords", 0)
                nav_w.writerow([now_ut, GNSS_NAMES.get(gnssId, str(gnssId)), svId, freqId, numWords])
                stats["sfrbx"] += 1

            elif hasattr(parsed, "lat") and hasattr(parsed, "quality"):
                lat = getattr(parsed, "lat", None)
                lon = getattr(parsed, "lon", None)
                alt = getattr(parsed, "alt", None)
                q = getattr(parsed, "quality", 0)
                nsv = getattr(parsed, "numSV", None)
                hdop = getattr(parsed, "HDOP", None)
                if lat and lon:
                    pos_w.writerow([now_ut, "", f"{lat:.8f}", f"{lon:.8f}", f"{alt:.3f}" if alt is not None else "", q, nsv, hdop])
                    stats["gga"] += 1

            # flush cadence
            if stats["rawx"] % 10 == 0:
                rawx_f.flush(); nav_f.flush(); pos_f.flush()

        except KeyboardInterrupt:
            break
        except Exception as err:
            print(f"[WARN] {err}")

        now = time.time()
        if now - last_print >= 10:
            sat_avg = (stats["sat_sum"] / stats["rawx"]) if stats["rawx"] > 0 else 0
            sig_avg = (stats["sig_sum"] / stats["rawx"]) if stats["rawx"] > 0 else 0
            print(
                f"[{int(now-start):5d}s] RAWX:{stats['rawx']:5d}  MEAS:{stats['meas']:6d}  "
                f"SAT(last/max/avg):{stats['sat_last']:2d}/{stats['sat_max']:2d}/{sat_avg:4.1f}  "
                f"SIG(last/max/avg):{stats['sig_last']:2d}/{stats['sig_max']:2d}/{sig_avg:4.1f}  "
                f"SFRBX:{stats['sfrbx']:5d}  GGA:{stats['gga']:5d}"
            )
            last_print = now

    rawx_f.close(); nav_f.close(); pos_f.close(); ser.close()

    print("\n" + "=" * 60)
    print("PPK logging completed")
    print(f"RAWX epochs : {stats['rawx']}")
    print(f"Measurements: {stats['meas']}")
    if stats["rawx"] > 0:
        print(f"Unique satellites (RAWX) last/max/avg : {stats['sat_last']}/{stats['sat_max']}/{stats['sat_sum']/stats['rawx']:.1f}")
        print(f"Unique signals    (RAWX) last/max/avg : {stats['sig_last']}/{stats['sig_max']}/{stats['sig_sum']/stats['rawx']:.1f}")
    print(f"SFRBX frames: {stats['sfrbx']}")
    print(f"GGA records : {stats['gga']}")
    print(rawx_path)
    print(nav_path)
    print(pos_path)


if __name__ == "__main__":
    main()
