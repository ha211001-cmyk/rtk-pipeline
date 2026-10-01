#!/usr/bin/env python3
"""monitor.py — 複数ローバーの RELPOSNED をペアリングして表示・CSV 記録するドライバ

2 台のローバー（F9P 直結シリアル）から UBX-NAV-RELPOSNED を読み出し、
``RelposPairingBuffer`` で同一 iTOW（GPS 時刻エポック）にペアリングして
機体間相対位置（相対距離・相対方位・相対位置精度）を表示し、ペアリング後の
相対位置時系列を iTOW 付きで CSV に記録する。

重要要件（協調搬送本番）:
  - 両ローバーの RELPOSNED を「単に都度表示」せず、**同一 iTOW でペアリングしてから**
    差分（RELPOSNED_B - RELPOSNED_A）を取る。
  - エポックのズレ（delta_ms）と許容ウィンドウ（--match-window-ms）を比較し、
    揃わない場合は警告を表示する。
  - 全ローバーが同一基地局（refStationId 一致）から補正を受けることを確認する。

既存資産の再利用:
  - ``archive/udp/base_ubx_logger.py`` の ``auto_detect_port``（reader.py 経由）
  - ``pyubx2``（UBX-NAV-RELPOSNED のパース。reader.py 経由）

Usage:
    python3 gcs/relpos/monitor.py \\
        --rover-a-port /dev/cu.usbmodem101 --rover-b-port /dev/cu.usbmodem102

    # 集計ロジックのみ自己検証
    python3 gcs/relpos/monitor.py --selftest
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

# 実行位置に依存しない import
_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent.parent
for _p in (_SCRIPT_DIR, _REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from gcs.relpos.pairing import (  # noqa: E402
    PAIRED_CSV_FIELDS,
    PairedRelpos,
    RelposPairingBuffer,
)
from gcs.relpos.reader import UbxRelposReader, resolve_port  # noqa: E402

DEFAULT_MATCH_WINDOW_MS = 200
DEFAULT_DISPLAY_INTERVAL = 1.0
DEFAULT_POLL_INTERVAL = 0.1


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _format_delta(delta_ms: int) -> str:
    sign = "+" if delta_ms > 0 else ""
    return "%s%dms" % (sign, delta_ms)


def format_paired(p: PairedRelpos) -> str:
    """ペアリング結果を 1 行の人間可読文字列へ整形する。"""
    epoch = "OK(%s)" % _format_delta(p.delta_ms) if p.matched \
        else "NG(%s)" % _format_delta(p.delta_ms)
    ref = "OK" if p.ref_station_match \
        else "NG(A=%d,B=%d)" % (p.ref_station_a, p.ref_station_b)
    val = "OK" if p.valid else "INVALID(relPosValid)"
    hdg = "OK" if p.heading_valid else "n/a"
    return (
        "iTOW=%d epoch=%s refStation=%s | "
        "dist2D=%.3fm dist3D=%.3fm | bearing(A→B)=%.1f° | "
        "accH=%.3fm accV=%.3fm acc3D=%.3fm | valid=%s heading=%s"
        % (
            p.itow_ms, epoch, ref,
            p.distance_2d_m, p.distance_3d_m,
            p.bearing_ab_deg,
            p.acc_horizontal_m, p.acc_d_m, p.acc_3d_m,
            val, hdg,
        )
    )


def emit_warnings(p: PairedRelpos, out=None) -> None:
    """エポック不整合・refStationId 不整合の警告を表示する。"""
    out = out if out is not None else sys.stderr
    if not p.matched:
        print("[WARN] エポックが許容ウィンドウを超えて不整合: "
              "Δ=%s (itow_a=%d, itow_b=%d)"
              % (_format_delta(p.delta_ms), p.itow_a, p.itow_b), file=out)
    if not p.ref_station_match:
        print("[WARN] refStationId が不一致（同一基地局から補正を受ける前提）: "
              "A=%d, B=%d" % (p.ref_station_a, p.ref_station_b), file=out)
    if not p.valid:
        print("[WARN] relPosValid が立っていないローバーがあります（RTK 未確定）",
              file=out)


def build_csv_row(p: PairedRelpos) -> Dict[str, str]:
    """ペアリング結果を CSV 行 dict へ変換する（utc_time を付与）。"""
    row = p.to_csv_row(PAIRED_CSV_FIELDS)
    row["utc_time"] = _utc_now()
    return row


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="複数ローバーの RELPOSNED を iTOW でペアリングして表示・CSV 記録",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--rover-a-port", default=None,
                   help="ローバー A の F9P シリアルポート（省略時は自動検出）")
    p.add_argument("--rover-b-port", default=None,
                   help="ローバー B の F9P シリアルポート（省略時は自動検出）")
    p.add_argument("--baud", type=int, default=115200, help="シリアルボーレート")
    p.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL,
                   help="RELPOSNED ポーリング間隔(秒)")
    p.add_argument("--match-window-ms", type=int, default=DEFAULT_MATCH_WINDOW_MS,
                   help="許容エポック差（マッチング許容ウィンドウ）[ms]")
    p.add_argument("--csv", default=None,
                   help="CSV 出力先（省略時: gcs/relpos/logs/relpos_<ts>.csv）")
    p.add_argument("--display-interval", type=float, default=DEFAULT_DISPLAY_INTERVAL,
                   help="待機中ステータスの表示間隔(秒)")
    p.add_argument("--duration", type=float, default=0.0,
                   help="記録秒数（0 で無限。Ctrl+C で停止）")
    p.add_argument("--selftest", action="store_true",
                   help="ペアリングロジックの自己検証のみ実行")
    return p


def _open_reader(port_arg: Optional[str], rover_id: str, baud: int,
                 poll_interval: float) -> Optional[UbxRelposReader]:
    port = resolve_port(port_arg)
    if not port:
        print("[WARN] ローバー %s のシリアルポートを検出できません "
              "(--rover-%s-port で明示指定)" % (rover_id, rover_id.lower()))
        return None
    reader = UbxRelposReader(port, rover_id=rover_id, baud=baud,
                             poll_interval=poll_interval)
    if not reader.start():
        return None
    return reader


def main() -> int:
    args = build_parser().parse_args()

    if args.selftest:
        from gcs.relpos.pairing import self_test
        ok = self_test()
        print("relpos monitor selftest: %s" % ("OK" if ok else "FAILED"))
        return 0 if ok else 1

    if args.match_window_ms < 0:
        print("[ERROR] --match-window-ms は 0 以上で指定してください")
        return 1

    # 2 ローバーのリーダーを準備
    readers: List[UbxRelposReader] = []
    for port_arg, rid in ((args.rover_a_port, "A"), (args.rover_b_port, "B")):
        r = _open_reader(port_arg, rid, args.baud, args.poll_interval)
        if r is not None:
            readers.append(r)
    if len(readers) < 2:
        print("[ERROR] 2 台のローバーを接続できませんでした（A/B 両方必要）")
        for r in readers:
            r.close()
        return 1

    # CSV 出力先
    if args.csv is None:
        log_dir = _SCRIPT_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.csv = str(log_dir / ("relpos_%s.csv" % ts))

    csv_fh = open(args.csv, "w", newline="")
    writer = csv.DictWriter(csv_fh, fieldnames=PAIRED_CSV_FIELDS)
    writer.writeheader()
    csv_fh.flush()
    print("[LOG] CSV: %s" % args.csv)

    buffer = RelposPairingBuffer(rover_ids=("A", "B"),
                                 match_window_ms=args.match_window_ms)

    print("=" * 66)
    print("複数ローバー RELPOSNED ペアリング開始（Ctrl+C で停止）")
    print("  match_window = %d ms" % args.match_window_ms)
    print("  A = %s, B = %s" % (readers[0].port, readers[1].port))
    print("=" * 66)

    last_itow: Dict[str, Optional[int]] = {"A": None, "B": None}
    last_logged_itow: Optional[int] = None
    start_time = time.time()
    last_status = 0.0

    try:
        while True:
            now = time.time()
            elapsed = now - start_time
            if args.duration > 0 and elapsed >= args.duration:
                break

            # 各ローバーの新着サンプルをバッファへ投入
            new_pair: Optional[PairedRelpos] = None
            for r in readers:
                s = r.latest()
                if s is None:
                    continue
                if last_itow[s.rover_id] == s.itow_ms:
                    continue
                last_itow[s.rover_id] = s.itow_ms
                p = buffer.update(s)
                if p is not None:
                    new_pair = p

            # 新たなペア（新 iTOW）を表示・記録
            if new_pair is not None and new_pair.itow_ms != last_logged_itow:
                last_logged_itow = new_pair.itow_ms
                emit_warnings(new_pair)
                line = format_paired(new_pair)
                print("[%s] %s"
                      % (datetime.now().strftime("%H:%M:%S.%f")[:-3], line))
                writer.writerow(build_csv_row(new_pair))
                csv_fh.flush()
            elif now - last_status >= args.display_interval:
                # 待機中（片方未受信など）の進捗表示
                recv = " / ".join("%s=%d" % (r.rover_id, r.recv_count())
                                  for r in readers)
                print("[%s] 待機中 recv(%s) paired=%d matched=%d"
                      % (datetime.now().strftime("%H:%M:%S.%f")[:-3], recv,
                         buffer.stats["paired"], buffer.stats["matched"]))
                last_status = now

            time.sleep(0.02)
    except KeyboardInterrupt:
        print("\n[INFO] Ctrl+C で終了します")
    finally:
        for r in readers:
            r.close()
        csv_fh.close()

    print()
    print("=" * 66)
    print("ペアリング集計")
    print("=" * 66)
    print("  投入サンプル      : %d" % buffer.stats["updates"])
    print("  ペア生成          : %d" % buffer.stats["paired"])
    print("  エポック整合      : %d" % buffer.stats["matched"])
    print("  エポック不整合    : %d" % buffer.stats["mismatched"])
    print("  refStation 不整合 : %d" % buffer.stats["ref_station_mismatch"])
    print("  保存先            : %s" % args.csv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
