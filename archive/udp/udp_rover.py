#!/usr/bin/env python3
"""
udp_rover.py — 移動局 (ラズパイ) 側スクリプト

MacBook（基地局側）から WiFi 経由の UDP で送られてくる RTCM3 補正データを
受信し、USB接続した移動局 F9P のシリアルポートへ流し込みます。
あわせて移動局の NMEA GGA を解析して RTK Float / Fixed 状態を表示します。

使い方:
    python3 udp_rover.py
    python3 udp_rover.py --port 50010 --serial /dev/ttyACM0
"""

import argparse
import glob
import socket
import sys
import threading
import time
from typing import List, Optional

import serial

try:
    from pyubx2 import UBXMessage
except Exception:  # noqa: BLE001 - pyubx2 が無い場合は TMODE3 無効化のみスキップ
    UBXMessage = None

DEFAULT_PORT = 50010        # UDP 受信ポート（基地局側と合わせる）
DEFAULT_BAUD = 38400        # 移動局 F9P のボーレート


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を解析する"""
    p = argparse.ArgumentParser(
        description="UDP受信 → 移動局F9P注入（ラズパイ側）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--port", type=int, default=DEFAULT_PORT,
                   help="UDP受信ポート番号")
    p.add_argument("--serial", default=None,
                   help="移動局F9Pのシリアルポート（省略時は自動検出）")
    p.add_argument("--baudrate", type=int, default=DEFAULT_BAUD,
                   help="移動局F9Pのボーレート")
    p.add_argument("--no-tmode3-reset", action="store_true",
                   help="TMODE3無効化（移動局モード化）をスキップする")
    return p.parse_args()


def detect_serial_port() -> Optional[str]:
    """移動局 F9P のシリアルポートを自動検出する"""
    candidates: List[str] = []
    candidates += sorted(glob.glob("/dev/ttyACM*"))
    candidates += sorted(glob.glob("/dev/ttyUSB*"))
    candidates += sorted(glob.glob("/dev/cu.usbmodem*"))
    candidates += sorted(glob.glob("/dev/tty.usbmodem*"))

    if not candidates:
        return None
    if len(candidates) > 1:
        print("[WARN] シリアルポート候補が複数あります:")
        for c in candidates:
            print(f"         - {c}")
        print(f"[WARN] 先頭の {candidates[0]} を使用します（--serial で指定可能）")
    return candidates[0]


def disable_tmode3(ser: serial.Serial) -> None:
    """F9P の TMODE3（基地局モード）を無効化して移動局として動作させる"""
    if UBXMessage is None:
        print("[WARN] pyubx2 が無いため TMODE3 無効化をスキップします")
        return
    try:
        msg = UBXMessage.config_set(1, 0, [("CFG-TMODE-MODE", 0)])
        ser.write(msg.serialize())
        ser.flush()
        print("[INFO] TMODE3 無効化（移動局モード）を送信しました")
        time.sleep(0.3)
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] TMODE3 無効化に失敗しました（続行します）: {e}")


def set_gga_rate_5hz(ser: serial.Serial) -> None:
    """F9P の NMEA GGA 出力を 5Hz に設定する（RTK状態表示用）"""
    try:
        ubx_cfg_msg = bytes.fromhex("B562060108 00F00005000000000823".replace(" ", ""))
        ser.write(ubx_cfg_msg)
        ser.flush()
        print("[INFO] GGA 出力を 5Hz に設定しました")
        time.sleep(0.2)
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] GGA 設定に失敗しました（続行します）: {e}")


def format_fix(quality: int) -> str:
    """GGA の quality 値を分かりやすい文字列に変換する"""
    mapping = {
        0: "No Fix (未測位)",
        1: "GPS Fix (単独測位)",
        2: "DGPS (ディファレンシャル)",
        4: "RTK Fixed (RTK固定解 - cm精度!)",
        5: "RTK Float (RTK浮動解 - 10~20cm)",
    }
    return mapping.get(quality, f"Unknown ({quality})")


def print_local_ip() -> None:
    """このラズパイ自身のIPを表示する（MacBook側の --host に使う）"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            print(f"[INFO] このラズパイのIP: {ip}")
            print("       → MacBook側の --host にこのIPを指定してください")
    except Exception:  # noqa: BLE001
        pass


