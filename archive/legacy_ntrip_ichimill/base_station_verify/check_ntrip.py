import socket, base64, time

s = socket.create_connection(('ntrip.ales-corp.co.jp', 2101), timeout=10)
creds = base64.b64encode(b'6y8swddj:xxu2w5').decode()
req = 'GET / HTTP/1.0\r\nUser-Agent: NTRIP Test\r\nAuthorization: Basic ' + creds + '\r\n\r\n'
s.sendall(req.encode())
time.sleep(2)
data = s.recv(4096)
print(data.decode('utf-8', errors='replace')[:3000])
s.close()
