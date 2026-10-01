#!/usr/bin/env python3
"""runner.py — GCS バックエンドコア（MAVLink 受信 + RTCM 送信の並行稼働）

本番アーキテクチャ（DroneCAN + MAVLink + UDP）の GCS 側バックエンド:

  [ローバー群] --UDP(MAVLink)--> [GCS PC]  MavlinkTelemetryReader（受信スレッド）
  [基地局 F9P] --USB--> [GCS PC] --UDP--> [ローバー群]  RtcmCaster（送信スレッド）

``GcsBackend`` がこの2つを別スレッドで並行稼働させ、``snapshot()`` で
機体ごとのステータス + RTCM 配信統計を一括取得できるようにする。
旧来の UBX シリアル/TCP 直読ロジックは削除済み。

使い方（ヘッドレス）:
    python3 -m gcs.integration.runner --mavlink-port 14550 \\
        --base-port /dev/ttyACM0 --dest 192.168.1.10:14550
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gcs.integration.sources import MavlinkTelemetryReader  # noqa: E402
from gcs.integration.rtcm_caster import RtcmCaster  # noqa: E402

DEFAULT_MAVLINK_PORT = 14550


def _parse_dest(text: str) -> Tuple[str, int]:
    """``host:port`` 形式の文字列を ``(host, port)`` に分解する。"""
    host, _, port = text.rpartition(":")
    if not host or not port:
        raise ValueError("送信先は host:port 形式で指定してください: %s" % text)
    return host, int(port)


class GcsBackend:
    """MAVLink 受信スレッドと RTCM 送信スレッドを並行稼働させる GCS バックエンド。

    Args:
        mavlink_host: MAVLink テレメトリを受信する UDP バインドアドレス。
        mavlink_port: MAVLink テレメトリを受信する UDP ポート。
        rtcm_source_port: 基地局 F9P のシリアルポート（省略時は RTCM 配信なし）。
        rtcm_source_baud: 基地局 F9P のボーレート。
        rtcm_destinations: RTCM 配信先 ``[(host, port), ...]``。
        reader/caster: テスト時に差し替え可能な reader/caster インスタンス。
    """

    def __init__(self,
                 mavlink_host: str = "0.0.0.0",
                 mavlink_port: int = DEFAULT_MAVLINK_PORT,
                 rtcm_source_port: Optional[str] = None,
                 rtcm_source_baud: int = 115200,
                 rtcm_destinations: Optional[List[Tuple[str, int]]] = None,
                 reader: Optional[MavlinkTelemetryReader] = None,
                 caster: Optional[RtcmCaster] = None):
        self.reader = reader or MavlinkTelemetryReader(host=mavlink_host,
                                                       port=mavlink_port)
        self.caster = caster or RtcmCaster(source_port=rtcm_source_port,
                                           source_baud=rtcm_source_baud)
        for host, port in (rtcm_destinations or []):
            self.caster.add_destination(host, port)

    def start(self) -> bool:
        """受信スレッドと送信スレッドを順に起動する。"""
        if not self.reader.start():
            return False
        if not self.caster.start():
            self.reader.stop()
            return False
        return True

    def stop(self) -> None:
        self.caster.stop()
        self.reader.stop()

    def snapshot(self) -> Dict[str, Any]:
        """機体ステータス + MAVLink/RTCM 統計を一括取得する。"""
        return {
            "vehicles": self.reader.vehicles(),
            "mavlink": dict(self.reader.stats),
            "rtcm": dict(self.caster.stats),
            "rtcm_destinations": [list(d) for d in self.caster.destinations()],
        }

    def is_running(self) -> bool:
        return bool(self.reader.is_running() and self.caster.is_running())


def _status_lines(backend: GcsBackend) -> List[str]:
    """コンソール表示用のステータス行を組み立てる。"""
    snap = backend.snapshot()
    lines = ["[GCS Backend] MAVLink受信=%s RTCM送信=%s"
             % ("ON" if backend.reader.is_running() else "OFF",
                "ON" if backend.caster.is_running() else "OFF")]
    vehicles = snap["vehicles"]
    if not vehicles:
        lines.append("  (機体からのテレメトリ未受信)")
    for sid in sorted(vehicles):
        v = vehicles[sid]
        fix = v.get("fix_name") or ("fix_type=%s" % v.get("fix_type"))
        mode = v.get("flight_mode") or "-"
        sats = v.get("satellites")
        batt = v.get("battery_voltage_v")
        batt_s = ("%.1fV" % batt) if batt is not None else "-"
        lines.append("  system_id=%-3d fix=%s sats=%s mode=%s batt=%s"
                     % (sid, fix, sats if sats is not None else "-", mode, batt_s))
    rtcm = snap["rtcm"]
    lines.append("  RTCM: frames_read=%d frames_sent=%d dests=%d send_errors=%d"
                 % (rtcm.get("frames_read", 0), rtcm.get("frames_sent", 0),
                    len(snap["rtcm_destinations"]), rtcm.get("send_errors", 0)))
    return lines


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="GCS バックエンドコア（MAVLink受信 + RTCM送信）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--mavlink-host", default="0.0.0.0",
                   help="MAVLink テレメトリを受信する UDP バインドアドレス")
    p.add_argument("--mavlink-port", type=int, default=DEFAULT_MAVLINK_PORT,
                   help="MAVLink テレメトリを受信する UDP ポート")
    p.add_argument("--base-port", default=None,
                   help="基地局 F9P のシリアルポート（例: /dev/ttyACM0）")
    p.add_argument("--base-baud", type=int, default=115200,
                   help="基地局 F9P のボーレート")
    p.add_argument("--dest", action="append", default=[], metavar="HOST:PORT",
                   help="RTCM 配信先 UDP エンドポイント（複数指定可）")
    p.add_argument("--interval", type=float, default=2.0,
                   help="ステータス表示間隔 [秒]")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    destinations: List[Tuple[str, int]] = []
    for text in args.dest:
        try:
            destinations.append(_parse_dest(text))
        except ValueError as e:
            print("[ERROR] %s" % e)
            return 2

    backend = GcsBackend(
        mavlink_host=args.mavlink_host,
        mavlink_port=args.mavlink_port,
        rtcm_source_port=args.base_port,
        rtcm_source_baud=args.base_baud,
        rtcm_destinations=destinations,
    )

    if not backend.start():
        print("[ERROR] GCS バックエンドを起動できませんでした")
        return 2

    print("=" * 70)
    print("GCS バックエンド稼働中（Ctrl+C で終了）")
    print("  MAVLink 受信: udpin://%s:%d" % (args.mavlink_host, args.mavlink_port))
    if args.base_port:
        dest_s = ", ".join("%s:%d" % d for d in destinations) or "(なし)"
        print("  RTCM 配信: %s @ %d bps -> %s" % (args.base_port, args.base_baud, dest_s))
    print("=" * 70)

    try:
        while True:
            for line in _status_lines(backend):
                print(line)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n[INFO] 終了します")
    finally:
        backend.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
