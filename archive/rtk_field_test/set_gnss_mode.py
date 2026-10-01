#!/usr/bin/env python3
"""
set_gnss_mode.py — ArduPilot の GNSS_MODE（GPS1_GNSS_MODE）を変更し、ローバー側 GLONASS を ON/OFF する

ローバー（DroneCAN F9P）の GLONASS を無効化するためのスクリプト。
ArduPilot の GNSS_MODE（ビットマスク）の GLONASS ビット(bit6)だけを落として
書き戻す（他の星座設定は維持）。

GNSS_MODE のビット:
    bit0: GPS, bit1: SBAS, bit2: Galileo, bit3: BeiDou,
    bit4: IMES, bit5: QZSS, bit6: GLONASS

使い方:
    python3 set_gnss_mode.py --no-glonass               # GLONASS を無効化
    python3 set_gnss_mode.py --restore 219              # 指定値へ復元
    python3 set_gnss_mode.py --no-glonass --port /dev/ttyAMA0 --baud 921600

注意:
    GPS_GNSS_MODE は Pixhawk に永続保存される。実験後に必ず元値へ復元すること。
    変更を反映するには Pixhawk / GPS の再起動が必要（GPS_AUTO_CONFIG=1 前提）。
"""

import argparse
import time

from pymavlink import mavutil

GLONASS_BIT = 6
BITS = {0: "GPS", 1: "SBAS", 2: "Galileo", 3: "BeiDou",
        4: "IMES", 5: "QZSS", 6: "GLONASS"}
# GPS1_GNSS_MODE=0（受信機デフォルト）のときに GLONASS を除いて設定する明示値
ALL_EXCEPT_GLONASS = 63  # GPS+SBAS+Galileo+BeiDou+IMES+QZSS（GLONASSなし）


def format_gnss_mode(value: int) -> str:
    enabled = [name for bit, name in BITS.items() if (value >> bit) & 1]
    return "%d (0b%s) → %s" % (value, bin(value), ", ".join(enabled) if enabled else "なし")


def read_param(master, name: str):
    """PARAM_VALUE を1件読み取って返す（見つからなければ None）。"""
    deadline = time.time() + 4.0
    while time.time() < deadline:
        msg = master.recv_match(type='PARAM_VALUE', blocking=True, timeout=1)
        if msg and msg.param_id == name:
            return msg.param_value
    return None


def find_param(master):
    """GNSS_MODE パラメータ名（GPS1_GNSS_MODE 優先）と現在値を返す。"""
    for name in ("GPS1_GNSS_MODE", "GPS_GNSS_MODE"):
        master.mav.param_request_read_send(master.target_system, master.target_component,
                                           name.encode(), -1)
        val = read_param(master, name)
        if val is not None:
            return name, val
    return None, None


def main() -> None:
    p = argparse.ArgumentParser(description="GPS_GNSS_MODE を変更（GLONASS 無効化など）")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--no-glonass", action="store_true", help="GLONASS を無効化する")
    g.add_argument("--restore", type=int, help="指定値へ復元する")
    p.add_argument("--port", default="/dev/ttyAMA0", help="Pixhawk の MAVLink ポート")
    p.add_argument("--baud", type=int, default=921600, help="MAVLink ボーレート")
    p.add_argument("--no-rtscts", action="store_true", help="RTS/CTS を無効化")
    args = p.parse_args()

    master = mavutil.mavlink_connection(args.port, baud=args.baud, rtscts=not args.no_rtscts)
    print("[INFO] 接続中: %s @ %d" % (args.port, args.baud))
    master.wait_heartbeat(timeout=10)
    print("[INFO] heartbeat 受信: system=%d component=%d"
          % (master.target_system, master.target_component))

    # 現在値を読む（GPS1_GNSS_MODE → GPS_GNSS_MODE の順で探す）
    name, cur = find_param(master)
    if cur is None:
        print("[ERROR] GNSS_MODE パラメータを読み取れませんでした")
        master.close()
        return
    current = int(cur)
    print("[INFO] 現在の %s = %s" % (name, format_gnss_mode(current)))

    if args.no_glonass:
        if current == 0:
            # 0 = 受信機デフォルト（全星座）。GLONASS を除く明示ビットマスクを設定
            new_val = ALL_EXCEPT_GLONASS
            print("[INFO] 現在値=0（受信機デフォルト）。GLONASS を除く %d を設定します" % new_val)
        else:
            new_val = current & ~(1 << GLONASS_BIT)
            if new_val == current:
                print("[INFO] GLONASS はすでに無効です（変更なし）")
                master.close()
                return
        print("[INFO] 新しい %s = %s" % (name, format_gnss_mode(new_val)))
    else:
        new_val = args.restore
        print("[INFO] 復元する %s = %s" % (name, format_gnss_mode(new_val)))

    master.mav.param_set_send(master.target_system, master.target_component,
                              name.encode(), float(new_val),
                              mavutil.mavlink.MAV_PARAM_TYPE_INT32)
    time.sleep(0.5)

    # 書き込み確認
    master.mav.param_request_read_send(master.target_system, master.target_component,
                                       name.encode(), -1)
    confirmed = read_param(master, name)
    if confirmed is not None:
        print("[OK] 書き込み後の %s = %s" % (name, format_gnss_mode(int(confirmed))))
    else:
        print("[WARN] 書き込み後の値を確認できませんでした")

    if args.no_glonass:
        print("\n[重要] 変更を反映するには Pixhawk / GPS の再起動が必要です")
        print("       復元方法: python3 set_gnss_mode.py --restore %d" % current)
    master.close()
    print("[done]")


if __name__ == "__main__":
    main()
