
#!/usr/bin/env python3
"""
rtk-pipeline GPS Display Program - Final Version
Displays GPS data from u-blox F9P on COM6 in NMEA format
"""

import serial
import struct
import sys
import time
from datetime import datetime

# ====== 設定 ======
COM_PORT = 'COM7'      # シリアルポート名
BAUD = 38400           # ボーレート
# 表示するNMEAメッセージ種別（Trueで表示、Falseで非表示）
SHOW_GGA = True
SHOW_RMC = True
SHOW_GSA = True
SHOW_VTG = True
SHOW_GSV = True
SHOW_GLL = True



try:
    from pynmeagps import NMEAReader
except ImportError:
    print("Error: pynmeagps library not found")
    print("  pip install pynmeagps")
    sys.exit(1)


def ubx_checksum(data):
    """UBXチェックサム計算"""
    ck_a = ck_b = 0
    for b in data:
        ck_a = (ck_a + b) & 0xFF
        ck_b = (ck_b + ck_a) & 0xFF
    return bytes([ck_a, ck_b])


def make_ubx(cls, msg_id, payload):
    """UBXパケット生成"""
    inner = bytes([cls, msg_id]) + struct.pack('<H', len(payload)) + payload
    return bytes([0xB5, 0x62]) + inner + ubx_checksum(inner)


