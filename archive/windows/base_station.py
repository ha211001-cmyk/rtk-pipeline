#!/usr/bin/env python3
"""
F9P 基地局（Base Station）設定・RTCM信号受信プログラム
pyubx2のCFG-VALSET方式でFlash永続化に対応

使用方法:
  python base_station.py [秒数]
  例: python base_station.py 30   -> 30秒で自動終了
      python base_station.py      -> Ctrl+Cまで実行
"""

import sys
import time
import serial
import argparse
from pyubx2 import UBXMessage, SET
from pyrtcm import RTCMReader

# ============================================================
# 基地局として使用する固定座標（既知点）
# RTK Fixed測位結果から取得した座標
# ============================================================
# イチミルRTK測位で取得した座標（RTK Float, 精度10~20cm）
# NMEA GGA文の高度はMSL（標高）なので、ジオイド高を足して楕円体高に変換
# 楕円体高 = MSL高度(10.500) + ジオイド高(34.300) = 44.800m
FIXED_LAT = 36.0751418   # 緯度（度, WGS84）
FIXED_LON = 136.2133477  # 経度（度, WGS84）
FIXED_ALT = 44.800       # 高度（m, WGS84楕円体高 = MSL + Geoid Sep）

BAUD = 38400
COM_PORT = "COM7"

# Flash保存フラグ (True=RAM+FLASH同時書き込み, False=RAMのみ)
SAVE_TO_FLASH = True


# ============================================================
# UBX ユーティリティ
# ============================================================
def send_ubx_and_wait_ack(ser: serial.Serial, packet: bytes, label: str, timeout=1.0) -> bool:
    """UBXパケットを送信してACK/NAKを待つ"""
    ser.reset_input_buffer()
    ser.write(packet)
    deadline = time.time() + timeout
    buf = b''
    while time.time() < deadline:
        buf += ser.read(ser.in_waiting or 1)
        ack_idx = buf.find(b'\xB5\x62\x05\x01')
        nak_idx = buf.find(b'\xB5\x62\x05\x00')
        if ack_idx != -1 and len(buf) >= ack_idx + 8:
            print(f"  [ACK] {label}")
            return True
        if nak_idx != -1 and len(buf) >= nak_idx + 8:
            print(f"  [NAK] {label}")
            return False
    print(f"  [TIMEOUT] ACK未受信: {label}")
    return False


def send_cfg_set(ser: serial.Serial, cfg_data: list, label: str, layers: int = 0x05):
    """CFG-VALSET方式で設定を送信（layers=0x05でRAM+FLASH同時書き込み）"""
    msg = UBXMessage.config_set(
        layers=layers,
        transaction=0,
        cfgData=cfg_data
    )
    packet = msg.serialize()
    ok = send_ubx_and_wait_ack(ser, packet, label, timeout=2.0)
    return ok


