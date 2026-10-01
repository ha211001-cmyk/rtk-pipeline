#!/usr/bin/env python3
"""
udp_mavlink_rover.py — 移動局側（ラズパイ）: UDP受信 → MAVLink GPS_RTCM_DATA 注入 + RTK定量判定

本番アーキテクチャ（構成B）のローバー側スクリプト。

MacBook（基地局側）から WiFi 経由の UDP で送られてくる RTCM3 補正データを受信し、
MAVLink GPS_RTCM_DATA (ID:233) で ArduPilot（フライトコントローラー）へ注入する。
ArduPilot が DroneCAN 経由で移動局 H-RTK F9P に転送し、RTK Fix を実現する。

さらに、MAVLink の GPS_RAW_INT.fix_type を時系列で記録し、
gcs/fix_metrics.compute_metrics() で RTK-FIXED 到達・維持率・FLOAT遷移・TTFF を
定量判定し、PASS/FAIL レポート（JSON + fix_type CSV）を保存する。

システム構成（本番）:
  [基地局 F9P] --USB--> [MacBook] --WiFi(UDP)--> [ラズパイ] --UART(MAVLink)--> [Pixhawk] --DroneCAN--> [移動局 F9P]
                          └ udp_base_sender.py ──▶ 本スクリプト（受信・注入・判定）

rtk_base_mavlink/ の MavlinkComm / RtcmInjector と、gcs/fix_metrics を再利用する。

使い方:
    python3 udp_mavlink_rover.py
    python3 udp_mavlink_rover.py --port 50010 --mavlink-port /dev/ttyAMA0 --baud 921600
    python3 udp_mavlink_rover.py --duration 300   # 300秒の観測で自動終了 + レポート保存
"""

import argparse
import csv
import json
import logging
import socket
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import udp_seq  # noqa: E402 - 同一ディレクトリの連番ヘッダモジュール

# rtk_base_mavlink / gcs を import パスに追加
_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (_REPO_ROOT, _REPO_ROOT / "rtk_base_mavlink", _REPO_ROOT / "gcs"):
    if _p.is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from mavlink_comm import MavlinkComm  # noqa: E402
from rtcm_injector import RtcmInjector  # noqa: E402
from gcs.fix_metrics import compute_metrics, fix_name  # noqa: E402


DEFAULT_UDP_PORT = 50010
DEFAULT_MAVLINK_PORT = "/dev/ttyAMA0"
DEFAULT_MAVLINK_BAUD = 921600


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="UDP受信 → MAVLink GPS_RTCM_DATA注入（ラズパイ側）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--port", type=int, default=DEFAULT_UDP_PORT,
                   help="UDP受信ポート番号")
    p.add_argument("--mavlink-port", default=DEFAULT_MAVLINK_PORT,
                   help="MAVLink接続ポート（フライトコントローラー）")
    p.add_argument("--baud", type=int, default=DEFAULT_MAVLINK_BAUD,
                   help="MAVLinkボーレート")
    p.add_argument("--rtscts", action=argparse.BooleanOptionalAction,
                   default=True,
                   help="RTS/CTSフロー制御（既定: 有効。--no-rtscts で無効化）")
    p.add_argument("--max-packet-size", type=int, default=180,
                   help="GPS_RTCM_DATA 1パケット最大サイズ")
    p.add_argument("--max-fragments", type=int, default=4,
                   help="1フレームあたり最大分割数")
    p.add_argument("--seq-header", action="store_true",
                   help="UDPペイロードの連番ヘッダを解析して欠落を検出する")
    p.add_argument("--duration", type=float, default=0.0,
                   help="観測時間[秒]（>0 で自動終了しレポート保存。0 は Ctrl+C まで継続）")
    p.add_argument("--report-dir", default=str(Path(__file__).resolve().parent / "reports"),
                   help="RTK判定レポート（JSON/CSV）の出力先")
    return p.parse_args()


# ---------------------------------------------------------------------------
# RTK 定量判定（gcs/fix_metrics.compute_metrics を再利用）
# ---------------------------------------------------------------------------
RTK_CRITERIA = {
    "fixed_rate_pct_min": 80.0,    # FIXED 維持率の下限 [%]
    "max_float_transitions": 5,    # FLOAT 遷移回数の上限
    "ttff_sec_max": 120.0,         # TTFF の上限 [秒]
}


