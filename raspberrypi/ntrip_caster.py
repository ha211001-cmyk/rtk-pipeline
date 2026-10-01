#!/usr/bin/env python3
"""
F9P NTRIP キャスター（基地局サーバー）
【Raspberry Pi 5 対応版】

F9P を Fixed Mode（既知点固定）で設定し、RTCM3 補正データを
NTRIP プロトコルでローカルネットワーク上のローバーへ配信します。

ローバー側の設定:
  サーバー      : <Raspberry Pi の IP アドレス>:2101
  マウントポイント: F9P_BASE
  ユーザー/パス  : 不要（認証なし）

使い方:
  python3 ntrip_caster.py
"""

import sys
import time
import socket
import struct
import threading
import serial

# ============================================================
# 基地局固定座標（既知点）
# ============================================================
FIXED_LAT = 36.070846    # 緯度 (度, WGS84)
FIXED_LON = 136.595280   # 経度 (度, WGS84)
FIXED_ALT = 1237.00      # 高度 (m, 楕円体高)

# F9P シリアル設定
SERIAL_PORT = "/dev/ttyACM0"
BAUD = 38400

# NTRIP キャスター設定
NTRIP_PORT = 2101
MOUNTPOINT = "F9P_BASE"

# F9P に出力させる RTCM3 メッセージ (クラス, ID, レート, 説明)
RTCM_MSGS = [
    (0xF5, 0x05, 5, "RTCM 1005 基準局座標 (5秒毎)"),
    (0xF5, 0x4D, 1, "RTCM 1077 GPS MSM7"),
    (0xF5, 0x57, 1, "RTCM 1087 GLONASS MSM7"),
    (0xF5, 0x61, 1, "RTCM 1097 Galileo MSM7"),
    (0xF5, 0x7F, 1, "RTCM 1127 BeiDou MSM7"),
    (0xF5, 0xE6, 5, "RTCM 1230 GLO コードフェーズバイアス (5秒毎)"),
]

# 接続中クライアント管理
_clients: list = []
_clients_lock = threading.Lock()
_running = True


def _crc24q(data: bytes) -> int:
    """RTCM3 CRC24Q (poly=0x1864CFB, init=0) を計算"""
    crc = 0
    for byte in data:
        crc ^= byte << 16
        for _ in range(8):
            crc <<= 1
            if crc & 0x1000000:
                crc ^= 0x1864CFB
    return crc & 0xFFFFFF


def _rtcm3_crc_ok(frame: bytes) -> bool:
    """RTCM3 フレームの CRC24Q を検証"""
    if len(frame) < 6 or frame[0] != 0xD3:
        return False
    expected = int.from_bytes(frame[-3:], byteorder="big")
    calculated = _crc24q(frame[:-3])
    return expected == calculated


# ============================================================
# UBX ユーティリティ
# ============================================================
def _ubx_checksum(data: bytes) -> bytes:
    ck_a = ck_b = 0
    for b in data:
        ck_a = (ck_a + b) & 0xFF
        ck_b = (ck_b + ck_a) & 0xFF
    return bytes([ck_a, ck_b])


def _make_ubx(cls_id: int, msg_id: int, payload: bytes) -> bytes:
    inner = bytes([cls_id, msg_id]) + struct.pack('<H', len(payload)) + payload
    return bytes([0xB5, 0x62]) + inner + _ubx_checksum(inner)


def _send_ubx_ack(ser: serial.Serial, packet: bytes, label: str, timeout: float = 1.0) -> bool:
    ser.reset_input_buffer()
    ser.write(packet)
    deadline = time.time() + timeout
    buf = b''
    while time.time() < deadline:
        try:
            n = ser.in_waiting or 1
            chunk = ser.read(n)
        except serial.SerialException:
            # USB 再列挙などの一時的エラーは無視して継続
            time.sleep(0.05)
            continue
        if chunk:
            buf += chunk
        if b'\xB5\x62\x05\x01' in buf:
            print(f"  ✓ ACK: {label}")
            return True
        if b'\xB5\x62\x05\x00' in buf:
            print(f"  ✗ NAK: {label}")
            return False
    print(f"  ? タイムアウト: {label}")
    return False


