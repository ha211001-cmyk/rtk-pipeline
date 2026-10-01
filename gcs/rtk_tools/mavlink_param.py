#!/usr/bin/env python3
"""mavlink_param.py — Pixhawk パラメータの確認・変更ツール (Mission Planner 不要)

使い方:
  # 1. ラズパイ上でシリアル直結で確認
  python3 mavlink_param.py --serial /dev/ttyAMA0 --get FS_GCS_ENABLE

  # 2. ラズパイ上で値を 0 (無効) に設定
  python3 mavlink_param.py --serial /dev/ttyAMA0 --set FS_GCS_ENABLE 0

  # 3. フェイルセーフ関連パラメータを一括チェック
  python3 mavlink_param.py --serial /dev/ttyAMA0 --check-failsafe

  # 4. Mac から UDP 経由で確認 (mavlink_bridge 起動中)
  python3 mavlink_param.py --udp 14550 --check-failsafe
"""

import argparse
import sys
import time
from pymavlink import mavutil

def connect_mavlink(args):
    if args.udp:
        uri = f"udpin:0.0.0.0:{args.udp}"
        print(f"[MAVLink] Connecting via UDP ({uri})...")
        conn = mavutil.mavlink_connection(uri)
    else:
        print(f"[MAVLink] Connecting via Serial ({args.serial} @ {args.baud}bps)...")
        conn = mavutil.mavlink_connection(args.serial, baud=args.baud)

    print("[MAVLink] Waiting for heartbeat...")
    msg = conn.wait_heartbeat(timeout=10)
    if not msg:
        print("[ERROR] Heartbeat timeout. Pixhawk の電源や接続を確認してください。")
        sys.exit(1)
    print(f"[MAVLink] Heartbeat received from System {conn.target_system}, Component {conn.target_component}")
    return conn

def get_param(conn, param_name, timeout=5.0):
    param_bytes = param_name.encode('ascii')
    conn.mav.param_request_read_send(
        conn.target_system,
        conn.target_component,
        param_bytes,
        -1
    )
    start = time.time()
    while time.time() - start < timeout:
        msg = conn.recv_match(type='PARAM_VALUE', blocking=True, timeout=1.0)
        if msg:
            name = msg.param_id
            if name == param_name or name.startswith(param_name):
                return msg.param_value, msg.param_type
    return None, None

def set_param(conn, param_name, param_value, timeout=5.0):
    # まず型を取得
    curr_val, ptype = get_param(conn, param_name, timeout=3.0)
    if ptype is None:
        ptype = mavutil.mavlink.MAV_PARAM_TYPE_REAL32  # デフォルト float

    param_bytes = param_name.encode('ascii')
    conn.mav.param_set_send(
        conn.target_system,
        conn.target_component,
        param_bytes,
        float(param_value),
        ptype
    )
    # 反映確認
    start = time.time()
    while time.time() - start < timeout:
        msg = conn.recv_match(type='PARAM_VALUE', blocking=True, timeout=1.0)
        if msg and (msg.param_id == param_name or msg.param_id.startswith(param_name)):
            if abs(msg.param_value - float(param_value)) < 1e-4:
                return True, msg.param_value
    return False, None

def check_failsafe(conn):
    print("\n" + "=" * 60)
    print(" 🛡️  フェイルセーフ設定確認サマリー")
    print("=" * 60)

    # 1. FS_GCS_ENABLE
    val, _ = get_param(conn, "FS_GCS_ENABLE")
    if val is not None:
        status = "✅ 安全 (Disabled: 通信断でもプロポ操縦維持)" if int(val) == 0 else f"⚠️ 注意! ({int(val)}: 通信断でRTL/着陸発動)"
        print(f"  FS_GCS_ENABLE  = {int(val):<2}  --> {status}")
    else:
        print("  FS_GCS_ENABLE  = 取得失敗")

    # 2. FS_THR_ENABLE
    val, _ = get_param(conn, "FS_THR_ENABLE")
    if val is not None:
        status = "✅ 安全 (Enabled: プロポ電波切れで保護発動)" if int(val) != 0 else "⚠️ 警告! (0: プロポ電波切れ保護が無効)"
        print(f"  FS_THR_ENABLE  = {int(val):<2}  --> {status}")
    else:
        print("  FS_THR_ENABLE  = 取得失敗")

    # 3. BATT_FS_LOW_ACT
    val, _ = get_param(conn, "BATT_FS_LOW_ACT")
    if val is not None:
        act_names = {0: "None", 1: "Land", 2: "RTL", 3: "SmartRTL/RTL"}
        print(f"  BATT_FS_LOW_ACT = {int(val):<2} --> 低電圧時動作: {act_names.get(int(val), str(int(val)))}")

    print("=" * 60 + "\n")

def main():
    p = argparse.ArgumentParser(description="Pixhawk MAVLink Parameter Tool")
    p.add_argument("--serial", default="/dev/ttyAMA0", help="Serial port (default: /dev/ttyAMA0)")
    p.add_argument("--baud", type=int, default=921600, help="Baudrate (default: 921600)")
    p.add_argument("--udp", type=int, default=None, help="UDP port (e.g. 14550) if connecting via network")
    p.add_argument("--get", help="Get parameter value (e.g. --get FS_GCS_ENABLE)")
    p.add_argument("--set", nargs=2, metavar=('PARAM', 'VALUE'), help="Set parameter value (e.g. --set FS_GCS_ENABLE 0)")
    p.add_argument("--check-failsafe", action="store_true", help="Check all failsafe related parameters")
    args = p.parse_args()

    conn = connect_mavlink(args)

    if args.check_failsafe:
        check_failsafe(conn)
    elif args.get:
        val, _ = get_param(conn, args.get)
        if val is not None:
            print(f"[PARAM] {args.get} = {val}")
        else:
            print(f"[ERROR] Parameter {args.get} not found or timeout.")
    elif args.set:
        param, val = args.set
        print(f"[PARAM] Setting {param} -> {val}...")
        ok, new_val = set_param(conn, param, val)
        if ok:
            print(f"✅ [SUCCESS] {param} is now set to {new_val}")
        else:
            print(f"❌ [FAILED] Could not verify {param} setting.")
    else:
        check_failsafe(conn)

if __name__ == "__main__":
    main()
