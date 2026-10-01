#!/usr/bin/env python3
"""
Simple GPS Data Display for EVK-F9P using NMEA format
Simplified version with better debugging
"""

import serial
import sys
from datetime import datetime

try:
    from pynmeagps import NMEAReader
except ImportError:
    print("Error: pynmeagps library not found")
    print("  pip install pynmeagps")
    sys.exit(1)


def main():
    port = 'COM6'
    baudrate = 38400
    
    if len(sys.argv) > 1:
        port = sys.argv[1]
    if len(sys.argv) > 2:
        try:
            baudrate = int(sys.argv[2])
        except ValueError:
            pass
    
    print("=" * 70)
    print("EVK-F9P GPS Data Display (NMEA Format)")
    print("=" * 70)
    print(f"Port: {port}, Baudrate: {baudrate}\n")
    
    try:
        ser = serial.Serial(port=port, baudrate=baudrate, timeout=1.0)
        print(f"✓ Connected to {port}\n")
        print("-" * 70)
        
        nmea_reader = NMEAReader(ser)
        msg_count = 0
        last_gga = None
        last_rmc = None
        
        print("Listening for GPS messages...\n")
        
        while True:
            try:
                (raw_data, msg) = nmea_reader.read()
                
                if msg is not None:
                    msg_count += 1
                    msg_id = msg.msgID if hasattr(msg, 'msgID') else None
                    
                    if msg_id is None:
                        continue
                    
                    # GGA - Fix Data
                    if msg_id == 'GGA':
                        print(f"\n[{msg_count}] NMEA-GGA (Fix Data)")
                        print(f"  Time:      {msg.time if hasattr(msg, 'time') else 'N/A'}")
                        print(f"  Latitude:  {msg.lat if hasattr(msg, 'lat') else 'N/A'}")
                        print(f"  Longitude: {msg.lon if hasattr(msg, 'lon') else 'N/A'}")
                        print(f"  Altitude:  {msg.alt if hasattr(msg, 'alt') else 'N/A'} m")
                        
                        quality = msg.quality if hasattr(msg, 'quality') else 0
                        quality_map = {
                            0: 'No Fix',
                            1: 'GPS Fix',
                            2: 'DGPS Fix',
                            4: 'RTK Fixed',
                            5: 'RTK Float'
                        }
                        quality_str = quality_map.get(quality, f'Unknown ({quality})')
                        print(f"  Fix Type:  {quality_str}")
                        print(f"  Satellites: {msg.numSV if hasattr(msg, 'numSV') else 'N/A'}")
                        print(f"  HDOP:      {msg.HDOP if hasattr(msg, 'HDOP') else 'N/A'}")
                        
                        last_gga = {
                            'lat': msg.lat if hasattr(msg, 'lat') else None,
                            'lon': msg.lon if hasattr(msg, 'lon') else None,
                            'alt': msg.alt if hasattr(msg, 'alt') else None,
                        }
                    
                    # RMC - Recommended Minimum Data
                    elif msg_id == 'RMC':
                        print(f"\n[{msg_count}] NMEA-RMC (Recommended Minimum Data)")
                        print(f"  Time:   {msg.time if hasattr(msg, 'time') else 'N/A'}")
                        print(f"  Date:   {msg.date if hasattr(msg, 'date') else 'N/A'}")
                        print(f"  Lat:    {msg.lat if hasattr(msg, 'lat') else 'N/A'}")
                        print(f"  Lon:    {msg.lon if hasattr(msg, 'lon') else 'N/A'}")
                        print(f"  Speed:  {msg.spd if hasattr(msg, 'spd') else 'N/A'} knots")
                        print(f"  Track:  {msg.cog if hasattr(msg, 'cog') else 'N/A'}°")
                        
                        status = msg.status if hasattr(msg, 'status') else 'V'
                        print(f"  Status: {'Valid' if status == 'A' else 'Invalid'}")
                        
                        last_rmc = {
                            'lat': msg.lat if hasattr(msg, 'lat') else None,
                            'lon': msg.lon if hasattr(msg, 'lon') else None,
                        }
                    
                    # GSA - DOP and Active Satellites
                    elif msg_id == 'GSA':
                        print(f"\n[{msg_count}] NMEA-GSA (DOP and Active Satellites)")
                        nav_mode = msg.navMode if hasattr(msg, 'navMode') else 1
                        fix_map = {1: 'No Fix', 2: '2D Fix', 3: '3D Fix'}
                        print(f"  Fix Type: {fix_map.get(nav_mode, f'Unknown ({nav_mode})')}")
                        print(f"  PDOP:     {msg.PDOP if hasattr(msg, 'PDOP') else 'N/A'}")
                        print(f"  HDOP:     {msg.HDOP if hasattr(msg, 'HDOP') else 'N/A'}")
                        print(f"  VDOP:     {msg.VDOP if hasattr(msg, 'VDOP') else 'N/A'}")
                    
                    # VTG - Speed and Track
                    elif msg_id == 'VTG':
                        print(f"\n[{msg_count}] NMEA-VTG (Speed and Track)")
                        print(f"  Track (T):     {msg.cogt if hasattr(msg, 'cogt') else 'N/A'}°")
                        print(f"  Track (M):     {msg.cogm if hasattr(msg, 'cogm') else 'N/A'}°")
                        print(f"  Speed (knots): {msg.sogn if hasattr(msg, 'sogn') else 'N/A'}")
                        print(f"  Speed (km/h):  {msg.sogk if hasattr(msg, 'sogk') else 'N/A'}")
                    
                    # GSV - Satellites in View
                    elif msg_id == 'GSV':
                        # Only show on first message of each GSV group
                        print(f"\n[{msg_count}] NMEA-GSV (Satellites in View)")
                    
                    else:
                        print(f"\n[{msg_count}] NMEA-{msg_id}")
                        print(f"  Raw: {raw_data[:80]}")
            
            except StopIteration:
                continue
            except Exception as e:
                print(f"[Debug] Error: {str(e)}")
                continue
    
    except serial.SerialException as e:
        print(f"✗ Cannot open {port}: {e}")
        return 1
    
    except KeyboardInterrupt:
        print("\n\nStopped by user")
        
        if last_gga:
            print("\nLast GGA Position:")
            print(f"  Lat: {last_gga['lat']}")
            print(f"  Lon: {last_gga['lon']}")
            print(f"  Alt: {last_gga['alt']} m")
        
        elif last_rmc:
            print("\nLast RMC Position:")
            print(f"  Lat: {last_rmc['lat']}")
            print(f"  Lon: {last_rmc['lon']}")
        
        print(f"\nTotal messages received: {msg_count}")
        return 0
    
    finally:
        if ser.is_open:
            ser.close()
            print("✓ Port closed")


if __name__ == '__main__':
    sys.exit(main())