# ============================================================
# STEP1: TMODE3 Fixed Mode 設定 (CFG-VALSET方式)
# ============================================================
def set_tmode3_fixed(ser: serial.Serial):
    """pyubx2のCFG-VALSET方式でTMODE3 Fixed Modeを設定"""
    # u-blox内部形式への変換
    # 緯度・経度: 1e-7度（×10000000）
    # 高度: mm単位（×1000）
    lat_val = int(FIXED_LAT * 10000000)
    lon_val = int(FIXED_LON * 10000000)
    height_val = int(FIXED_ALT * 1000)

    # layers: 0x01=RAM, 0x04=FLASH, 0x05=RAM+FLASH
    layers = 0x05 if SAVE_TO_FLASH else 0x01

    print(f"\n[STEP1] TMODE3 Fixed Mode 設定 (CFG-VALSET方式)")
    print(f"  緯度: {FIXED_LAT} deg ({lat_val} x 1e-7)")
    print(f"  経度: {FIXED_LON} deg ({lon_val} x 1e-7)")
    print(f"  高度: {FIXED_ALT} m ({height_val} mm)")
    print(f"  保存先: {'RAM + FLASH' if layers == 0x05 else 'RAM only'}")

    # 1. まずTMODE3をDisabledにリセット
    print("  TMODE3 を Disabled にリセット...")
    send_cfg_set(ser, [("CFG_TMODE_MODE", 0)], "TMODE3 Disabled (リセット)", layers=layers)
    time.sleep(1.0)

    # 2. タイムモードをFixed(2)に設定
    ok1 = send_cfg_set(ser, [("CFG_TMODE_MODE", 2)], "CFG_TMODE_MODE=2 (Fixed)", layers=layers)
    time.sleep(0.1)

    # 3. LLH→ECEF変換（Python側で正確に計算してF9P内部の変換を回避）
    import math
    lat_rad = math.radians(FIXED_LAT)
    lon_rad = math.radians(FIXED_LON)
    a = 6378137.0
    f = 1 / 298.257223563
    e2 = f * (2 - f)
    N = a / math.sqrt(1 - e2 * math.sin(lat_rad) ** 2)
    ecef_x = int((N + FIXED_ALT) * math.cos(lat_rad) * math.cos(lon_rad) * 100)  # cm単位
    ecef_y = int((N + FIXED_ALT) * math.cos(lat_rad) * math.sin(lon_rad) * 100)  # cm単位
    ecef_z = int((N * (1 - e2) + FIXED_ALT) * math.sin(lat_rad) * 100)            # cm単位

    print(f"  ECEF X: {ecef_x/100:.4f} m ({ecef_x} cm)")
    print(f"  ECEF Y: {ecef_y/100:.4f} m ({ecef_y} cm)")
    print(f"  ECEF Z: {ecef_z/100:.4f} m ({ecef_z} cm)")

    # 4. 座標系をECEF(0)に指定（LLH変換を回避）
    ok2 = send_cfg_set(ser, [("CFG_TMODE_POS_TYPE", 0)], "CFG_TMODE_POS_TYPE=0 (ECEF)", layers=layers)
    time.sleep(0.1)

    # 5. ECEF座標を直接設定
    ok3 = send_cfg_set(ser, [
        ("CFG_TMODE_ECEF_X", ecef_x),
        ("CFG_TMODE_ECEF_Y", ecef_y),
        ("CFG_TMODE_ECEF_Z", ecef_z),
        ("CFG_TMODE_FIXED_POS_ACC", 100),  # 100 = 10mm = 1cm
    ], "TMODE3 ECEF座標設定 (X/Y/Z/Acc)", layers=layers)
    time.sleep(0.5)

    print("  TMODE3 安定待ち (3秒)...")
    time.sleep(3.0)
    try:
        ser.reset_input_buffer()
    except serial.SerialException:
        pass

    return ok1 and ok2 and ok3


# ============================================================
# STEP2: RTCM3 出力メッセージ有効化 (CFG-VALSET方式)
# ============================================================
def enable_rtcm_output(ser: serial.Serial):
    """CFG-VALSET方式でRTCM出力を有効化（UART1 + USB）"""
    print("\n[STEP2] RTCM3 出力メッセージ有効化 (CFG-VALSET方式)")

    layers = 0x05 if SAVE_TO_FLASH else 0x01

    # RTCMメッセージのCFGキー名（UART1とUSB両方）
    rtcm_cfgs = [
        # (CFG_KEY, rate, description)
        ("CFG_MSGOUT_RTCM_3X_TYPE1005", 5, "RTCM 1005 基準局座標 (5秒毎)"),
        ("CFG_MSGOUT_RTCM_3X_TYPE1077", 1, "RTCM 1077 GPS MSM7"),
        ("CFG_MSGOUT_RTCM_3X_TYPE1087", 1, "RTCM 1087 GLONASS MSM7"),
        ("CFG_MSGOUT_RTCM_3X_TYPE1097", 1, "RTCM 1097 Galileo MSM7"),
        ("CFG_MSGOUT_RTCM_3X_TYPE1127", 1, "RTCM 1127 BeiDou MSM7"),
        ("CFG_MSGOUT_RTCM_3X_TYPE1230", 5, "RTCM 1230 GLOバイアス (5秒毎)"),
    ]

    all_ok = True
    for cfg_key, rate, desc in rtcm_cfgs:
        # UART1用
        cfg_data_uart1 = [(f"{cfg_key}_UART1", rate)]
        ok1 = send_cfg_set(ser, cfg_data_uart1, f"{desc} (UART1)", layers=layers)
        time.sleep(0.05)

        # USB用
        cfg_data_usb = [(f"{cfg_key}_USB", rate)]
        ok2 = send_cfg_set(ser, cfg_data_usb, f"{desc} (USB)", layers=layers)
        time.sleep(0.05)

        if not ok1 or not ok2:
            all_ok = False

    return all_ok


