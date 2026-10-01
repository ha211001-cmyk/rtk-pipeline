#!/usr/bin/env python3
"""NMEA GGA文からジオイド分離量を取得して楕円体高を計算"""
import serial
import time
from pynmeagps import NMEAReader

COM_PORT = "COM7"
BAUD = 38400

print("=" * 60)
print("NMEA GGA Geoidal Separation Check")
print("=" * 60)

ser = serial.Serial(COM_PORT, BAUD, timeout=1.0)
print(f"[OK] Connected to {COM_PORT}")

nmr = NMEAReader(ser)
print("Listening for GGA messages (30 seconds)...\n")

deadline = time.time() + 30
found = False

while time.time() < deadline:
    try:
        raw, parsed = nmr.read()
        if raw is None:
            continue
        
        if hasattr(parsed, 'msgID') and parsed.msgID == "GGA":
            found = True
            print(f"[GGA] Raw: {raw.decode('ascii', errors='ignore').strip()}")
            print(f"  Latitude:   {parsed.lat:.7f} {parsed.NS}")
            print(f"  Longitude:  {parsed.lon:.7f} {parsed.EW}")
            print(f"  Altitude (MSL):     {parsed.alt:.3f} m")
            print(f"  Geoid Sep:          {parsed.sep:.3f} m")
            ellipsoid_alt = parsed.alt + parsed.sep
            print(f"  Ellipsoid Alt:      {ellipsoid_alt:.3f} m")
            print(f"  Quality:    {parsed.quality}")
            print(f"  Satellites: {parsed.numSV}")
            print()
            break
    except Exception:
        continue

if not found:
    print("[WARN] GGA not received within 30 seconds")

ser.close()
print("[OK] Port closed")