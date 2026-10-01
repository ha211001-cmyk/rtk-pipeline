#!/usr/bin/env python3
"""
ローバー側 補正データ連続監視（DroneCAN tunnel 経由）

Pixhawk の USB(MAVLink) 経由で CAN にアクセスし、DroneCAN の
``uavcan.tunnel.Targetted``（target_node_id=125, serial_id=0）で運ばれる
F9P 内部 UART1 のバイト列から ``UBX-RXM-RTCM``（class=0x02, id=0x32）を
抽出し、以下を連続監視する。

- UBX-RXM-RTCM のパース（crcFailed / msgUsed / msgType / refStation）
- 最終RTCM受信からの経過秒（RTK age / correction age）と閾値アラート
- CRC エラー率の集計
- 自作 GCS に統合可能な JSON Lines 出力

``archive/udp/f9p_rtcm_monitor.py`` をベースに、監視ロジックを ``rtcm_monitor.py``
（クラス化済み）へ置き換えたもの。

出力形式:
    stdout に JSON Lines（1行 = 1スナップショット）を出力する。
    人間向けの進捗・アラート・サマリーは stderr に出力する。
    ``--json-file`` を指定すると同じ JSON Lines をファイルにも書き出す。

前提:
    - MAVCAN ドライバが起動時に MAV_CMD_CAN_FORWARD を自動送信し
      CAN_FRAME 転送を有効化する。
    - UBX-RXM-RTCM はポーリング不要で、RTCM 受信のたびに F9P が自動出力する。
    - 読み取り専用のため UART Locking は行わない。ただし Mission Planner 等が
      同じポートを同時に使っていないことを事前に確認すること。

使用例:
    source ~/Mavlink_venv/bin/activate
    python3 gcs/dronecan_rtcm_monitor.py --monitor-rtcm 60
    python3 gcs/dronecan_rtcm_monitor.py --monitor-rtcm 60 \
        --port /dev/cu.usbmodem103 --target-node 125 \
        --age-alert-threshold 10 --json-file logs/rtcm_monitor.jsonl
"""

import argparse
import json
import sys
import time
from pathlib import Path

