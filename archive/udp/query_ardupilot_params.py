#!/usr/bin/env python3
"""query_ardupilot_params.py — ArduPilot の GPS/CAN 関連パラメータを MAVLink 経由で取得する

ローバー(DroneCAN F9P) の RTK FIXED 未達調査用。
Pixhawk に MAVLink 接続し、GPS / CAN / RTCM 関連パラメータを一覧表示する。

Usage (ラズパイ側):
    python3 query_ardupilot_params.py [--port /dev/ttyAMA0] [--baud 921600]
"""

import argparse
import time

from pymavlink import mavutil

# 表示対象のキーワード（パラメータ名の部分一致）
KEYWORDS = [
    "GPS",
    "CAN_P",
    "CAN_D",
    "RTCM",
    "EK3_SRC1_POSXY",
    "EK3_SRC1_VELXY",
    "AHRS_EKF_TYPE",
]


def main() -> None:
    p = argparse.ArgumentParser(description="ArduPilot GPS/CAN パラメータ取得")
    p.add_argument("--port", default="/dev/ttyAMA0")
    p.add_argument("--baud", type=int, default=921600)
    args = p.parse_args()

    master = mavutil.mavlink_connection(args.port, baud=args.baud, rtscts=True)
    print("[INFO] 接続中: %s @ %d" % (args.port, args.baud))
    master.wait_heartbeat(timeout=10)
    print("[INFO] heartbeat 受信: system=%d component=%d autopilot=%s" % (
        master.target_system, master.target_component,
        mavutil.mavlink.enums['MAV_AUTOPILOT'][getattr(master, 'target_autopilot', 0)].name
        if hasattr(master, 'target_autopilot') else "?"))

    # 全パラメータを要求
    master.mav.param_request_list_send(master.target_system, master.target_component)

    params = {}
    start = time.time()
    print("[INFO] パラメータ受信中...")
    while time.time() - start < 15:
        msg = master.recv_match(type='PARAM_VALUE', blocking=True, timeout=2)
        if msg is None:
            continue
        params[msg.param_id] = msg.param_value
        # 全パラメータ受信完了判定（param_count が既知なら break）
        if msg.param_count > 0 and len(params) >= msg.param_count:
            break

    print("[INFO] 受信パラメータ数: %d" % len(params))

    print("\n" + "=" * 70)
    print("  GPS / CAN / RTCM 関連パラメータ")
    print("=" * 70)
    shown = 0
    for name in sorted(params):
        for kw in KEYWORDS:
            if name.startswith(kw) or name.startswith(kw.replace("_", "")):
                print("  %-28s = %s" % (name, params[name]))
                shown += 1
                break
    if shown == 0:
        print("  (一致なし。全パラメータ数を確認してください)")

    # 特に重要なパラメータを個別に強調表示
    print("\n" + "-" * 70)
    print("  重要パラメータの解釈")
    print("-" * 70)
    gps_type = params.get("GPS_TYPE", params.get("GPS1_TYPE"))
    print("  GPS_TYPE(GPS1_TYPE) = %s  (9=UAVCAN/DroneCAN)" % gps_type)
    gnss = params.get("GPS_GNSS_MODE")
    if gnss is not None:
        gnss = int(gnss)
        bits = {
            0: "GPS", 1: "SBAS", 2: "Galileo", 3: "BeiDou",
            4: "IMES", 5: "QZSS", 6: "GLONASS",
        }
        enabled = [bits[i] for i in bits if (gnss >> i) & 1]
        print("  GPS_GNSS_MODE = %d (0b%s) → 有効: %s" % (
            gnss, bin(gnss), ", ".join(enabled) if enabled else "なし"))
        if (gnss >> 6) & 1:
            print("    ⚠️ GLONASS が有効 (基地局は GLONASS 非配信のため要確認)")
        else:
            print("    ✅ GLONASS は無効")
    print("  GPS_DRV_OPTIONS = %s" % params.get("GPS_DRV_OPTIONS"))
    print("  GPS_AUTO_CONFIG = %s" % params.get("GPS_AUTO_CONFIG"))

    master.close()
    print("\n[done]")


if __name__ == "__main__":
    main()