# ============================================================
# STEP3: RTCM3 信号の受信・表示
# ============================================================
def receive_rtcm(ser: serial.Serial, duration: float = 0):
    """F9P から出力される RTCM3 信号を受信して解析・表示"""
    print("\n[STEP3] RTCM3 信号 受信開始")
    if duration > 0:
        print(f"  -> {duration}秒後に自動終了します")
    print("-" * 70)

    rtcm_count = 0
    start_time = time.time()
    last_summary = start_time
    msg_stats = {}

    rtr = RTCMReader(ser)

    while True:
        if duration > 0 and (time.time() - start_time) >= duration:
            print(f"\n[TIMER] 指定時間 ({duration}秒) 経過 -> 自動終了")
            break

        try:
            raw_data, parsed_data = rtr.read()
            if raw_data is None:
                continue

            msg_num = parsed_data.identity
            rtcm_count += 1
            msg_stats[msg_num] = msg_stats.get(msg_num, 0) + 1
            payload_len = len(raw_data) - 6
            print(f"[RTCM] #{rtcm_count:5d} | {msg_num:8s} | {payload_len:4d} bytes | 累計: {msg_stats.get(msg_num,0)} 回")

        except Exception:
            continue

        now = time.time()
        if now - last_summary >= 10.0:
            print("\n--- [10秒サマリ] 受信済み RTCM メッセージ ---")
            for mtype, cnt in sorted(msg_stats.items()):
                print(f"    {mtype}: {cnt} 回")
            print("--------------------------------------------\n")
            last_summary = now

    elapsed = time.time() - start_time
    print(f"\n=== 最終サマリ ({elapsed:.1f}秒間) ===")
    print(f"  総受信フレーム数: {rtcm_count}")
    for mtype, cnt in sorted(msg_stats.items()):
        print(f"  {mtype}: {cnt} 回")


# ============================================================
# メイン
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="F9P 基地局モード設定 & RTCM3 受信プログラム (CFG-VALSET方式)")
    parser.add_argument("duration", type=float, nargs="?", default=0,
                        help="実行秒数（指定しない場合はCtrl+Cまで実行）")
    args = parser.parse_args()

    print("=" * 70)
    print("F9P 基地局モード設定 & RTCM3 受信プログラム (CFG-VALSET方式)")
    print(f"固定座標: 緯度 {FIXED_LAT} deg  経度 {FIXED_LON} deg  高度 {FIXED_ALT}m")
    print(f"Flash保存: {'有効' if SAVE_TO_FLASH else '無効'}")
    if args.duration > 0:
        print(f"実行時間: {args.duration}秒")
    print("=" * 70)

    print(f"対象ポート: {COM_PORT}")

    try:
        ser = serial.Serial(COM_PORT, BAUD, timeout=1.0)
        print(f"\n[OK] F9P 接続: {COM_PORT} ({BAUD} baud)")
    except Exception as e:
        print(f"[ERR] ポートオープン失敗: {e}")
        sys.exit(1)

    try:
        ok1 = set_tmode3_fixed(ser)
        time.sleep(0.5)
        ok2 = enable_rtcm_output(ser)
        time.sleep(1.0)

        if not ok1:
            print("\n[WARN] TMODE3 設定の ACK が取れませんでした。")
        if not ok2:
            print("\n[WARN] RTCM 出力有効化の一部で問題が発生しました。")

        if SAVE_TO_FLASH:
            print("\n[INFO] 設定はRAM + FLASHに同時書き込みされました（電源OFF後も保持）")

        receive_rtcm(ser, duration=args.duration)

    except KeyboardInterrupt:
        print("\n\n[OK] 終了（Ctrl+C）")
    except Exception as e:
        print(f"\n[ERR] エラー: {e}")
    finally:
        ser.close()
        print("[OK] ポートクローズ")


if __name__ == "__main__":
    main()