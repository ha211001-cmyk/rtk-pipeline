import socket
import base64
import threading
import json
import time
import datetime
import os

# Configuration loading
def load_config(config_path=None):
    if config_path is None:
        config_path = os.path.join(os.path.dirname(__file__), "config.json")
    if not os.path.exists(config_path) and os.path.exists("config.json"):
        config_path = "config.json"
        
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)

config = load_config()

SERVER = config["server"]
PORT = config["port"]
MOUNT_POINT = config["mount_point"]
USERNAME = config["username"]
PASSWORD = config["password"]
LATITUDE = config["latitude"]
LONGITUDE = config["longitude"]

# Global variables for status monitoring
stats = {
    "connected": False,
    "received_count": 0,
    "sent_count": 0,
    "error_msg": ""
}

def convert_to_nmea_format(lat, lon):
    """Converts decimal degrees to NMEA DDMM.MMMM format with direction."""
    # Latitude
    lat_abs = abs(lat)
    lat_deg = int(lat_abs)
    lat_min = (lat_abs - lat_deg) * 60
    lat_nmea = f"{lat_deg:02d}{lat_min:07.4f}"
    lat_dir = "N" if lat >= 0 else "S"
    
    # Longitude
    lon_abs = abs(lon)
    lon_deg = int(lon_abs)
    lon_min = (lon_abs - lon_deg) * 60
    lon_nmea = f"{lon_deg:03d}{lon_min:07.4f}"
    lon_dir = "E" if lon >= 0 else "W"
        
    return lat_nmea, lat_dir, lon_nmea, lon_dir

def generate_gga():
    """Generates a valid NMEA GPGGA message with correct checksum."""
    lat_nmea, lat_dir, lon_nmea, lon_dir = convert_to_nmea_format(LATITUDE, LONGITUDE)
    
    # UTC timestamp (hhmmss.ss)
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%H%M%S.00")
    
    # GPGGA body: Fix quality=1 (Single), SV=12, HDOP=1.0, Alt=54.0m
    body = f"GPGGA,{timestamp},{lat_nmea},{lat_dir},{lon_nmea},{lon_dir},1,12,1.0,54.0,M,0.0,M,,"
    
    # XOR checksum calculation
    checksum = 0
    for char in body:
        checksum ^= ord(char)
        
    # Return byte stream ending with CRLF (\r\n)
    gga_sentence = f"${body}*{checksum:02X}\r\n"
    return gga_sentence.encode('ascii')

def receiver_thread(sock):
    """Thread to receive RTCM data and save to a single session log file."""
    global stats
    try:
        # Create log directory
        log_dir = os.path.join(os.path.dirname(__file__), "logs")
        os.makedirs(log_dir, exist_ok=True)
        
        # Define log filename for this session
        session_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(log_dir, f"rtcm_{session_time}.rtcm3")
        
        # Read HTTP header until \r\n\r\n
        header_data = b""
        while b"\r\n\r\n" not in header_data:
            chunk = sock.recv(4096)
            if not chunk:
                raise ConnectionError("Server closed connection during handshake.")
            header_data += chunk
        
        # Extract remaining RTCM payload after header
        stream_start_idx = header_data.find(b"\r\n\r\n") + 4
        initial_rtcm = header_data[stream_start_idx:]
        
        # Open binary log file and append data
        with open(filename, "ab") as f:
            if initial_rtcm:
                f.write(initial_rtcm)
                stats["received_count"] += 1
                
            while stats["connected"]:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                f.write(chunk)
                f.flush()  # Ensure data is written to disk
                stats["received_count"] += 1
                
    except Exception as e:
        stats["error_msg"] = str(e)
    finally:
        stats["connected"] = False

def sender_thread(sock):
    """Thread to send fake GGA messages periodically."""
    global stats
    try:
        # Send initial GGA immediately upon connection
        if stats["connected"]:
            sock.sendall(generate_gga())
            stats["sent_count"] += 1

        while stats["connected"]:
            time.sleep(2)  # Send every 2 seconds
            if stats["connected"]:
                sock.sendall(generate_gga())
                stats["sent_count"] += 1
    except Exception as e:
        stats["error_msg"] = str(e)
        stats["connected"] = False

def run_client():
    """Single connection attempt execution."""
    global stats
    stats["connected"] = False
    stats["received_count"] = 0
    stats["sent_count"] = 0
    stats["error_msg"] = ""

    print(f"Connecting to {SERVER}:{PORT} (Mountpoint: {MOUNT_POINT})...")
    
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(10.0)  # 10s connection timeout
    
    auth_str = f"{USERNAME}:{PASSWORD}"
    encoded_auth = base64.b64encode(auth_str.encode()).decode()
    
    request = (
        f"GET /{MOUNT_POINT} HTTP/1.1\r\n"
        f"Host: {SERVER}\r\n"
        f"User-Agent: NTRIP PythonClient/1.0\r\n"
        f"Authorization: Basic {encoded_auth}\r\n"
        f"Connection: close\r\n\r\n"
    ).encode('ascii')

    s.connect((SERVER, PORT))
    s.sendall(request)
    s.settimeout(None)  # Reset timeout for blocking recv

    stats["connected"] = True
    print("Connected successfully. Starting receiver/sender threads...")

    t_recv = threading.Thread(target=receiver_thread, args=(s,), daemon=True)
    t_send = threading.Thread(target=sender_thread, args=(s,), daemon=True)
    
    t_recv.start()
    t_send.start()

    # Monitor status while connected
    while stats["connected"]:
        print(f"Status: Connected | Received Chunks: {stats['received_count']} | GGA Sent: {stats['sent_count']}")
        time.sleep(1)

    print(f"Disconnected. Reason / Error: {stats['error_msg']}")
    s.close()

def main():
    while True:
        try:
            run_client()
        except Exception as e:
            print(f"Connection failed: {e}")
            stats["error_msg"] = str(e)
        
        print("Reconnecting in 5 seconds...")
        time.sleep(5)

if __name__ == "__main__":
    main()