def _check(name: str, ok: bool, expected: Any = None, actual: Any = None,
           message: str = "") -> Dict[str, Any]:
    return {"name": name, "ok": bool(ok), "expected": expected,
            "actual": actual, "message": message}


def evaluate_rtk(metrics: Dict[str, Any],
                 criteria: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """compute_metrics() の結果から RTK-FIXED 到達・維持の PASS/FAIL を判定する。"""
    c = dict(RTK_CRITERIA)
    if criteria:
        c.update(criteria)

    reached = bool(metrics.get("reached_fixed"))
    fixed_rate = float(metrics.get("fixed_rate_pct", 0.0) or 0.0)
    float_cnt = int(metrics.get("float_transition_count", 0) or 0)
    ttff = metrics.get("ttff_sec")

    checks = [
        _check("reached_fixed", reached, True, reached,
               "RTK_FIXED 到達" if reached else "RTK_FIXED 未到達"),
        _check("fixed_rate_min", reached and fixed_rate >= c["fixed_rate_pct_min"],
               ">= %.1f %%" % c["fixed_rate_pct_min"], "%.1f %%" % fixed_rate,
               "FIXED 維持率（全期間）"),
        _check("float_transition_max", float_cnt <= c["max_float_transitions"],
               "<= %d 回" % c["max_float_transitions"], "%d 回" % float_cnt,
               "FLOAT 遷移回数"),
    ]
    if reached:
        checks.append(_check(
            "ttff_max", ttff is not None and float(ttff) <= c["ttff_sec_max"],
            "<= %.1f 秒" % c["ttff_sec_max"],
            "n/a" if ttff is None else "%.1f 秒" % float(ttff),
            "TTFF（初回 FIXED）"))

    ok = all(ch["ok"] for ch in checks)
    if not reached:
        summary = "RTK_FIXED に到達しませんでした"
    elif ok:
        summary = ("FIXED 維持率 %.1f%% / FLOAT 遷移 %d 回 / TTFF %.1f 秒"
                   % (fixed_rate, float_cnt, float(ttff or 0.0)))
    else:
        summary = "RTK_FIXED には到達したが定量基準を満たしませんでした"
    return {"status": "PASS" if ok else "FAIL", "summary": summary, "checks": checks}


def write_series_csv(series: List[Dict[str, Any]], path: Path) -> None:
    """fix_type 時系列を CSV として保存する。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["timestamp", "elapsed_sec", "fix_type", "fix_name"])
        w.writeheader()
        for row in series:
            w.writerow({
                "timestamp": row.get("ts", ""),
                "elapsed_sec": "%.2f" % (row.get("t", 0.0) or 0.0),
                "fix_type": row.get("fix_type"),
                "fix_name": fix_name(row.get("fix_type", 0)),
            })


def save_report(series: List[Dict[str, Any]], injector: RtcmInjector,
                udp_stats: Dict[str, Any], args: argparse.Namespace,
                metrics: Dict[str, Any], verdict: Dict[str, Any]) -> None:
    """RTK 判定レポートを JSON + fix_type CSV として保存する。"""
    out_dir = Path(args.report_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    payload = {
        "overall": {"status": verdict["status"]},
        "summary": verdict["summary"],
        "checks": verdict["checks"],
        "rtk_metrics": metrics,
        "injection": dict(injector.stats),
        "udp": udp_stats,
        "fix_type_series": series,
        "criteria": RTK_CRITERIA,
    }
    json_path = out_dir / ("rtk_report_%s.json" % ts)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    print("[LOG] JSON レポート: %s" % json_path)

    csv_path = out_dir / ("fix_type_%s.csv" % ts)
    write_series_csv(series, csv_path)
    print("[LOG] fix_type CSV: %s" % csv_path)


def print_local_ip() -> None:
    """このラズパイ自身のIPを表示する（MacBook側 --host に使う）"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            print("[INFO] このラズパイのIP: %s" % s.getsockname()[0])
            print("       → MacBook側 udp_base_sender.py の --host にこのIPを指定")
    except Exception:
        pass


def extract_rtcm_frames(buf: bytearray):
    """バッファから RTCM3 フレーム（0xD3 始まり）を1つずつ yield する

    base側は1フレーム=1UDPパケットで送るが、念のため複数/断片にも対応。
    """
    while len(buf) >= 6:
        if buf[0] != 0xD3:
            buf.pop(0)
            continue
        reserved = buf[1] >> 2
        if reserved != 0:
            buf.pop(0)
            continue
        frame_len = ((buf[1] & 0x03) << 8) | buf[2]
        if frame_len > 1023:
            buf.pop(0)
            continue
        total = 6 + frame_len
        if len(buf) < total:
            break
        yield bytes(buf[:total])
        del buf[:total]


def udp_inject_loop(sock: socket.socket, injector: RtcmInjector,
                    mavlink: MavlinkComm, seq_header: bool = False,
                    duration: float = 0.0,
                    sample_interval: float = 1.0) -> Dict[str, Any]:
    """UDPで受信した RTCM を MAVLink GPS_RTCM_DATA として注入しつつ、
    fix_type 時系列を収集する。

    seq_header=True のとき、UDP ペイロード先頭の連番ヘッダを剥がして
    UDP 層の欠落（ロス）を検出・集計する。RTCM バイト列は変更しない。

    duration > 0 の場合は指定秒で自動終了する。
    戻り値は bytes_received / udp_packets_received / frames_received /
    series（fix_type 時系列）を含む dict。
    """
    bytes_received = 0
    udp_packets_received = 0
    frames_received = 0
    tracker = udp_seq.SeqLossTracker() if seq_header else None
    last_status = time.time()
    last_frame_time = time.time()
    last_sample = time.monotonic()
    start = time.monotonic()           # 観測時間カウント用（--duration）
    series: List[Dict[str, Any]] = []
    prev_fix: Optional[int] = None
    rtcm_start: Optional[float] = None  # 初回 RTCM 注入時刻（TTFF 起点）

    while True:
        try:
            sock.settimeout(0.5)
            data, _addr = sock.recvfrom(65535)
            if not data:
                continue
            bytes_received += len(data)
            udp_packets_received += 1

            rtcm_payload = data
            if tracker is not None:
                is_seq, seq, rtcm_payload = udp_seq.unpack_seq_payload(data)
                if is_seq:
                    tracker.update(seq)

            for frame in extract_rtcm_frames(bytearray(rtcm_payload)):
                frames_received += 1
                injector.inject_frame(frame)
                last_frame_time = time.time()
                if rtcm_start is None:
                    rtcm_start = time.monotonic()
                    print("[INFO] 初回 RTCM 注入（TTFF 計測開始）")
        except socket.timeout:
            pass
        except KeyboardInterrupt:
            break
        except Exception as e:  # noqa: BLE001
            print("[UDP Error] %s" % e)
            time.sleep(0.1)

        now = time.monotonic()

        # fix_type サンプリング（sample_interval 毎。初回 RTCM 注入後から計測）
        if now - last_sample >= sample_interval:
            last_sample = now
            if rtcm_start is not None:
                pos = mavlink.get_gps_position()
                ft = pos.get("fix_type")
                if ft is not None:
                    t = now - rtcm_start
                    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    series.append({"t": t, "ts": ts, "fix_type": int(ft)})
                    if prev_fix is not None and ft != prev_fix:
                        print("[遷移 %.1fs] %s -> %s" % (t, fix_name(prev_fix), fix_name(ft)))
                    prev_fix = ft

        if time.time() - last_status >= 5:
            pos = mavlink.get_gps_position()
            elapsed = time.time() - last_frame_time
            ts = datetime.now().strftime("%H:%M:%S")
            base = pos.get("baseline_m")
            base_s = ("%.1fm" % base) if base is not None else "?"
            lat = pos.get("lat")
            lon = pos.get("lon")
            pos_s = ("%.7f,%.7f" % (lat, lon)) if (lat is not None and lon is not None) else "?"
            udp_lost = tracker.packets_lost if tracker is not None else 0
            loss_pct = (tracker.loss_rate * 100.0) if tracker is not None else 0.0
            print("[STATUS %s] injected=%d dropped=%d frames_recv=%d bytes=%d | "
                  "UDP recv=%d lost=%d (loss %.2f%%) | GPS:%s sats=%s "
                  "nsats=%s base=%s pos=%s | 最終RTCMから%.1f秒" %
                  (ts,
                   injector.stats["frames_injected"],
                   injector.stats["frames_dropped"],
                   frames_received,
                   bytes_received,
                   udp_packets_received,
                   udp_lost,
                   loss_pct,
                   pos.get("fix_name", "?"),
                   pos.get("satellites", 0),
                   pos.get("rtk_nsats", 0),
                   base_s,
                   pos_s,
                   elapsed))
            last_status = time.time()

        if duration > 0 and (now - start) >= duration:
            print("[INFO] 指定観測時間 %.1f 秒に達したため終了します" % duration)
            break

    return {
        "bytes_received": bytes_received,
        "udp_packets_received": udp_packets_received,
        "frames_received": frames_received,
        "series": series,
        "loss": {
            "packets_lost": tracker.packets_lost if tracker else 0,
            "loss_rate": tracker.loss_rate if tracker else 0.0,
        },
    }


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="[%(asctime)s] %(name)s: %(message)s")

    print("=" * 60)
    print("UDP受信 → MAVLink GPS_RTCM_DATA 注入（移動局側）")
    print("=" * 60)

    rtscts = args.rtscts
    mavlink = MavlinkComm(port=args.mavlink_port, baud=args.baud, rtscts=rtscts)
    if not mavlink.connect():
        print("[ERROR] MAVLink接続に失敗しました。"
              "Pixhawkの電源・接続・ボーレートを確認してください。")
        sys.exit(1)

    # PL011 UART の受信ハングアップ(EOF)対策として CLOCAL を設定
    try:
        import termios
        _fd = mavlink._master.port.fd
        _attrs = termios.tcgetattr(_fd)
        _attrs[2] |= termios.CLOCAL
        termios.tcsetattr(_fd, termios.TCSANOW, _attrs)
        print("[INFO] CLOCAL 設定済み（受信ハングアップ対策）")
    except Exception as _e:
        print("[WARN] CLOCAL 設定に失敗: %s" % _e)

    mavlink.start_gps_stream()
    time.sleep(1)

    injector = RtcmInjector(mavlink_comm=mavlink,
                            max_packet_size=args.max_packet_size,
                            max_fragments=args.max_fragments)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", args.port))
    except OSError as e:
        print("[ERROR] UDPポート %d のbindに失敗: %s" % (args.port, e))
        mavlink.disconnect()
        sys.exit(1)

    print_local_ip()
    print("=" * 60)
    print("UDP受信待機中: 0.0.0.0:%d" % args.port)
    print("連番ヘッダ解析: %s" % ("有効(欠落検出用)" if args.seq_header else "無効"))
    if args.duration > 0:
        print("観測時間: %.1f 秒（自動終了 + レポート保存）" % args.duration)
    print("Ctrl+C で終了")
    print("=" * 60)

    result: Dict[str, Any] = {}
    try:
        result = udp_inject_loop(sock, injector, mavlink,
                                 seq_header=args.seq_header,
                                 duration=args.duration)
    except KeyboardInterrupt:
        print("\n[INFO] Ctrl+C で終了します")
    finally:
        sock.close()
        mavlink.disconnect()
        print("[INFO] 終了（injected=%d dropped=%d bytes=%d）" %
              (injector.stats["frames_injected"],
               injector.stats["frames_dropped"],
               result.get("bytes_received", 0)))

    # RTK 定量判定 + レポート保存
    series = result.get("series", [])
    metrics = compute_metrics(series)
    verdict = evaluate_rtk(metrics)
    udp_stats = {
        "packets_received": result.get("udp_packets_received", 0),
        "bytes_received": result.get("bytes_received", 0),
        "frames_received": result.get("frames_received", 0),
        "packets_lost": result.get("loss", {}).get("packets_lost", 0),
        "loss_rate": result.get("loss", {}).get("loss_rate", 0.0),
    }
    save_report(series, injector, udp_stats, args, metrics, verdict)

    print()
    print("=" * 60)
    print("RTK 定量判定: %s — %s" % (verdict["status"], verdict["summary"]))
    for ch in verdict["checks"]:
        mark = "✓" if ch["ok"] else "✗"
        exp = "" if ch["expected"] is None else " (期待: %s)" % ch["expected"]
        act = "" if ch["actual"] is None else " = %s" % ch["actual"]
        msg = (" / " + ch["message"]) if ch["message"] else ""
        print("  [%s] %-22s%s%s%s" % (mark, ch["name"], exp, act, msg))
    print("=" * 60)


if __name__ == "__main__":
    main()
