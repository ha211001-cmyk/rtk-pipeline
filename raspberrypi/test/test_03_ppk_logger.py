#!/usr/bin/env python3
"""
[PPK テスト Step 3] PPK 後処理用 生観測値 CSV ロガー
=====================================================
u-blox F9P から UBX-RXM-RAWX を受信し、後処理RTK (PPK) に
必要な生観測値データを CSV 形式で記録する。

出力ファイル:
  ppk_raw_YYYYMMDD_HHMMSS.csv   — メイン観測値 (RAWX)
  ppk_nav_YYYYMMDD_HHMMSS.csv   — 航法サブフレーム統計 (SFRBX)
  ppk_pos_YYYYMMDD_HHMMSS.csv   — 同時記録した NMEA 位置 (参照用)

PPK ワークフロー:
  1. このスクリプトで移動局データを収集
  2. 基地局データ (既知点のRINEX等) を入手
  3. RTKLIB などで後処理 → cm精度の軌跡を取得

CSV フォーマット (ppk_raw_*.csv):
  tow_s, week, leap_s, gnss, sv_id, sig_id,
  pseudorange_m, carrier_phase_cyc, doppler_hz,
  cno_dbhz, lock_time_ms, pr_stdev_m, cp_stdev_cyc, do_stdev_hz,
  pr_valid, cp_valid, half_cyc_valid

使い方:
  python3 test_03_ppk_logger.py [オプション]
  python3 test_03_ppk_logger.py --duration 300   # 5分間ログ
  python3 test_03_ppk_logger.py --out /home/taki/ppkdata
"""

import sys
import os
import time
import argparse
import csv
import signal
from datetime import datetime
from collections import defaultdict

try:
    import serial
except ImportError:
    print("Error: pyserial が必要です。  pip install pyserial")
    sys.exit(1)

try:
    from pyubx2 import UBXReader, UBXMessage, UBX_PROTOCOL, NMEA_PROTOCOL, SET_LAYER_RAM, TXN_NONE
except ImportError:
    print("Error: pyubx2 が必要です。  pip install pyubx2")
    sys.exit(1)

# ============================================================
# 定数
# ============================================================
SERIAL_PORT   = "/dev/ttyACM0"
BAUD          = 38400
DEFAULT_OUTDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "log")

GNSS_NAMES = {
    0: "GPS", 1: "SBAS", 2: "Galileo", 3: "BeiDou",
    4: "IMES", 5: "QZSS", 6: "GLONASS",
}

# RAWX trackin status bit masks
TRKSTAT_PRVALID = 0x01
TRKSTAT_CPVALID = 0x02
TRKSTAT_HALFCYC = 0x04

# ============================================================
# グローバル制御フラグ
# ============================================================
running = True


def handle_sigint(signum, frame):
    global running
    running = False
    print("\n[INFO] 停止シグナル受信 — ファイルを閉じて終了します…")


signal.signal(signal.SIGINT,  handle_sigint)
signal.signal(signal.SIGTERM, handle_sigint)


# ============================================================
# F9P 設定
# ============================================================
def enable_rawx(ser):
    """RXM-RAWX / RXM-SFRBX を有効化する (RAM のみ)"""
    # /dev/ttyACM0 は USB CDC → _USB キーを使う
    cfg = [
        ("CFG_USBOUTPROT_UBX",              1),
        ("CFG_MSGOUT_UBX_RXM_RAWX_USB",     1),
        ("CFG_MSGOUT_UBX_RXM_SFRBX_USB",    1),
    ]
    msg = UBXMessage.config_set(SET_LAYER_RAM, TXN_NONE, cfg)
    ser.write(msg.serialize())

    # ACK チェック (UBXReader で待機)
    from pyubx2 import UBXReader, UBX_PROTOCOL, NMEA_PROTOCOL
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
                return
            if identity == "ACK-NAK":
                print("  [NAK] CFG-VALSET 失敗 — RAWX が到着しない場合は F9P のファームを確認")
                return
        except Exception:
            pass
    print("  [INFO] ACK 応答なし — RAWX の受信を確認してください")


# ============================================================
# CSV ヘッダー
# ============================================================
RAWX_HEADER = [
    "tow_s", "week", "leap_s",
    "gnss", "sv_id", "sig_id", "freq_id",
    "pseudorange_m", "carrier_phase_cyc", "doppler_hz",
    "cno_dbhz", "lock_time_ms",
    "pr_stdev_raw", "cp_stdev_raw", "do_stdev_raw",
    "pr_valid", "cp_valid", "half_cyc_valid",
    "recv_utc",        # ローカルPC/ラズパイの受信時刻 (参照用)
]

SFRBX_HEADER = [
    "recv_utc", "gnss", "sv_id", "freq_id", "num_words",
]

