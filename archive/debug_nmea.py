#!/usr/bin/env python3
"""
Debug program to dump NMEA message attributes
"""

import serial
import sys

try:
    from pynmeagps import NMEAReader
except ImportError:
    print("Error: pynmeagps not found")
    sys.exit(1)


def main():
    port = 'COM6'
    
    try:
        ser = serial.Serial(port=port, baudrate=38400, timeout=1.0)
        print(f"Connected to {port}\n")
        
        nmea_reader = NMEAReader(ser)
        count = 0
        
        while count < 20:  # Read first 20 messages
            try:
                (raw_data, msg) = nmea_reader.read()
                
                if msg is not None:
                    count += 1
                    print(f"\n{'='*70}")
                    print(f"Message #{count}")
                    print(f"{'='*70}")
                    print(f"Type: {type(msg).__name__}")
                    print(f"Raw: {raw_data[:100]}")
                    
                    # Dump all attributes
                    print("\nAttributes:")
                    for attr in dir(msg):
                        if not attr.startswith('_'):
                            try:
                                val = getattr(msg, attr)
                                if not callable(val):
                                    print(f"  {attr}: {val} ({type(val).__name__})")
                            except:
                                pass
            
            except StopIteration:
                continue
            except Exception as e:
                print(f"Error: {e}")
                continue
    
    except serial.SerialException as e:
        print(f"Cannot open {port}: {e}")
        return 1
    
    finally:
        if ser.is_open:
            ser.close()
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
