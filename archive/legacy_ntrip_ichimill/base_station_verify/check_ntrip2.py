import socket, base64, time

SERVER = "ntrip.ales-corp.co.jp"
PORT = 2101
USER = "6y8swddj"
PASS = "xxu2w5"

for mp in ["RTCM32MSM5", "RTCM32MSM4", "RTCM31", "32MSM7NH"]:
    print(f"\n--- MOUNTPOINT: {mp} ---")
    try:
        s = socket.create_connection((SERVER, PORT), timeout=10)
        creds = base64.b64encode(f"{USER}:{PASS}".encode()).decode()
        req = (
            f"GET /{mp} HTTP/1.0\r\n"
            f"User-Agent: NTRIP SimpleRTK/1.0\r\n"
            f"Authorization: Basic {creds}\r\n"
            f"Accept: */*\r\n"
            f"\r\n"
        )
        s.sendall(req.encode())
        time.sleep(2)
        resp = s.recv(1024)
        print(resp.decode('utf-8', errors='replace')[:300])
        s.close()
    except Exception as e:
        print(f"Error: {e}")
    time.sleep(3)
