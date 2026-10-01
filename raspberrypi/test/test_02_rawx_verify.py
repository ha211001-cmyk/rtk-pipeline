#!/usr/bin/env python3
"""
[PPK テスト Step 2] RXM-RAWX メッセージ内容の詳細検証
=======================================================
test_01_rawx_enable.py で RAWX が受信できることを確認したら、
このスクリプトで各フィールドの内容を詳細に表示・検証する。

表示内容:
  - 衛星ごとの疑似距離・搬送波位相・ドップラー・CNR
  - 追跡ステータス (搬送波位相の有効性チェック)
  - GPSシステム (GPS/GLONASS/Galileo/BeiDou/QZSS) ごとの集計
  - 座標 (NMEA-GGA) との同期確認

前提:
  - test_01_rawx_enable.py を先に実行済み (RAWXが有効化されていること)
  - 再起動した場合は再度 test_01 の実行が必要
    (または --save オプションで BBR に保存済みであること)

使い方:
  python3 test_02_rawx_verify.py [--port /dev/ttyACM0] [--baud 38400] [--count 5]
"""

import sys
import time
import argparse
from collections import defaultdict

try:
    import serial
except ImportError:
    print("Error: pyserial が必要です。  pip install pyserial")
    sys.exit(1)

try:
    from pyubx2 import UBXReader, UBXMessage, UBX_PROTOCOL, NMEA_PROTOCOL, SET_LAYER_RAM, TXN_NONE
    from pynmeagps import NMEAReader
except ImportError:
    print("Error: pyubx2 / pynmeagps が必要です。  pip install pyubx2 pynmeagps")
    sys.exit(1)

# ============================================================
# 定数
# ============================================================
SERIAL_PORT = "/dev/ttyACM0"
BAUD        = 38400

# GNSS ID → 名前マッピング (u-blox 仕様)
GNSS_NAMES = {
    0: "GPS",
    1: "SBAS",
    2: "Galileo",
    3: "BeiDou",
    4: "IMES",
    5: "QZSS",
    6: "GLONASS",
}

# 追跡ステータスのビットフィールド (trkStat)
TRKSTAT_PRVALID  = 0x01  # 疑似距離有効
TRKSTAT_CPVALID  = 0x02  # 搬送波位相有効
TRKSTAT_HALFCYC  = 0x04  # ハーフサイクル有効
TRKSTAT_SUBHALFCYC = 0x08  # サブハーフサイクル有効


def ensure_rawx_enabled(ser):
    """RAWXがまだ有効でなければ有効化を試みる"""
    print("[INFO] RXM-RAWX/SFRBX 有効化コマンドを送信します…")
    # /dev/ttyACM0 は USB CDC → _USB キーを使う
    cfg = [
        ("CFG_USBOUTPROT_UBX",              1),
        ("CFG_MSGOUT_UBX_RXM_RAWX_USB",     1),
        ("CFG_MSGOUT_UBX_RXM_SFRBX_USB",    1),
    ]
    msg = UBXMessage.config_set(SET_LAYER_RAM, TXN_NONE, cfg)
    ser.write(msg.serialize())
    time.sleep(0.5)


def parse_trkstat(trkstat):
    """trkStat バイトを人間可読な文字列に変換"""
    flags = []
    if trkstat & TRKSTAT_PRVALID:
        flags.append("PR有効")
    if trkstat & TRKSTAT_CPVALID:
        flags.append("CP有効")
    if trkstat & TRKSTAT_HALFCYC:
        flags.append("HalfCyc有効")
    return ", ".join(flags) if flags else "無効"