# ============================================================
# F9P 設定（TMODE3 Fixed + RTCM3 出力）
# ============================================================
def setup_f9p(ser: serial.Serial) -> bool:
    """
    F9P を基地局モードに設定する。
    STEP1: UBX-CFG-TMODE3 Fixed Mode（既知点 LLH 形式）
    STEP2: UBX-CFG-MSG で RTCM3 メッセージを USB ポートに出力
    """
    lat_int = round(FIXED_LAT * 1e7)
    lon_int = round(FIXED_LON * 1e7)
    alt_cm  = round(FIXED_ALT * 100)
    lat_hp  = round((FIXED_LAT - lat_int * 1e-7) * 1e9)
    lon_hp  = round((FIXED_LON - lon_int * 1e-7) * 1e9)
    alt_hp  = round((FIXED_ALT * 100 - alt_cm) * 10)

    # UBX-CFG-TMODE3 payload: 40 bytes
    # '<BBHiiibbbBIIIII' = 1+1+2+4+4+4+1+1+1+1+4+4+4+4+4 = 40 bytes
    def _tmode_payload(mode_flags):
        return struct.pack(
            '<BBHiiibbbBIIIII',
            0,        # version
            0,        # reserved1
            mode_flags,
            lat_int, lon_int, alt_cm,
            lat_hp, lon_hp, alt_hp,
            0,        # reserved2
            10000,    # fixedPosAcc [0.1mm]
            0, 0,     # svinMinDur, svinAccLimit (Fixed Modeでは不使用)
            0, 0,     # reserved3
        )

    print("\n[STEP1] TMODE3 設定")
    print(f"  緯度: {FIXED_LAT}°  経度: {FIXED_LON}°  高度: {FIXED_ALT} m")

    # まず Disabled (mode=0) に設定して内部状態をリセット
    disabled_payload = _tmode_payload(0x0000)  # mode=0 (Disabled), ECEF
    _send_ubx_ack(ser, _make_ubx(0x06, 0x71, disabled_payload), "CFG-TMODE3 Disabled (リセット)", timeout=1.5)
    time.sleep(1.0)

    # Fixed Mode (mode=2, LLH) に設定
    fixed_payload = _tmode_payload(0x0102)  # bit[1:0]=2(Fixed), bit8=1(LLH)
    ok1 = _send_ubx_ack(ser, _make_ubx(0x06, 0x71, fixed_payload), "CFG-TMODE3 Fixed Mode", timeout=2.0)

    # TMODE3 後は F9P が内部リセットすることがある → 3秒待機してバッファをクリア
    print("  TMODE3 安定待ち (3秒)...")
    time.sleep(3.0)
    try:
        ser.reset_input_buffer()
    except serial.SerialException:
        pass

    # TMODE3 状態をポールして実際のモードを確認
    ser.reset_input_buffer()
    ser.write(_make_ubx(0x06, 0x71, b''))
    time.sleep(0.5)
    poll_buf = b''
    poll_deadline = time.time() + 2.0
    while time.time() < poll_deadline:
        try:
            chunk = ser.read(ser.in_waiting or 1)
            if chunk:
                poll_buf += chunk
        except serial.SerialException:
            break
        idx = poll_buf.find(b'\xB5\x62\x06\x71')
        if idx != -1 and len(poll_buf) >= idx + 48:
            rsp = poll_buf[idx:]
            if len(rsp) >= 48:
                flags = struct.unpack('<H', rsp[8:10])[0]
                actual_mode = flags & 0x3
                lla_fmt = (flags >> 8) & 0x1
                mode_str = {0: "Disabled", 1: "Survey-In", 2: "Fixed"}.get(actual_mode, f"Unknown({actual_mode})")
                print(f"  [確認] TMODE3 モード: {mode_str} / 座標形式: {'LLH' if lla_fmt else 'ECEF'}")
            break

    if not ok1:
        print("  ⚠ TMODE3 NAK: F9P が固定モードに応答しません")
        print("    → RTCM 1005（基準局座標）が出力されない可能性があります")

    print("\n[STEP2] RTCM3 出力有効化 (USB ポート)")
    for cls, id_, rate, desc in RTCM_MSGS:
        msg_payload = bytes([cls, id_, 0, 0, 0, rate, 0, 0])
        _send_ubx_ack(ser, _make_ubx(0x06, 0x01, msg_payload), desc, timeout=0.5)
    time.sleep(0.5)

    # STEP3: 設定を BBR/Flash に保存（再接続後も有効に）
    # UBX-CFG-CFG class=0x06, id=0x09
    # clearMask=0, saveMask=0xFFFF (全て保存), loadMask=0
    print("\n[STEP3] 設定を Flash/BBR に保存")
    save_payload = struct.pack('<III', 0x00000000, 0x0000FFFF, 0x00000000)
    _send_ubx_ack(ser, _make_ubx(0x06, 0x09, save_payload), "CFG-CFG Save to Flash", timeout=2.0)

    return ok1


