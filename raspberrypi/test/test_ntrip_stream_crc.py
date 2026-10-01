"""
NTRIP キャスターの RTCM ストリーム受信テスト（CRC24Q 検証付き）
F9P_BASE マウントポイントに接続して RTCM フレームを受信し、
RTCM3 CRC24Q を検証した有効フレームのみをカウントする。
"""
import socket
import time

HOST = "127.0.0.1"
PORT = 2101
MOUNTPOINT = "F9P_BASE"
TEST_SEC = 10


def crc24q(data: bytes) -> int:
    """RTCM3 CRC24Q (poly=0x1864CFB, init=0)"""
    crc = 0
    for byte in data:
        crc ^= byte << 16
        for _ in range(8):
            crc <<= 1
            if crc & 0x1000000:
                crc ^= 0x1864CFB
    return crc & 0xFFFFFF


def verify_rtcm3_crc(frame: bytes) -> bool:
    """
    RTCM3 フレームの CRC を検証する。
    frame = preamble(0xD3) + length(2) + payload + crc(3)
    """
    if len(frame) < 6 or frame[0] != 0xD3:
        return False
    expected = int.from_bytes(frame[-3:], byteorder="big")
    calculated = crc24q(frame[:-3])
    return expected == calculated


def extract_frames(buffer: bytes):
    """受信バッファから RTCM3 フレームを順次抽出する。"""
    frames = []
    while len(buffer) >= 3:
        idx = buffer.find(b"\xD3")
        if idx == -1:
            return frames, b""
        if idx > 0:
            buffer = buffer[idx:]

        if len(buffer) < 3:
            break

        length = ((buffer[1] & 0x03) << 8) | buffer[2]
        frame_len = 3 + length + 3
        if len(buffer) < frame_len:
            break

        frames.append(buffer[:frame_len])
        buffer = buffer[frame_len:]

    return frames, buffer


def main():
    s = socket.socket()
    s.settimeout(15)
    s.connect((HOST, PORT))

    req = f"GET /{MOUNTPOINT} HTTP/1.0\r\nUser-Agent: NTRIP CRCClient/1.0\r\n\r\n"
    s.sendall(req.encode())

    header = b""
    while b"\r\n\r\n" not in header:
        header += s.recv(256)

    print("=== NTRIP レスポンスヘッダ ===")
    print(header.decode("utf-8", errors="replace").split("\r\n\r\n")[0])
    print("=" * 40)

    if b"ICY 200 OK" not in header:
        print("✗ 接続失敗")
        s.close()
        raise SystemExit(1)

    print(f"\n✓ RTCMストリーム接続成功！ {TEST_SEC}秒間受信します...\n")

    buf = b""
    total_frames = 0
    valid_frames = 0
    invalid_crc = 0
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

        frames, buf = extract_frames(buf)
        for frame in frames:
            total_frames += 1
            if not verify_rtcm3_crc(frame):
                invalid_crc += 1
                continue

            valid_frames += 1
            payload_len = ((frame[1] & 0x03) << 8) | frame[2]
            if payload_len >= 2:
                msg_num = (frame[3] << 4) | (frame[4] >> 4)
                msg_stats[msg_num] = msg_stats.get(msg_num, 0) + 1

    s.close()

    print(f"=== CRC付きテスト結果 ({TEST_SEC}秒間) ===")
    print(f"総フレーム数      : {total_frames}")
    print(f"CRC有効フレーム数 : {valid_frames}")
    print(f"CRC無効フレーム数 : {invalid_crc}")
    print("MSG 種別別カウント（CRC有効のみ）:")
    for msg, cnt in sorted(msg_stats.items()):
        print(f"  MSG {msg:4d}: {cnt} 回")

    required = [1005, 1077, 1087, 1097, 1127, 1230]
    missing = [m for m in required if m not in msg_stats]

    if missing:
        print(f"\n⚠ 必須MSG未検出: {missing}")
    else:
        print("\n✓ 必須MSG(1005/1077/1087/1097/1127/1230)をすべて確認")

    if valid_frames > 0:
        print("✓ CRC検証つきRTCM受信: 成功")
    else:
        print("✗ CRC有効なRTCMフレームを受信できませんでした")


if __name__ == "__main__":
    main()
