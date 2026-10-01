#!/usr/bin/env python3
"""
GPS Information Display Program for EVK-F9P
Reads GNSS data from u-blox F9P receiver via COM6
Supports both UBX and NMEA protocols
"""

import serial
import sys
from datetime import datetime

try:
    from pyubx2 import UBXReader
    from pynmeagps import NMEAReader
except ImportError as e:
    print(f"Error: Required library not found: {e}")
    print("Please install with: pip install pyubx2 pynmeagps")
    sys.exit(1)


class GPSConsoleDisplay:
    """Displays GPS information from EVK-F9P in real-time"""
    
    def __init__(self, port='COM6', baudrate=38400):
        """
        Initialize GPS reader
        
        Args:
            port: Serial port name (default: COM6)
            baudrate: Baud rate (default: 38400)
        """
        self.port = port
        self.baudrate = baudrate
        self.ser = None
        self.message_count = 0
        self.last_position = None
        self.nmea_reader = None
        self.ubx_reader = None
        
    def connect(self):
        """Connect to the serial port"""
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=1.0
            )
            print(f"✓ Connected to {self.port} at {self.baudrate} baud")
            print(f"✓ Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print("-" * 70)
            
            # Try to create both readers - we'll use whichever works
            try:
                self.nmea_reader = NMEAReader(self.ser)
            except:
                pass
            
            try:
                self.ubx_reader = UBXReader(self.ser)
            except:
                pass
            
            return True
        except serial.SerialException as e:
            print(f"✗ Error: Failed to open {self.port}")
            print(f"  {str(e)}")
            return False
    
    def disconnect(self):
        """Close the serial connection"""
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("\n✓ Connection closed")
    
    def display_nmea_message(self, msg):
        """Display relevant parts of a NMEA message"""
        try:
            # Get message type or ID
            msg_id = None
            if hasattr(msg, 'msg_ID'):
                msg_id = msg.msg_ID
            elif hasattr(msg, 'sentence_id'):
                msg_id = msg.sentence_id
            elif hasattr(msg, 'msg_type'):
                msg_id = msg.msg_type
            
            if msg_id is None:
                return
            
            # Handle specific NMEA sentence types
            if msg_id == 'GGA' or msg_id == 'GPGGA' or msg_id == 'GNGGA':
                self._display_nmea_gga(msg)
            
            elif msg_id == 'RMC' or msg_id == 'GPRMC' or msg_id == 'GNRMC':
                self._display_nmea_rmc(msg)
            
            elif msg_id == 'GSA' or msg_id == 'GPGSA' or msg_id == 'GNGSA':
                self._display_nmea_gsa(msg)
            
            elif msg_id == 'GSV' or msg_id == 'GPGSV' or msg_id == 'GNGSV':
                self._display_nmea_gsv(msg)
            
            elif msg_id == 'VTG' or msg_id == 'GPVTG' or msg_id == 'GNVTG':
                self._display_nmea_vtg(msg)
        
        except Exception as e:
            print(f"[Debug] Error displaying NMEA: {str(e)}")
    
    def _display_nmea_gga(self, msg):
        """Display GGA (Fix Data) message"""
        try:
            print(f"\n[NMEA-GGA] Fix Data")
            
            # Check for valid fix
            quality = getattr(msg, 'quality', 0)
            if quality == 0:
                print(f"  Status: No fix")
                return
            
            quality_str = {
                1: "GPS Fix",
                2: "DGPS Fix", 
                4: "RTK Fixed",
                5: "RTK Float"
            }
            
            print(f"  Time: {getattr(msg, 'time', 'N/A')}")
            print(f"  Lat:  {getattr(msg, 'lat', 'N/A')}")
            print(f"  Lon:  {getattr(msg, 'lon', 'N/A')}")
            print(f"  Alt:  {getattr(msg, 'alt', 'N/A')} m")
            print(f"  Fix Quality: {quality_str.get(quality, f'Unknown ({quality})')}")
            print(f"  Num Satellites: {getattr(msg, 'numSV', 'N/A')}")
            print(f"  HDOP: {getattr(msg, 'hdop', 'N/A')}")
            
            # Store position
            lat = getattr(msg, 'lat', None)
            lon = getattr(msg, 'lon', None)
            alt = getattr(msg, 'alt', None)
            if lat is not None and lon is not None:
                self.last_position = {
                    'lat': lat,
                    'lon': lon,
                    'alt': alt,
                    'timestamp': getattr(msg, 'time', 'unknown')
                }
        except Exception as e:
            print(f"[Debug] Error parsing GGA: {str(e)}")
    
    def _display_nmea_rmc(self, msg):
        """Display RMC (Recommended Minimum Data) message"""
        try:
            print(f"\n[NMEA-RMC] Recommended Minimum Data")
            print(f"  Time: {getattr(msg, 'time', 'N/A')}")
            print(f"  Date: {getattr(msg, 'date', 'N/A')}")
            print(f"  Lat:  {getattr(msg, 'lat', 'N/A')}")
            print(f"  Lon:  {getattr(msg, 'lon', 'N/A')}")
            print(f"  Speed: {getattr(msg, 'speed', 'N/A')} knots")
            print(f"  Heading: {getattr(msg, 'track', 'N/A')}°")
            
            status = getattr(msg, 'status', 'V')
            status_str = "Valid" if status == 'A' else "Invalid"
            print(f"  Status: {status_str}")
        except Exception as e:
            print(f"[Debug] Error parsing RMC: {str(e)}")
    
    def _display_nmea_gsa(self, msg):
        """Display GSA (DOP and active satellites) message"""
        try:
            print(f"\n[NMEA-GSA] DOP and Active Satellites")
            mode = getattr(msg, 'mode', 'M')
            mode_str = "Manual" if mode == 'M' else "Automatic"
            print(f"  Mode: {mode_str}")
            
            fix_type = getattr(msg, 'fixType', 1)
            fix_str = {1: "No Fix", 2: "2D Fix", 3: "3D Fix"}
            print(f"  Fix Type: {fix_str.get(fix_type, f'Unknown ({fix_type})')}")
            
            print(f"  PDOP: {getattr(msg, 'pdop', 'N/A')}")
            print(f"  HDOP: {getattr(msg, 'hdop', 'N/A')}")
            print(f"  VDOP: {getattr(msg, 'vdop', 'N/A')}")
            
            # Active satellites
            sats = getattr(msg, 'sat_ids', [])
            if sats:
                print(f"  Active Satellites: {', '.join(str(s) for s in sats if s)}")
        except Exception as e:
            print(f"[Debug] Error parsing GSA: {str(e)}")
    
    def _display_nmea_gsv(self, msg):
        """Display GSV (Satellites in View) message"""
        try:
            print(f"\n[NMEA-GSV] Satellites in View")
            num_msgs = getattr(msg, 'msg_count', 1)
            msg_num = getattr(msg, 'msg_num', 1)
            print(f"  Message {msg_num}/{num_msgs}")
            
            num_sats = getattr(msg, 'num_sats', 0)
            print(f"  Satellites in View: {num_sats}")
        except Exception as e:
            print(f"[Debug] Error parsing GSV: {str(e)}")
    
    def _display_nmea_vtg(self, msg):
        """Display VTG (Track and Speed) message"""
        try:
            print(f"\n[NMEA-VTG] Track and Speed")
            print(f"  Track (True): {getattr(msg, 'track', 'N/A')}°")
            print(f"  Speed (Knots): {getattr(msg, 'speed_knots', 'N/A')}")
            print(f"  Speed (km/h): {getattr(msg, 'speed_kmh', 'N/A')}")
        except Exception as e:
            print(f"[Debug] Error parsing VTG: {str(e)}")
    
    def run(self):
        """Main loop to read and display GPS data"""
        if not self.connect():
            return False
        
        print("\nListening for GPS messages from EVK-F9P...\n")
        
        try:
            # Use NMEA reader primarily since EVK-F9P sends NMEA format
            reader = self.nmea_reader if self.nmea_reader else self.ubx_reader
            
            if reader is None:
                print("✗ Error: Could not create message reader")
                return False
            
            while True:
                try:
                    (raw_data, msg) = reader.read()
                    
                    if msg is not None:
                        self.message_count += 1
                        self.display_nmea_message(msg)
                        print(f"\n[Total messages received: {self.message_count}]")
                
                except StopIteration:
                    # No more data
                    continue
                except Exception as e:
                    # Continue on parse errors
                    continue
        
        except KeyboardInterrupt:
            print("\n\nInterrupted by user")
            if self.last_position:
                print("\nLast known position:")
                print(f"  Lat:  {self.last_position['lat']}")
                print(f"  Lon:  {self.last_position['lon']}")
                if self.last_position['alt'] is not None:
                    print(f"  Alt:  {self.last_position['alt']} m")
                print(f"  Time: {self.last_position['timestamp']}")
            return True
        
        except Exception as e:
            print(f"\n✗ Error: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
        
        finally:
            self.disconnect()


def main():
    """Main entry point"""
    print("=" * 70)
    print("EVK-F9P GPS Information Display Program")
    print("=" * 70)
    
    # Check if port is specified as argument
    port = 'COM6'
    if len(sys.argv) > 1:
        port = sys.argv[1]
    
    baudrate = 38400
    if len(sys.argv) > 2:
        try:
            baudrate = int(sys.argv[2])
        except ValueError:
            print(f"Warning: Invalid baudrate '{sys.argv[2]}', using default {baudrate}")
    
    print(f"Port: {port}, Baudrate: {baudrate}\n")
    
    # Create and run GPS display
    gps = GPSConsoleDisplay(port=port, baudrate=baudrate)
    success = gps.run()
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()


class GPSConsoleDisplay:
    """Displays GPS information from EVK-F9P in real-time"""
    
    def __init__(self, port='COM6', baudrate=38400):
        """
        Initialize GPS reader
        
        Args:
            port: Serial port name (default: COM6)
            baudrate: Baud rate (default: 38400)
        """
        self.port = port
        self.baudrate = baudrate
        self.ser = None
        self.ubx_reader = None
        self.message_count = 0
        self.last_position = None
        
    def connect(self):
        """Connect to the serial port"""
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=1.0
            )
            print(f"✓ Connected to {self.port} at {self.baudrate} baud")
            print(f"✓ Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print("-" * 70)
            return True
        except serial.SerialException as e:
            print(f"✗ Error: Failed to open {self.port}")
            print(f"  {str(e)}")
            return False
    
    def disconnect(self):
        """Close the serial connection"""
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("\n✓ Connection closed")
    
    def display_message(self, msg):
        """Display relevant parts of a UBX message"""
        msg_id = msg.msg_type
        
        # PVT (Position, Velocity, Time) message - most important
        if msg_id == 'NAV-PVT':
            self._display_nav_pvt(msg)
        
        # POSLLH (Position Longitude/Latitude/Height)
        elif msg_id == 'NAV-POSLLH':
            self._display_nav_posllh(msg)
        
        # VELNED (Velocity North/East/Down)
        elif msg_id == 'NAV-VELNED':
            self._display_nav_velned(msg)
        
        # STATUS (Receiver Navigation Status)
        elif msg_id == 'NAV-STATUS':
            self._display_nav_status(msg)
        
        # TIMEGPS (GPS Time of Day and Week Number)
        elif msg_id == 'NAV-TIMEGPS':
            self._display_nav_timegps(msg)
    
    def _display_nav_pvt(self, msg):
        """Display NAV-PVT message (Position, Velocity, Time)"""
        print(f"\n[NAV-PVT] Position & Velocity & Time")
        print(f"  Time: {msg.year:04d}-{msg.month:02d}-{msg.day:02d} " 
              f"{msg.hour:02d}:{msg.min:02d}:{msg.sec:02d}")
        print(f"  Lat:  {msg.lat:.8f}° N")
        print(f"  Lon:  {msg.lon:.8f}° E")
        print(f"  Alt:  {msg.hMSL:.2f} m (MSL) / {msg.height:.2f} m (ellipsoid)")
        print(f"  Accuracy: H±{msg.hAcc:.2f}m, V±{msg.vAcc:.2f}m")
        print(f"  Speed: {msg.gSpeed*3.6:.2f} km/h, Heading: {msg.headMot:.2f}°")
        print(f"  DOP: PDOP={msg.pDOP:.2f}, HDOP={msg.hDOP:.2f}, VDOP={msg.vDOP:.2f}")
        print(f"  Num SV: {msg.numSV} satellites")
        print(f"  Fix Type: {self._get_fix_type(msg.fixType)}")
        
        self.last_position = {
            'lat': msg.lat,
            'lon': msg.lon,
            'alt': msg.hMSL,
            'timestamp': f"{msg.year:04d}-{msg.month:02d}-{msg.day:02d} {msg.hour:02d}:{msg.min:02d}:{msg.sec:02d}"
        }
    
    def _display_nav_posllh(self, msg):
        """Display NAV-POSLLH message"""
        print(f"\n[NAV-POSLLH] Position (LLH)")
        print(f"  Lat:  {msg.lat:.8f}° N")
        print(f"  Lon:  {msg.lon:.8f}° E")
        print(f"  Alt:  {msg.hMSL:.2f} m (MSL) / {msg.height:.2f} m (ellipsoid)")
        print(f"  Accuracy: H±{msg.hAcc:.2f}m, V±{msg.vAcc:.2f}m")
    
    def _display_nav_velned(self, msg):
        """Display NAV-VELNED message"""
        print(f"\n[NAV-VELNED] Velocity (NED)")
        print(f"  V North: {msg.velN:.2f} m/s")
        print(f"  V East:  {msg.velE:.2f} m/s")
        print(f"  V Down:  {msg.velD:.2f} m/s")
        print(f"  Speed (3D): {msg.speed:.2f} m/s ({msg.speed*3.6:.2f} km/h)")
        print(f"  Heading: {msg.heading:.2f}°")
        print(f"  Accuracy: {msg.sAcc:.2f} m/s")
    
    def _display_nav_status(self, msg):
        """Display NAV-STATUS message"""
        print(f"\n[NAV-STATUS] Navigation Status")
        print(f"  Fix Type: {self._get_fix_type(msg.fixType)}")
        print(f"  Fix Status: {self._get_fix_status(msg.fixStatus)}")
        print(f"  Num SV: {msg.numSV} satellites")
    
    def _display_nav_timegps(self, msg):
        """Display NAV-TIMEGPS message"""
        print(f"\n[NAV-TIMEGPS] GPS Time")
        print(f"  Week: {msg.week}, TOW: {msg.iTOW} ms")
        print(f"  fTOW: {msg.fTOW} ns")
    
    @staticmethod
    def _get_fix_type(fix_type):
        """Convert fix type code to string"""
        fix_types = {
            0x00: "No Fix",
            0x01: "Dead Reckoning Only",
            0x02: "2D Fix",
            0x03: "3D Fix",
            0x04: "GNSS + Dead Reckoning",
            0x05: "Time Only Fix",
        }
        return fix_types.get(fix_type, f"Unknown ({fix_type})")
    
    @staticmethod
    def _get_fix_status(status):
        """Convert fix status code to string"""
        statuses = {
            0x00: "No Fix",
            0x01: "Fix Valid",
            0x02: "Differential Fix",
        }
        return statuses.get(status, f"Unknown ({status})")
    
    def run(self):
        """Main loop to read and display GPS data"""
        if not self.connect():
            return False
        
        print("\nListening for GPS messages from EVK-F9P...\n")
        
        try:
            # Create UBXReader once with the serial port
            ubx_reader = UBXReader(self.ser)
            
            while True:
                try:
                    # read_msg() returns (raw_data, parsed_message)
                    (raw_data, msg) = ubx_reader.read()
                    
                    if msg is not None:
                        self.message_count += 1
                        self.display_message(msg)
                        print(f"\n[Total messages received: {self.message_count}]")
                
                except Exception as e:
                    # Continue on parse errors, but show them for debugging
                    print(f"[Debug] Parse error: {str(e)}", file=sys.stderr)
                    continue
        
        except KeyboardInterrupt:
            print("\n\nInterrupted by user")
            if self.last_position:
                print("\nLast known position:")
                print(f"  Lat:  {self.last_position['lat']:.8f}° N")
                print(f"  Lon:  {self.last_position['lon']:.8f}° E")
                print(f"  Alt:  {self.last_position['alt']:.2f} m")
                print(f"  Time: {self.last_position['timestamp']}")
            return True
        
        except Exception as e:
            print(f"\n✗ Error: {str(e)}")
            return False
        
        finally:
            self.disconnect()


def main():
    """Main entry point"""
    print("=" * 70)
    print("EVK-F9P GPS Information Display Program")
    print("=" * 70)
    
    # Check if port is specified as argument
    port = 'COM6'
    if len(sys.argv) > 1:
        port = sys.argv[1]
    
    baudrate = 38400
    if len(sys.argv) > 2:
        try:
            baudrate = int(sys.argv[2])
        except ValueError:
            print(f"Warning: Invalid baudrate '{sys.argv[2]}', using default {baudrate}")
    
    print(f"Port: {port}, Baudrate: {baudrate}\n")
    
    # Create and run GPS display
    gps = GPSConsoleDisplay(port=port, baudrate=baudrate)
    success = gps.run()
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
