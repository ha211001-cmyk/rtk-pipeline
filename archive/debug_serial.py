#!/usr/bin/env python3
"""
Debug program to check serial data from rtk-pipeline
Shows raw bytes being received on COM6
"""

import serial
import sys
from datetime import datetime


def hex_str(data, length=None):
    """Convert bytes to hex string"""
    s = ' '.join(f'{b:02x}' for b in data)
    if length:
        return f"{s:<{length}}"
    return s


def main():
    """Main entry point"""
    port = 'COM6'
    baudrate = 38400
    
    if len(sys.argv) > 1:
        port = sys.argv[1]
    if len(sys.argv) > 2:
        try:
            baudrate = int(sys.argv[2])
        except ValueError:
            pass
    
    print(f"Opening {port} at {baudrate} baud...")
    
    try:
        ser = serial.Serial(port=port, baudrate=baudrate, timeout=1.0)
        print(f"✓ Port opened successfully\n")
        print("Waiting for data (press Ctrl+C to stop)...\n")
        print(f"{'Time':<10} {'Bytes Rx':<15} {'Hex':<24} {'ASCII'}")
        print("-" * 80)
        
        byte_count = 0
        ubx_frame_count = 0
        last_log = datetime.now()
        
        while True:
            if ser.in_waiting > 0:
                data = ser.read(ser.in_waiting)
                byte_count += len(data)
                
                # Count UBX frames (start with 0xB5 0x62)
                for i in range(len(data) - 1):
                    if data[i] == 0xB5 and data[i + 1] == 0x62:
                        ubx_frame_count += 1
                
                # Display data
                hex_str_val = hex_str(data[:16])  # Show first 16 bytes
                ascii_val = ''.join(chr(b) if 32 <= b < 127 else '.' for b in data[:16])
                
                time_str = datetime.now().strftime("%H:%M:%S")
                print(f"{time_str}  {len(data):<14} {hex_str_val:<24} {ascii_val}")
                
                # Print first 50 bytes with frame markers
                if len(data) > 16:
                    print(f"        Full: {hex_str(data)}")
                
                # Highlight UBX frames
                for i in range(len(data) - 1):
                    if data[i] == 0xB5 and data[i + 1] == 0x62:
                        print(f"        ↑↑ UBX frame detected at position {i}")
            else:
                # Show periodic status every 5 seconds
                now = datetime.now()
                if (now - last_log).total_seconds() >= 5:
                    print(f"[{now.strftime('%H:%M:%S')}] Waiting... (Bytes rx: {byte_count}, UBX frames: {ubx_frame_count})")
                    last_log = now
    
    except serial.SerialException as e:
        print(f"✗ Error opening {port}: {e}")
        return 1
    
    except KeyboardInterrupt:
        print(f"\n\nStopped by user")
        print(f"Total bytes received: {byte_count}")
        print(f"UBX frames detected: {ubx_frame_count}")
        return 0
    
    finally:
        if ser.is_open:
            ser.close()
            print(f"Port closed")


if __name__ == '__main__':
    sys.exit(main())