# ============================================================
# RTCM データ収集 → クライアントへブロードキャスト
# ============================================================
def _broadcast(data: bytes):
    """全 NTRIP クライアントに RTCM フレームを配信し、切断済みを除去する"""
    with _clients_lock:
        dead = []
        for sock in _clients:
            try:
                sock.sendall(data)
            except Exception:
                dead.append(sock)
        for s in dead:
            _clients.remove(s)
            try:
                s.close()
            except Exception:
                pass
        if dead:
            print(f"[Caster] {len(dead)} クライアント切断 (残: {len(_clients)})")


def rtcm_reader_thread(ser: serial.Serial):
    """F9P から RTCM3 フレームを読み取り、クライアントへ配信するスレッド"""
    global _running
    buf = b''
    rtcm_count = 0
    valid_count = 0
    invalid_count = 0
    msg_stats: dict = {}
    last_log = time.time()

    print("[RTCM] 読み取りスレッド開始")
    while _running:
        try:
            chunk = ser.read(ser.in_waiting or 1)
        except serial.SerialException as e:
            # USB 再列挙などの一時的なエラーは少し待って継続
            print(f"[RTCM] シリアル一時エラー (再試行): {e}")
            time.sleep(0.5)
            continue
        except Exception as e:
            print(f"[RTCM] シリアル読み取りエラー: {e}")
            _running = False
            break

        if not chunk:
            continue
        buf += chunk

        # RTCM3 フレーム (先頭 0xD3) を抽出してブロードキャスト
        while len(buf) >= 3:
            idx = buf.find(b'\xD3')
            if idx == -1:
                buf = b''
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

            if not _rtcm3_crc_ok(frame):
                invalid_count += 1
                continue

            valid_count += 1
            _broadcast(frame)

            if length >= 2:
                msg_num = (frame[3] << 4) | (frame[4] >> 4)
                msg_stats[msg_num] = msg_stats.get(msg_num, 0) + 1

            now = time.time()
            if now - last_log >= 5.0:
                with _clients_lock:
                    nc = len(_clients)
                types = sorted(msg_stats.keys())
                print(
                    f"[RTCM] 総:{rtcm_count} 有効:{valid_count} 無効CRC:{invalid_count} "
                    f"| MSG 種別: {types} | クライアント: {nc}"
                )
                last_log = now

    print("[RTCM] 読み取りスレッド終了")