def display_rawx(parsed, idx):
    """RXM-RAWX メッセージを詳細表示"""
    rcvTow  = getattr(parsed, "rcvTow",  "?")
    week    = getattr(parsed, "week",    "?")
    leapS   = getattr(parsed, "leapS",   "?")
    numMeas = getattr(parsed, "numMeas", 0)

    def _to_int(v):
        """X1 型 (bytes or int) を int に変換"""
        if isinstance(v, (bytes, bytearray)):
            return v[0] if len(v) > 0 else 0
        try:
            return int(v)
        except Exception:
            return 0

    print(f"\n{'='*60}")
    print(f"RXM-RAWX #{idx}  TOW={rcvTow:.3f}s  Week={week}  LeapS={leapS}")
    print(f"  衛星数: {numMeas}")
    print(f"  {'GNSS':8s} {'SVid':5s} {'SigId':6s} {'PR[m]':14s} {'CP[cyc]':14s} {'Dop[Hz]':10s} {'CNR[dBHz]':10s} {'状態'}")
    print(f"  {'-'*8} {'-'*5} {'-'*6} {'-'*14} {'-'*14} {'-'*10} {'-'*10} {'-'*12}")

    stats_by_gnss = defaultdict(int)
    cp_valid_count = 0

    for i in range(1, numMeas + 1):
        gnssId  = getattr(parsed, f"gnssId_{i:02d}",  None)
        svId    = getattr(parsed, f"svId_{i:02d}",    None)
        sigId   = getattr(parsed, f"sigId_{i:02d}",   None)
        prMes   = getattr(parsed, f"prMes_{i:02d}",   None)
        cpMes   = getattr(parsed, f"cpMes_{i:02d}",   None)
        doMes   = getattr(parsed, f"doMes_{i:02d}",   None)
        cno     = getattr(parsed, f"cno_{i:02d}",     None)
        trkStat = getattr(parsed, f"trkStat_{i:02d}", 0)
        trkInt  = _to_int(trkStat)
        gnss_name = GNSS_NAMES.get(gnssId, f"ID={gnssId}")
        pr_str  = f"{prMes:14.3f}" if prMes is not None else f"{'N/A':>14}"
        cp_str  = f"{cpMes:14.3f}" if cpMes is not None else f"{'N/A':>14}"
        dop_str = f"{doMes:10.2f}" if doMes is not None else f"{'N/A':>10}"
        cno_str = f"{cno:10d}"     if cno  is not None else f"{'N/A':>10}"
        stat_str = parse_trkstat(trkInt)

        print(f"  {gnss_name:8s} {str(svId):5s} {str(sigId):6s} {pr_str} {cp_str} {dop_str} {cno_str} {stat_str}")
        stats_by_gnss[gnss_name] += 1
        if trkInt & TRKSTAT_CPVALID:
            cp_valid_count += 1

    # 集計
    print(f"\n  GNSS別衛星数: " + "  ".join(f"{k}:{v}" for k, v in sorted(stats_by_gnss.items())))
    print(f"  搬送波位相有効数: {cp_valid_count}/{numMeas}")
    if cp_valid_count == 0:
        print("  ⚠️  搬送波位相が全て無効 → 前空視時間が短い可能性があります")
    elif cp_valid_count < numMeas // 2:
        print(f"  ⚠️  搬送波位相有効率が低い ({cp_valid_count}/{numMeas})")
    else:
        print(f"  ✅ 搬送波位相: {cp_valid_count}/{numMeas} 有効 → PPK キャリア演算可能")


def main():
    parser = argparse.ArgumentParser(description="PPK Step2: RXM-RAWX 内容詳細検証")
    parser.add_argument("--port",   default=SERIAL_PORT, help=f"シリアルポート (default: {SERIAL_PORT})")
    parser.add_argument("--baud",   type=int, default=BAUD, help=f"ボーレート (default: {BAUD})")
    parser.add_argument("--count",  type=int, default=5, help="表示する RAWX メッセージ数 (default: 5)")
    parser.add_argument("--no-enable", action="store_true", help="RAWX 有効化をスキップ (既に有効な場合)")
    args = parser.parse_args()

    print("=" * 60)
    print("PPK テスト Step 2: RXM-RAWX 内容詳細検証")
    print("=" * 60)
    print(f"  ポート: {args.port} @ {args.baud} baud")
    print(f"  表示数: {args.count} メッセージ")

    try:
        ser = serial.Serial(args.port, args.baud, timeout=1)
    except serial.SerialException as e:
        print(f"[エラー] シリアルポートを開けません: {e}")
        sys.exit(1)

    if not args.no_enable:
        ensure_rawx_enabled(ser)

    ubr = UBXReader(ser, protfilter=UBX_PROTOCOL | NMEA_PROTOCOL)
    # parsebitfield=0 で X1 型 (trkStat 等) を生バイトとして受け取る
    ubr = UBXReader(ser, protfilter=UBX_PROTOCOL | NMEA_PROTOCOL, parsebitfield=0)
    rawx_idx  = 0
    nmea_last = None
    deadline  = time.time() + 60  # 最大60秒待つ

    print(f"\n[受信中] RAWX {args.count} 件を表示して終了します (最大60秒)…")

    while rawx_idx < args.count and time.time() < deadline:
        try:
            raw, parsed = ubr.read()
            if parsed is None:
                continue

            identity = parsed.identity if hasattr(parsed, "identity") else ""

            if identity == "RXM-RAWX":
                rawx_idx += 1
                display_rawx(parsed, rawx_idx)

            # NMEA-GGA も表示 (座標確認)
            elif hasattr(parsed, "lat") and hasattr(parsed, "quality"):
                quality_map = {0: 'No Fix', 1: 'GPS Fix', 2: 'DGPS', 4: 'RTK Fixed', 5: 'RTK Float'}
                q = getattr(parsed, "quality", 0)
                lat = getattr(parsed, "lat", None)
                lon = getattr(parsed, "lon", None)
                if lat and lon:
                    print(f"\n  [GGA] {q} ({quality_map.get(q,'?')})  Lat={lat:.6f}  Lon={lon:.6f}")

        except KeyboardInterrupt:
            print("\n  Ctrl+C で停止")
            break
        except Exception:
            pass

    if rawx_idx == 0:
        print("\n❌ RAWX を受信できませんでした。")
        print("   先に test_01_rawx_enable.py を実行してください。")
    else:
        print(f"\n✅ RAWX {rawx_idx} 件の検証完了")
        print("   次のステップ: python3 test_03_ppk_logger.py")

    ser.close()


if __name__ == "__main__":
    main()
