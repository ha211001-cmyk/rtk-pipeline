#!/usr/bin/env python3
"""
F9P 基地局（Base Station）設定・RTCM信号受信プログラム
【Raspberry Pi 5 対応版】

緯度:36.070846 経度:136.595280 を固定点（既知点）として設定し、
F9P に RTCM3 補正信号を生成させてシリアルから受信・表示します。

処理の流れ:
  1. UBX-CFG-TMODE3 → Fixed Mode（固定点設定）
  2. UBX-CFG-MSG    → RTCM3 メッセージを USB ポートで出力有効化
  3. RTCMReader     → F9P から出力される RTCM3 信号を受信・表示
"""

import sys
import time
import struct
import serial
from serial.tools import list_ports
from pyrtcm import RTCMReader

# ============================================================
# 基地局として使用する固定座標（既知点）
# ============================================================
FIXED_LAT = 36.070846    # 緯度（度, WGS84）
FIXED_LON = 136.595280   # 経度（度, WGS84）
FIXED_ALT = 1237.00      # 高度（m, WGS84楕円体高）

BAUD = 38400
# Raspberry Pi では F9P は通常 /dev/ttyACM0 として認識される
# USB-シリアル変換アダプタ使用時は /dev/ttyUSB0 の場合もある
SERIAL_PORT = "/dev/ttyACM0"

# ============================================================
# 有効化する RTCM3 メッセージ一覧（USB ポートに出力）
# UBX class 0xF5, id = RTCM_MSG_NUM - 1000
# ============================================================
RTCM_MSGS = [
    (0xF5, 0x05, 5, "RTCM 1005 基準局座標 (5秒毎)"),
    (0xF5, 0x4D, 1, "RTCM 1077 GPS MSM7"),
    (0xF5, 0x57, 1, "RTCM 1087 GLONASS MSM7"),
    (0xF5, 0x61, 1, "RTCM 1097 Galileo MSM7"),
    (0xF5, 0x7F, 1, "RTCM 1127 BeiDou MSM7"),
    (0xF5, 0xE6, 5, "RTCM 1230 GLO コードフェーズバイアス (5秒毎)"),
]


# ============================================================
# UBX ユーティリティ
# ============================================================
def ubx_checksum(data: bytes) -> bytes:
    """UBX チェックサム（CLASS, ID, LEN, PAYLOAD に対して計算）"""
    ck_a = ck_b = 0
    for b in data:
        ck_a = (ck_a + b) & 0xFF
        ck_b = (ck_b + ck_a) & 0xFF
    return bytes([ck_a, ck_b])


def make_ubx(cls_id: int, msg_id: int, payload: bytes) -> bytes:
    """UBX パケット組み立て"""
    inner = bytes([cls_id, msg_id]) + struct.pack('<H', len(payload)) + payload
    return bytes([0xB5, 0x62]) + inner + ubx_checksum(inner)


def send_ubx_and_wait_ack(ser: serial.Serial, packet: bytes, label: str, timeout=0.5) -> bool:
    """UBX コマンドを送信し、ACK を待つ"""
    ser.reset_input_buffer()
    ser.write(packet)
    deadline = time.time() + timeout
    buf = b''
    while time.time() < deadline:
        buf += ser.read(ser.in_waiting or 1)
        ack_idx = buf.find(b'\xB5\x62\x05\x01')
        nak_idx = buf.find(b'\xB5\x62\x05\x00')
        if ack_idx != -1 and len(buf) >= ack_idx + 8:
            print(f"  ✓ ACK: {label}")
            return True
        if nak_idx != -1 and len(buf) >= nak_idx + 8:
            print(f"  ✗ NAK: {label}")
            return False
    print(f"  ? タイムアウト（ACK 未受信）: {label}")
    return False


# ============================================================
# STEP1: TMODE3 Fixed Mode 設定
# ============================================================
def set_tmode3_fixed(ser: serial.Serial):
    """
    UBX-CFG-TMODE3 (Class=0x06, ID=0x71)
    Fixed Mode で既知座標を LLH 形式で設定する
    """
    lat_int = round(FIXED_LAT * 1e7)
    lon_int = round(FIXED_LON * 1e7)
    alt_cm  = round(FIXED_ALT * 100)

    lat_hp = round((FIXED_LAT - lat_int * 1e-7) * 1e9)
    lon_hp = round((FIXED_LON - lon_int * 1e-7) * 1e9)
    alt_hp = round((FIXED_ALT * 100 - alt_cm) * 10)

    # UBX-CFG-TMODE3 payload: 40 bytes
    # '<BBHiiibbbBIIIII' = 1+1+2+4+4+4+1+1+1+1+4+4+4+4+4 = 40 bytes
    payload = struct.pack(
        '<BBHiiibbbBIIIII',
        0,        # version
        0,        # reserved1
        0x0102,   # flags: bit[1:0]=2(Fixed Mode), bit8=1(LLH形式)
        lat_int,  # ecefXOrLat  [1e-7 deg]
        lon_int,  # ecefYOrLon  [1e-7 deg]
        alt_cm,   # ecefZOrAlt  [cm]
        lat_hp,   # ecefXOrLatHP [1e-9 deg]
        lon_hp,   # ecefYOrLonHP [1e-9 deg]
        alt_hp,   # ecefZOrAltHP [0.1mm]
        0,        # reserved2
        10000,    # fixedPosAcc [0.1mm] = 1m 精度
        0,        # svinMinDur [s]
        0,        # svinAccLimit [0.1mm]
        0,        # reserved3[0]
        0,        # reserved3[1]
    )
    packet = make_ubx(0x06, 0x71, payload)

    print(f"\n[STEP1] TMODE3 Fixed Mode 設定")
    print(f"  緯度: {FIXED_LAT}° ({lat_int} × 1e-7)")
    print(f"  経度: {FIXED_LON}° ({lon_int} × 1e-7)")
    print(f"  高度: {FIXED_ALT} m ({alt_cm} cm)")
    print(f"  パケット: {packet.hex(' ').upper()}")
    return send_ubx_and_wait_ack(ser, packet, "CFG-TMODE3 Fixed")


