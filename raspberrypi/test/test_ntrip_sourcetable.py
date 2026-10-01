import socket, time

s = socket.socket()
s.settimeout(5)
s.connect(("127.0.0.1", 2101))
s.sendall(b"GET / HTTP/1.0\r\nUser-Agent: NTRIP TestClient/1.0\r\n\r\n")
time.sleep(1)
data = s.recv(4096)
print("=== NTRIP ソーステーブル ===")
print(data.decode("utf-8", errors="replace"))
s.close()