# 実行位置に依存しない import（スクリプト自身のディレクトリとリポジトリルート）
_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
for _p in (_SCRIPT_DIR, _REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from rtcm_monitor import (  # noqa: E402
    CorrectionMonitor,
)

try:
    import dronecan  # noqa: E402
    from dronecan import uavcan  # noqa: E402
except ImportError:
    sys.exit("エラー: dronecan がインストールされていません。\n"
             "  source ~/Mavlink_venv/bin/activate")


def _emit_json(mon: CorrectionMonitor, json_out) -> None:
    """1スナップショットを JSON Lines として stdout / ファイルへ出力する。"""
    line = json.dumps(mon.snapshot(), ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write(line + "\n")
    sys.stdout.flush()
    if json_out is not None:
        json_out.write(line + "\n")
        json_out.flush()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="DroneCAN tunnel 経由で F9P の補正データを連続監視する"
    )
    parser.add_argument(
        "--monitor-rtcm",
        type=float,
        required=True,
        help="受信を継続する秒数（例: 30〜60）",
    )
    parser.add_argument(
        "--port",
        default="/dev/cu.usbmodem101",
        help="Pixhawk の MAVLink USB ポート (default: /dev/cu.usbmodem101)",
    )
    parser.add_argument(
        "--target-node",
        type=int,
        default=125,
        help="F9P/GPS の DroneCAN node_id (default: 125)",
    )
    parser.add_argument(
        "--serial-id",
        type=int,
        default=0,
        help="uavcan.tunnel.Targetted の serial_id (default: 0)",
    )
    parser.add_argument(
        "--local-node",
        type=int,
        default=100,
        help="本スクリプト自身の DroneCAN node_id (default: 100)",
    )
    parser.add_argument(
        "--bus-number",
        type=int,
        default=1,
        help="MAVCAN が接続する CAN バス番号(1始まり, default: 1)",
    )
    parser.add_argument(
        "--mavlink-target-system",
        type=int,
        default=0,
        help="MAVLINK target_system (0=自動, default: 0)",
    )
    parser.add_argument(
        "--age-alert-threshold",
        type=float,
        default=10.0,
        help="RTK age のアラート閾値[秒] (default: 10.0)",
    )
    parser.add_argument(
        "--age-warn-threshold",
        type=float,
        default=5.0,
        help="RTK age の警告閾値[秒] (default: 5.0)",
    )
    parser.add_argument(
        "--crc-alert-rate-pct",
        type=float,
        default=5.0,
        help="CRC エラー率のアラート閾値[%%] (default: 5.0)",
    )
    parser.add_argument(
        "--used-alert-ratio-pct",
        type=float,
        default=50.0,
        help="msgUsed=使用済み 比率の下限[%%] (default: 50.0)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="スナップショット出力間隔[秒] (default: 1.0)",
    )
    parser.add_argument(
        "--json-file",
        default=None,
        help="JSON Lines を追記出力するファイルパス（任意）",
    )
    args = parser.parse_args()

    if args.monitor_rtcm <= 0:
        parser.error("--monitor-rtcm は正の秒数で指定してください")
    if args.age_warn_threshold > args.age_alert_threshold:
        parser.error("--age-warn-threshold は --age-alert-threshold 以下にしてください")

    print("=" * 66, file=sys.stderr)
    print("F9P 補正データ連続監視 (UBX-RXM-RTCM)", file=sys.stderr)
    print("=" * 66, file=sys.stderr)
    print(f"  Port                : {args.port}", file=sys.stderr)
    print(f"  F9P target_node_id  : {args.target_node}", file=sys.stderr)
    print(f"  tunnel serial_id    : {args.serial_id}", file=sys.stderr)
    print(f"  監視時間            : {args.monitor_rtcm:g} 秒", file=sys.stderr)
    print(f"  RTK age アラート閾値 : {args.age_alert_threshold:g} 秒", file=sys.stderr)
    print(f"  出力間隔            : {args.interval:g} 秒", file=sys.stderr)
    print("=" * 66, file=sys.stderr)

    def on_alert(alert: dict) -> None:
        print(f"[ALERT][{alert['level']}] {alert['code']}: {alert['message']}",
              file=sys.stderr)

    mon = CorrectionMonitor(
        age_alert_threshold=args.age_alert_threshold,
        age_warn_threshold=args.age_warn_threshold,
        crc_alert_rate_pct=args.crc_alert_rate_pct,
        used_alert_ratio_pct=args.used_alert_ratio_pct,
        on_alert=on_alert,
    )

    print("\n[接続] MAVLink USB 経由で CAN に接続しています…", file=sys.stderr)
    print("        (ドライバが MAV_CMD_CAN_FORWARD を自動送信します)", file=sys.stderr)
    try:
        node = dronecan.make_node(
            f"mavcan:{args.port}",
            node_id=args.local_node,
            bus_number=args.bus_number,
            mavlink_target_system=args.mavlink_target_system,
        )
    except Exception as e:
        sys.exit(f"[エラー] DroneCAN ノードの初期化に失敗: {e}")

    tunnel_msg_count = 0
    rx_byte_count = 0

    def on_tunnel(event) -> None:
        nonlocal tunnel_msg_count, rx_byte_count
        msg = event.message
        if getattr(msg, "target_node", None) != args.target_node:
            return
        if getattr(msg, "serial_id", None) != args.serial_id:
            return

        tunnel_msg_count += 1
        buf = getattr(msg, "buffer", None)
        items = getattr(buf, "items", None) if buf is not None else None
        if not items:
            return

        raw = bytes(items)
        rx_byte_count += len(raw)
        mon.feed_ubx(raw)

    node.add_handler(uavcan.tunnel.Targetted, on_tunnel)

    json_out = None
    if args.json_file:
        Path(args.json_file).parent.mkdir(parents=True, exist_ok=True)
        json_out = open(args.json_file, "a")

    print("\n[受信] UBX-RXM-RTCM を待機しています…", file=sys.stderr)
    print("        (中断する場合は Ctrl+C)", file=sys.stderr)

    start = time.monotonic()
    next_report = start
    try:
        while time.monotonic() - start < args.monitor_rtcm:
            node.spin(timeout=0.05)
            now = time.monotonic()
            if now >= next_report:
                _emit_json(mon, json_out)
                next_report = now + args.interval
    except KeyboardInterrupt:
        print("\n[中断] キーボード割り込みで受信を終了します。", file=sys.stderr)
    finally:
        _emit_json(mon, json_out)
        if json_out is not None:
            json_out.close()
        try:
            node.close()
        except Exception:
            pass

    print("\n" + "=" * 66, file=sys.stderr)
    print("監視結果サマリー", file=sys.stderr)
    print("=" * 66, file=sys.stderr)
    print(f"  監視時間            : {args.monitor_rtcm:g} 秒", file=sys.stderr)
    print(f"  受信 tunnel メッセージ数 : {tunnel_msg_count}", file=sys.stderr)
    print(f"  受信バイト数        : {rx_byte_count}", file=sys.stderr)
    print("=" * 66, file=sys.stderr)
    print(mon.format_summary(), file=sys.stderr)


if __name__ == "__main__":
    main()