# ============================================================
# STEP2: RTCM3 出力メッセージ有効化（USB ポート）
# ============================================================
def enable_rtcm_output(ser: serial.Serial):
    """
    UBX-CFG-MSG (Class=0x06, ID=0x01) 8-byte 形式
    USB ポート（ポートID=3）に RTCM3 メッセージを出力させる
    """
    print("\n[STEP2] RTCM3 出力メッセージ有効化 (USB ポート)")
    all_ok = True
    for cls, id_, rate, desc in RTCM_MSGS:
        payload = bytes([cls, id_, 0, 0, 0, rate, 0, 0])
        packet = make_ubx(0x06, 0x01, payload)
        ok = send_ubx_and_wait_ack(ser, packet, desc, timeout=0.5)
        if not ok:
            all_ok = False
        time.sleep(0.05)
    return all_ok


# ============================================================
# STEP3: RTCM3 信号の受信・表示
# ============================================================
def receive_rtcm(ser: serial.Serial):
    """
    F9P から出力される RTCM3 信号を受信して解析・表示する
    NMEA / UBX と混在するため、RTCM フレーム（0xD3 始まり）のみを抽出
    """
    print("\n[STEP3] RTCM3 信号 受信開始（Ctrl+C で終了）")
    print("-" * 70)

    rtcm_buf = b''
    rtcm_count = 0
    last_summary = time.time()
    msg_stats = {}

    while True:
        chunk = ser.read(ser.in_waiting or 1)
        if not chunk:
            continue

        rtcm_buf += chunk

        while len(rtcm_buf) >= 3:
            idx = rtcm_buf.find(b'\xD3')
            if idx == -1:
                rtcm_buf = b''
                break
            if idx > 0:
                rtcm_buf = rtcm_buf[idx:]

            if len(rtcm_buf) < 3:
                break

            length = ((rtcm_buf[1] & 0x03) << 8) | rtcm_buf[2]
            frame_len = 3 + length + 3

            if len(rtcm_buf) < frame_len:
                break

            frame = rtcm_buf[:frame_len]
            rtcm_buf = rtcm_buf[frame_len:]

            if length >= 2:
                msg_num = (frame[3] << 4) | (frame[4] >> 4)
                rtcm_count += 1
                msg_stats[msg_num] = msg_stats.get(msg_num, 0) + 1
                print(f"[RTCM] #{rtcm_count:5d} | MSG {msg_num:4d} | {length:4d} bytes | 累計: {msg_stats.get(msg_num,0)} 回")

        now = time.time()
        if now - last_summary >= 10.0:
            print("\n--- [10秒サマリ] 受信済み RTCM メッセージ ---")
            for mtype, cnt in sorted(msg_stats.items()):
                print(f"    MSG {mtype}: {cnt} 回")
            print("--------------------------------------------\n")
            last_summary = now


# ============================================================
# メイン
# ============================================================
def main():
    print("=" * 70)
    print("F9P 基地局モード設定 & RTCM3 受信プログラム [Raspberry Pi 5版]")
    print(f"固定座標: 緯度 {FIXED_LAT}°  経度 {FIXED_LON}°  高度(推定) {FIXED_ALT}m")
    print("=" * 70)

    print(f"対象ポート: {SERIAL_PORT}")

    try:
        ser = serial.Serial(SERIAL_PORT, BAUD, timeout=1.0)
        print(f"\n✓ F9P 接続: {SERIAL_PORT} ({BAUD} baud)")
    except Exception as e:
        print(f"✗ ポートオープン失敗: {e}")
        print("ヒント: ls /dev/ttyACM* または ls /dev/ttyUSB* でポートを確認してください")
        print("       sudo usermod -aG dialout $USER でシリアルポート権限を付与できます")
        sys.exit(1)

    try:
        ok1 = set_tmode3_fixed(ser)
        time.sleep(0.5)

        ok2 = enable_rtcm_output(ser)
        time.sleep(1.0)

        if not ok1:
            print("\n⚠ TMODE3 設定の ACK が取れませんでした。")
            print("  → F9P が TMODE3 に非対応か、ポート設定を確認してください。")
            print("  → それでも RTCM 受信を試みます...\n")

        if not ok2:
            print("\n⚠ RTCM 出力有効化の一部で問題が発生しました。")
            print("  → 受信を試みます...\n")

        receive_rtcm(ser)

    except KeyboardInterrupt:
        print("\n\n✓ 終了（Ctrl+C）")
    except Exception as e:
        print(f"\n✗ エラー: {e}")
    finally:
        ser.close()
        print("✓ ポートクローズ")


if __name__ == "__main__":
    main()
