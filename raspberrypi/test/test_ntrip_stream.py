"""
NTRIP キャスターの RTCM ストリーム受信テスト
F9P_BASE マウントポイントに接続して RTCM フレームを受信・表示する
"""
import socket
import time

HOST = "127.0.0.1"
PORT = 2101
MOUNTPOINT = "F9P_BASE"
TEST_SEC = 10  # 10秒間受信してカウント

s = socket.socket()
s.settimeout(15)
s.connect((HOST, PORT))

# NTRIP 1.0 リクエスト
req = f"GET /{MOUNTPOINT} HTTP/1.0\r\nUser-Agent: NTRIP TestClient/1.0\r\n\r\n"
s.sendall(req.encode())

# ICY 200 OK ヘッダを読む
header = b""
while b"\r\n\r\n" not in header:
    header += s.recv(256)

print("=== NTRIP レスポンスヘッダ ===")
print(header.decode("utf-8", errors="replace").split("\r\n\r\n")[0])
print("=" * 40)

if b"ICY 200 OK" not in header:
    print("✗ 接続失敗")
    s.close()
    exit(1)

print(f"\n✓ RTCMストリーム接続成功！ {TEST_SEC}秒間受信します...\n")

# RTCM フレームを受信してカウント
buf = b""
rtcm_count = 0
msg_stats = {}
start = time.time()
s.settimeout(2)

while time.time() - start < TEST_SEC:
    try:
        chunk = s.recv(4096)
        if not chunk:
            break
        buf += chunk
    except socket.timeout:
        continue

    # RTCM フレーム抽出 (0xD3 始まり)
    while len(buf) >= 3:
        idx = buf.find(b"\xD3")
        if idx == -1:
            buf = b""
            break
        if idx > 0:
            buf = buf[idx:]
        if len(buf) < 3:
            break
        length = ((buf[1] & 0x03) << 8) | buf[2]
        frame_len = 3 + length + 3
        if len(buf) < frame_len:
            break
        frame = buf[:frame_len]
        buf = buf[frame_len:]
        rtcm_count += 1
        if length >= 2:
            msg_num = (frame[3] << 4) | (frame[4] >> 4)
            msg_stats[msg_num] = msg_stats.get(msg_num, 0) + 1

s.close()

print(f"=== テスト結果 ({TEST_SEC}秒間) ===")
print(f"受信 RTCM フレーム数: {rtcm_count}")
print(f"MSG 種別別カウント:")
for msg, cnt in sorted(msg_stats.items()):
    print(f"  MSG {msg:4d}: {cnt} 回")

if 1005 in msg_stats:
    print("\n✓ MSG 1005 (基準局座標) 受信確認 → NTRIP基地局として正常動作！")
else:
    print("\n⚠ MSG 1005 未受信 (まだ5秒経過していない可能性あり)")

if rtcm_count > 0:
    print(f"✓ NTRIP データ生成・配信: 成功")
else:
    print("✗ RTCMデータを受信できませんでした")