POS_HEADER = [
    "recv_utc", "tow_s", "lat_deg", "lon_deg", "alt_m",
    "fix_quality", "num_sv", "hdop",
]


# ============================================================
# メイン処理
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="PPK Step3: 生観測値 CSV ロガー")
    parser.add_argument("--port",     default=SERIAL_PORT,   help=f"シリアルポート (default: {SERIAL_PORT})")
    parser.add_argument("--baud",     type=int, default=BAUD, help=f"ボーレート (default: {BAUD})")
    parser.add_argument("--duration", type=int, default=0,   help="記録秒数 (0=無制限, Ctrl+C で停止)")
    parser.add_argument("--out",      default=DEFAULT_OUTDIR, help=f"出力ディレクトリ (default: {DEFAULT_OUTDIR})")
    parser.add_argument("--no-enable", action="store_true",   help="RAWX 有効化をスキップ")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    rawx_path  = os.path.join(args.out, f"ppk_raw_{ts}.csv")
    sfrbx_path = os.path.join(args.out, f"ppk_nav_{ts}.csv")
    pos_path   = os.path.join(args.out, f"ppk_pos_{ts}.csv")

    print("=" * 60)
    print("PPK テスト Step 3: 生観測値 CSV ロガー")
    print("=" * 60)
    print(f"  ポート       : {args.port} @ {args.baud} baud")
    print(f"  記録時間     : {'無制限 (Ctrl+C で停止)' if args.duration == 0 else f'{args.duration} 秒'}")
    print(f"  RAWX CSV     : {rawx_path}")
    print(f"  SFRBX CSV    : {sfrbx_path}")
    print(f"  NMEA位置 CSV : {pos_path}")

    try:
        ser = serial.Serial(args.port, args.baud, timeout=1)
    except serial.SerialException as e:
        print(f"[エラー] シリアルポートを開けません: {e}")
        sys.exit(1)

    # F9P 設定
    if not args.no_enable:
        print("\n[設定] RXM-RAWX / RXM-SFRBX を有効化…")
        enable_rawx(ser)

    # CSV ファイルをオープン
    rawx_f  = open(rawx_path,  "w", newline="", encoding="utf-8")
    sfrbx_f = open(sfrbx_path, "w", newline="", encoding="utf-8")
    pos_f   = open(pos_path,   "w", newline="", encoding="utf-8")

    rawx_w  = csv.writer(rawx_f)
    sfrbx_w = csv.writer(sfrbx_f)
    pos_w   = csv.writer(pos_f)

    rawx_w.writerow(RAWX_HEADER)
    sfrbx_w.writerow(SFRBX_HEADER)
    pos_w.writerow(POS_HEADER)

    ubr = UBXReader(ser, protfilter=UBX_PROTOCOL | NMEA_PROTOCOL)

    # parsebitfield=0: X1型 (trkStat等) を生バイトとして受け取る
    ubr = UBXReader(ser, protfilter=UBX_PROTOCOL | NMEA_PROTOCOL, parsebitfield=0)
    stats = defaultdict(int)
    start_t  = time.time()
    deadline = start_t + args.duration if args.duration > 0 else float("inf")
    last_print = start_t

    print("\n[記録中] Ctrl+C で停止\n")

    def _x1_to_int(value):
        if isinstance(value, (bytes, bytearray)):
            return value[0] if len(value) > 0 else 0
        if value is None:
            return ""
        return int(value)

    while running and time.time() < deadline:
        try:
            raw, parsed = ubr.read()
            if parsed is None:
                continue

            identity = parsed.identity if hasattr(parsed, "identity") else ""
            now_ut   = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

            # --------------------------------------------------------
            # RXM-RAWX
            # --------------------------------------------------------
            if identity == "RXM-RAWX":
                tow    = getattr(parsed, "rcvTow",  0.0)
                week   = getattr(parsed, "week",    0)
                leapS  = getattr(parsed, "leapS",   18)
                numMeas = getattr(parsed, "numMeas", 0)

                for i in range(1, numMeas + 1):
                    gnssId  = getattr(parsed, f"gnssId_{i:02d}",  0)
                    svId    = getattr(parsed, f"svId_{i:02d}",    0)
                    sigId   = getattr(parsed, f"sigId_{i:02d}",   0)
                    freqId  = getattr(parsed, f"freqId_{i:02d}",  0)
                    prMes   = getattr(parsed, f"prMes_{i:02d}",   None)
                    cpMes   = getattr(parsed, f"cpMes_{i:02d}",   None)
                    doMes   = getattr(parsed, f"doMes_{i:02d}",   None)
                    cno     = getattr(parsed, f"cno_{i:02d}",     None)
                    locktime= getattr(parsed, f"locktime_{i:02d}",None)
                    prStd   = getattr(parsed, f"prStdev_{i:02d}", None)
                    cpStd   = getattr(parsed, f"cpStdev_{i:02d}", None)
                    doStd   = getattr(parsed, f"doStdev_{i:02d}", None)
                    trkStat = getattr(parsed, f"trkStat_{i:02d}", 0)
                    # X1型はparsebitfield=0でbytesになる場合がある
                    if isinstance(trkStat, (bytes, bytearray)):
                        trkInt = trkStat[0] if len(trkStat) > 0 else 0
                    else:
                        trkInt = int(trkStat) if trkStat is not None else 0
                    prStdInt = _x1_to_int(prStd)
                    cpStdInt = _x1_to_int(cpStd)
                    doStdInt = _x1_to_int(doStd)
                    pr_valid = int(bool(trkInt & TRKSTAT_PRVALID))
                    cp_valid = int(bool(trkInt & TRKSTAT_CPVALID))
                    hc_valid = int(bool(trkInt & TRKSTAT_HALFCYC))

                    gnss_name = GNSS_NAMES.get(gnssId, str(gnssId))

                    rawx_w.writerow([
                        f"{tow:.6f}", week, leapS,
                        gnss_name, svId, sigId, freqId,
                        f"{prMes:.6f}"  if prMes   is not None else "",
                        f"{cpMes:.6f}"  if cpMes   is not None else "",
                        f"{doMes:.4f}"  if doMes   is not None else "",
                        cno if cno is not None else "",
                        locktime if locktime is not None else "",
                        prStdInt,
                        cpStdInt,
                        doStdInt,
                        pr_valid, cp_valid, hc_valid,
                        now_ut,
                    ])

                stats["rawx"] += 1
                stats["meas"] += numMeas
                rawx_f.flush()

            # --------------------------------------------------------
            # RXM-SFRBX
            # --------------------------------------------------------
            elif identity == "RXM-SFRBX":
                gnssId  = getattr(parsed, "gnssId",  0)
                svId    = getattr(parsed, "svId",    0)
                freqId  = getattr(parsed, "freqId",  0)
                numWords= getattr(parsed, "numWords",0)
                gnss_name = GNSS_NAMES.get(gnssId, str(gnssId))
                sfrbx_w.writerow([now_ut, gnss_name, svId, freqId, numWords])
                stats["sfrbx"] += 1
                sfrbx_f.flush()

            # --------------------------------------------------------
            # NMEA-GGA (参照位置)
            # --------------------------------------------------------
            elif hasattr(parsed, "lat") and hasattr(parsed, "quality"):
                lat  = getattr(parsed, "lat",    None)
                lon  = getattr(parsed, "lon",    None)
                alt  = getattr(parsed, "alt",    None)
                qual = getattr(parsed, "quality",0)
                nsv  = getattr(parsed, "numSV",  None)
                hdop = getattr(parsed, "HDOP",   None)
                if lat and lon:
                    pos_w.writerow([
                        now_ut, "",
                        f"{lat:.8f}", f"{lon:.8f}",
                        f"{alt:.3f}" if alt is not None else "",
                        qual, nsv, hdop,
                    ])
                    stats["gga"] += 1
                    pos_f.flush()

        except KeyboardInterrupt:
            break
        except Exception as err:
            print(f"[WARN] parse/write error: {err}")

        # --- 進捗表示 (10秒ごと) ---
        now = time.time()
        if now - last_print >= 10:
            elapsed = int(now - start_t)
            print(f"  [{elapsed:5d}s] RAWX:{stats['rawx']:5d}件  "
                  f"計測:{stats['meas']:6d}点  "
                  f"SFRBX:{stats['sfrbx']:5d}件  "
                  f"GGA:{stats['gga']:5d}件")
            last_print = now

    # --- 終了処理 ---
    rawx_f.close()
    sfrbx_f.close()
    pos_f.close()
    ser.close()

    elapsed = int(time.time() - start_t)
    print("\n" + "=" * 60)
    print(f"記録完了 (経過 {elapsed}s)")
    print(f"  RAWX エポック数 : {stats['rawx']}")
    print(f"  計測値総数      : {stats['meas']}")
    print(f"  SFRBX フレーム  : {stats['sfrbx']}")
    print(f"  GGA 位置        : {stats['gga']}")
    print(f"\n出力ファイル:")
    print(f"  {rawx_path}")
    print(f"  {sfrbx_path}")
    print(f"  {pos_path}")

    if stats["rawx"] == 0:
        print("\n❌ RAWX が記録されませんでした。")
        print("   先に test_01_rawx_enable.py を実行してください。")
    else:
        print(f"\n✅ PPK ログ記録完了。RTKLIB 等で後処理が可能です。")


if __name__ == "__main__":
    main()