# ============================================================
# NTRIP プロトコル実装
# ============================================================
def _local_ip() -> str:
    """実用的なローカル IP アドレスを取得"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return socket.gethostbyname(socket.gethostname())


def _make_sourcetable() -> bytes:
    """NTRIP ソーステーブル HTTP レスポンスを生成"""
    detail = "1005(5),1077(1),1087(1),1097(1),1127(1),1230(5)"
    body = (
        f"STR;{MOUNTPOINT};F9P_BASE;RTCM 3.3;{detail};;"
        f"GPS+GLO+GAL+BDS;Local;;{FIXED_LAT:.2f};{FIXED_LON:.2f};"
        f"0;1;u-blox F9P;;N;0;;\r\n"
        "ENDSOURCETABLE\r\n"
    )
    header = (
        "SOURCETABLE 200 OK\r\n"
        "Server: NTRIP F9P-Caster/1.0\r\n"
        "Ntrip-Version: Ntrip/1.0\r\n"
        "Content-Type: text/plain\r\n"
        f"Content-Length: {len(body.encode())}\r\n"
        "\r\n"
    )
    return (header + body).encode()


def ntrip_client_handler(conn: socket.socket, addr):
    """各 NTRIP クライアント接続を処理するスレッド関数"""
    print(f"[Caster] 接続: {addr}")
    try:
        # HTTP リクエストヘッダを読み取り
        request = b''
        conn.settimeout(5.0)
        while b'\r\n\r\n' not in request and len(request) < 4096:
            chunk = conn.recv(512)
            if not chunk:
                break
            request += chunk

        if not request:
            return

        first_line = request.split(b'\r\n')[0].decode('ascii', errors='replace')
        print(f"[Caster] リクエスト: '{first_line}' from {addr}")

        # GET / もしくは GET /sourcetable → ソーステーブル返却
        if b'GET / ' in request or b'GET /sourcetable' in request.lower():
            conn.sendall(_make_sourcetable())
            print(f"[Caster] ソーステーブル送信 → {addr}")
            return

        # GET /F9P_BASE → RTCM ストリーム開始
        mount_req = f'GET /{MOUNTPOINT}'.encode()
        if mount_req in request:
            conn.settimeout(None)
            response = (
                "ICY 200 OK\r\n"
                "Server: NTRIP F9P-Caster/1.0\r\n"
                "Ntrip-Version: Ntrip/1.0\r\n"
                "Content-Type: gnss/data\r\n"
                "\r\n"
            )
            conn.sendall(response.encode())
            with _clients_lock:
                _clients.append(conn)
            print(f"[Caster] RTCM ストリーム開始 → {addr} (計 {len(_clients)} 接続)")

            # _broadcast() が切断を検知するまで待機
            while _running:
                with _clients_lock:
                    if conn not in _clients:
                        break
                time.sleep(0.5)
            return

        # 不明パス
        conn.sendall(b"HTTP/1.0 404 Not Found\r\n\r\nMountpoint not found\r\n")

    except Exception as e:
        print(f"[Caster] クライアントエラー {addr}: {e}")
    finally:
        with _clients_lock:
            if conn in _clients:
                _clients.remove(conn)
        try:
            conn.close()
        except Exception:
            pass
        print(f"[Caster] 切断: {addr}")


# ============================================================
# メイン
# ============================================================
def main():
    global _running

    local_ip = _local_ip()
    print("=" * 70)
    print("F9P NTRIP キャスター [Raspberry Pi 5版]")
    print(f"固定座標 : 緯度 {FIXED_LAT}°  経度 {FIXED_LON}°  高度 {FIXED_ALT} m")
    print(f"NTRIP    : {local_ip}:{NTRIP_PORT} / {MOUNTPOINT}")
    print("=" * 70)

    # F9P 接続
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD, timeout=1.0)
        print(f"\n✓ F9P 接続: {SERIAL_PORT} ({BAUD} baud)")
    except Exception as e:
        print(f"✗ シリアルポート接続失敗: {e}")
        sys.exit(1)

    # F9P 設定（TMODE3 + RTCM msgs）
    setup_f9p(ser)
    time.sleep(1.0)

    # RTCM 読み取りスレッド開始
    reader = threading.Thread(target=rtcm_reader_thread, args=(ser,), daemon=True)
    reader.start()

    # NTRIP サーバー起動
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(("0.0.0.0", NTRIP_PORT))
    except OSError as e:
        print(f"✗ ポート {NTRIP_PORT} のバインド失敗: {e}")
        print(f"  別ポートを試す場合: NTRIP_PORT を変更してください (例: 2102)")
        ser.close()
        sys.exit(1)

    server.listen(10)
    server.settimeout(1.0)

    print(f"\n✓ NTRIP キャスター起動")
    print(f"  ローバー接続先 : {local_ip}:{NTRIP_PORT}")
    print(f"  マウントポイント: {MOUNTPOINT}")
    print(f"  認証           : 不要")
    print("\nCtrl+C で終了\n")

    try:
        while _running:
            try:
                conn, addr = server.accept()
            except socket.timeout:
                continue
            t = threading.Thread(target=ntrip_client_handler, args=(conn, addr), daemon=True)
            t.start()
    except KeyboardInterrupt:
        print("\n\n✓ 終了（Ctrl+C）")
    finally:
        _running = False
        server.close()
        ser.close()
        print("✓ サーバー停止")


if __name__ == "__main__":
    main()