def reset_tmode3(ser):
    """TMODE3をDisabledにリセット（基地局モード解除）"""
    payload = struct.pack('<BBHiiibbbBIIIII', 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    pkt = make_ubx(0x06, 0x71, payload)
    ser.reset_input_buffer()
    ser.write(pkt)
    time.sleep(0.5)
    buf = ser.read(ser.in_waiting)
    if b'\xB5\x62\x05\x01' in buf:
        print("[OK] TMODE3 reset to Disabled (Rover mode)")
    else:
        print("[WARN] TMODE3 reset ACK not found, continuing anyway")


def display_gga(msg, count):
    """Display GGA (Global Positioning System Fix Data)"""
    print(f"\n[{count}] NMEA-GGA (Global Positioning System Fix Data)")
    print(f"  Time:      {msg.time if hasattr(msg, 'time') else 'N/A'}")
    print(f"  Latitude:  {msg.lat:.8f}°" if hasattr(msg, 'lat') and msg.lat else "  Latitude:  N/A")
    print(f"  Longitude: {msg.lon:.8f}°" if hasattr(msg, 'lon') and msg.lon else "  Longitude: N/A")
    print(f"  Altitude:  {msg.alt if hasattr(msg, 'alt') else 'N/A'} m")
    
    quality = msg.quality if hasattr(msg, 'quality') else 0
    quality_map = {0: 'No Fix', 1: 'GPS Fix', 2: 'DGPS Fix', 4: 'RTK Fixed', 5: 'RTK Float'}
    quality_str = quality_map.get(quality, f'Unknown ({quality})')
    print(f"  Fix Type:  {quality_str}")
    print(f"  Satellites: {msg.numSV if hasattr(msg, 'numSV') else 'N/A'}")
    print(f"  HDOP:      {msg.HDOP if hasattr(msg, 'HDOP') else 'N/A'}")


def display_rmc(msg, count):
    """Display RMC (Recommended Minimum Navigation Information)"""
    print(f"\n[{count}] NMEA-RMC (Recommended Minimum Navigation Info)")
    print(f"  Time:   {msg.time if hasattr(msg, 'time') else 'N/A'}")
    print(f"  Date:   {msg.date if hasattr(msg, 'date') else 'N/A'}")
    print(f"  Lat:    {msg.lat:.8f}°" if hasattr(msg, 'lat') and msg.lat else "  Lat:    N/A")
    print(f"  Lon:    {msg.lon:.8f}°" if hasattr(msg, 'lon') and msg.lon else "  Lon:    N/A")
    print(f"  Speed:  {msg.spd if hasattr(msg, 'spd') else 'N/A'} knots")
    print(f"  Track:  {msg.cog if hasattr(msg, 'cog') else 'N/A'}°")
    
    status = msg.status if hasattr(msg, 'status') else 'V'
    print(f"  Status: {'Valid' if status == 'A' else 'Invalid'}")


def display_gsa(msg, count):
    """Display GSA (GPS DOP and Active Satellites)"""
    print(f"\n[{count}] NMEA-GSA (GPS DOP and Active Satellites)")
    nav_mode = msg.navMode if hasattr(msg, 'navMode') else 1
    fix_map = {1: 'No Fix', 2: '2D Fix', 3: '3D Fix'}
    print(f"  Fix Type: {fix_map.get(nav_mode, f'Unknown ({nav_mode})')}")
    print(f"  PDOP:     {msg.PDOP if hasattr(msg, 'PDOP') else 'N/A'}")
    print(f"  HDOP:     {msg.HDOP if hasattr(msg, 'HDOP') else 'N/A'}")
    print(f"  VDOP:     {msg.VDOP if hasattr(msg, 'VDOP') else 'N/A'}")


def display_vtg(msg, count):
    """Display VTG (Track Made Good and Ground Speed)"""
    print(f"\n[{count}] NMEA-VTG (Track Made Good and Ground Speed)")
    print(f"  Track (True):  {msg.cogt if hasattr(msg, 'cogt') and msg.cogt else 'N/A'}°")
    print(f"  Track (Mag):   {msg.cogm if hasattr(msg, 'cogm') and msg.cogm else 'N/A'}°")
    print(f"  Speed (knots): {msg.sogn if hasattr(msg, 'sogn') else 'N/A'}")
    print(f"  Speed (km/h):  {msg.sogk if hasattr(msg, 'sogk') else 'N/A'}")


def display_gsv(msg, count):
    """Display GSV (GPS Satellites in View)"""
    print(f"\n[{count}] NMEA-GSV (GPS Satellites in View)")


def display_gll(msg, count):
    """Display GLL (Geographic Position - Latitude/Longitude)"""
    print(f"\n[{count}] NMEA-GLL (Geographic Position)")
    print(f"  Time:      {msg.time if hasattr(msg, 'time') else 'N/A'}")
    print(f"  Lat:       {msg.lat:.8f}°" if hasattr(msg, 'lat') and msg.lat else "  Lat:       N/A")
    print(f"  Lon:       {msg.lon:.8f}°" if hasattr(msg, 'lon') and msg.lon else "  Lon:       N/A")
    print(f"  Status:    {'Valid' if (hasattr(msg, 'status') and msg.status == 'A') else 'Invalid'}")


def main():

    port = COM_PORT
    baudrate = BAUD
    if len(sys.argv) > 1:
        port = sys.argv[1]
    if len(sys.argv) > 2:
        try:
            baudrate = int(sys.argv[2])
        except ValueError:
            pass
    print("=" * 70)
    print("rtk-pipeline GPS Data Display Program (NMEA Format)")
    print("=" * 70)
    print(f"Port: {port}, Baudrate: {baudrate}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    try:
        ser = serial.Serial(port=port, baudrate=baudrate, timeout=1.0)
        print(f"[OK] Connected to {port}")
        print("[INFO] Resetting TMODE3 to Disabled (ensuring Rover mode)...")
        reset_tmode3(ser)
        print()
        print("-" * 70)
        nmea_reader = NMEAReader(ser)
        msg_count = 0
        last_position = None
        print("Listening for GPS messages (Ctrl+C to stop)...\n")
        while True:
            try:
                (raw_data, msg) = nmea_reader.read()
                if msg is not None:
                    msg_count += 1
                    msg_id = msg.msgID if hasattr(msg, 'msgID') else None
                    if msg_id == 'GGA' and SHOW_GGA:
                        display_gga(msg, msg_count)
                        if hasattr(msg, 'lat') and hasattr(msg, 'lon') and msg.lat and msg.lon:
                            last_position = (msg.lat, msg.lon, msg.alt if hasattr(msg, 'alt') else None)
                    elif msg_id == 'RMC' and SHOW_RMC:
                        display_rmc(msg, msg_count)
                        if hasattr(msg, 'lat') and hasattr(msg, 'lon') and msg.lat and msg.lon:
                            last_position = (msg.lat, msg.lon, None)
                    elif msg_id == 'GSA' and SHOW_GSA:
                        display_gsa(msg, msg_count)
                    elif msg_id == 'VTG' and SHOW_VTG:
                        display_vtg(msg, msg_count)
                    elif msg_id == 'GSV' and SHOW_GSV:
                        display_gsv(msg, msg_count)
                    elif msg_id == 'GLL' and SHOW_GLL:
                        display_gll(msg, msg_count)
            except StopIteration:
                continue
            except Exception as e:
                continue
    except serial.SerialException as e:
        print(f"[ERR] Cannot open {port}: {e}")
        return 1
    except KeyboardInterrupt:
        print("\n" + "=" * 70)
        print("Stopped by user")
        if last_position:
            print("\nLast Position:")
            print(f"  Latitude:  {last_position[0]:.8f}°")
            print(f"  Longitude: {last_position[1]:.8f}°")
            if last_position[2]:
                print(f"  Altitude:  {last_position[2]} m")
        print(f"  Total messages received: {msg_count}")
        print(f"  Stopped: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        return 0
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()
            print("[OK] Port closed")


if __name__ == '__main__':
    sys.exit(main())