def udp_to_serial(sock: socket.socket, ser: serial.Serial,
                  stop_event: threading.Event, stats: dict) -> None:
    """UDPで受信した RTCM データを移動局 F9P へ流し込むスレッド"""
    print("[INFO] UDP受信スレッド開始")
    while not stop_event.is_set():
        try:
            sock.settimeout(1.0)
            data, addr = sock.recvfrom(65535)
            if data:
                ser.write(data)
                ser.flush()
                stats["packets"] += 1
                stats["bytes"] += len(data)
        except socket.timeout:
            continue
        except Exception as e:  # noqa: BLE001
            if not stop_event.is_set():
                print(f"[UDP Error] {e}")
            break
    print("[INFO] UDP受信スレッド終了")


def display_loop(ser: serial.Serial, stop_event: threading.Event) -> None:
    """移動局の NMEA GGA を解析して RTK 状態を表示する（メインスレッド）"""
    last_show = 0.0
    while not stop_event.is_set():
        try:
            line = ser.readline()
            if not line:
                continue
            if line.startswith(b"$") and b"GGA" in line:
                now = time.time()
                if now - last_show < 1.0:  # 表示は1Hzに間引く
                    continue
                last_show = now

                line_str = line.decode("ascii", errors="ignore").strip()
                parts = line_str.split(",")
                if len(parts) > 9 and parts[2] and parts[4]:
                    lat_raw = float(parts[2])
                    lon_raw = float(parts[4])
                    lat = int(lat_raw / 100) + (lat_raw - int(lat_raw / 100) * 100) / 60
                    lon = int(lon_raw / 100) + (lon_raw - int(lon_raw / 100) * 100) / 60
                    alt = parts[9]
                    quality = int(parts[6]) if parts[6].isdigit() else 0
                    sats = parts[7]
                    print(f"[GGA] {format_fix(quality):<28} | "
                          f"緯度:{lat:.7f} 経度:{lon:.7f} 高度:{alt}m | 衛星:{sats}")
        except Exception as e:  # noqa: BLE001
            if not stop_event.is_set():
                print(f"[Serial Error] {e}")
            break


def main() -> None:
    args = parse_args()

    port = args.serial or detect_serial_port()
    if not port:
        print("[ERROR] 移動局F9Pのシリアルポートを検出できませんでした")
        print("        --serial /dev/ttyACM0 で明示指定してください")
        sys.exit(1)

    # 1. 移動局 F9P のシリアルポートを開く
    try:
        ser = serial.Serial(port, args.baudrate, timeout=0.5)
    except Exception as e:  # noqa: BLE001
        print(f"[ERROR] F9Pポート({port})のオープンに失敗しました: {e}")
        print("        ヒント: ls /dev/ttyACM* でポート確認、")
        print("        sudo usermod -aG dialout $USER で権限付与")
        sys.exit(1)
    print(f"[INFO] 移動局F9P: {port} @ {args.baudrate} bps")

    # 2. 移動局モード化 + GGA出力設定
    if not args.no_tmode3_reset:
        disable_tmode3(ser)
    set_gga_rate_5hz(ser)

    # 3. UDP ソケットを開く（ユニキャスト/ブロードキャスト両対応）
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", args.port))
    except OSError as e:
        print(f"[ERROR] UDPポート {args.port} のbindに失敗しました: {e}")
        ser.close()
        sys.exit(1)

    print_local_ip()
    print("=" * 60)
    print(f"UDP受信待機中: 0.0.0.0:{args.port}")
    print("  （ユニキャスト・ブロードキャストの両方を受信できます）")
    print("  Ctrl+C で終了")
    print("=" * 60)

    # 4. UDP受信スレッドを開始
    stop_event = threading.Event()
    stats = {"packets": 0, "bytes": 0}
    t = threading.Thread(target=udp_to_serial, args=(sock, ser, stop_event, stats),
                         daemon=True)
    t.start()

    # 5. RTK状態表示（メインスレッド）
    try:
        display_loop(ser, stop_event)
    except KeyboardInterrupt:
        print("\n[INFO] Ctrl+C で終了します")
    finally:
        stop_event.set()
        t.join(timeout=2)
        sock.close()
        ser.close()
        print(f"[INFO] 終了（受信 packets={stats['packets']}, bytes={stats['bytes']}）")


if __name__ == "__main__":
    main()
