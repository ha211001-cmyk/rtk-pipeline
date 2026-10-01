#!/usr/bin/env python3
"""
udp_base_sender.py — 基地局 (MacBook) 側スクリプト

MacBookにUSB接続した基地局 F9P を「基地局モード」に設定し、
シリアルから RTCM3 補正データを読み取って、WiFi 経由の UDP で
ラズパイ（移動局側）へ送信します。

使い方:
    # ユニキャスト（デフォルト）: ラズパイ 192.168.11.50:50010 へ送信
    python3 udp_base_sender.py

    # ブロードキャスト（将来・複数受信機へ一斉配信）: 255.255.255.255 へ送信
    python3 udp_base_sender.py --broadcast

    # 基地局設定をスキップ（F9Pが事前設定済みの場合）
    python3 udp_base_sender.py --skip-config

    # 座標・ポートなどを上書き
    python3 udp_base_sender.py --lat 36.0751418 --lon 136.2133477 --alt 44.80 \
        --host 192.168.11.50 --port 50010
"""

import argparse
import glob
import socket
import sys
import time
from pathlib import Path
from typing import List, Optional

import serial

import udp_seq  # noqa: E402 - 同一ディレクトリの連番ヘッダモジュール

# ---------------------------------------------------------------------------
# 既存の基地局設定モジュール（f9p_configurator_v2.py）を再利用する
# 同じリポジトリ内の base_station_verify/rtcm_compare/ を import パスに追加
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_DIR = _REPO_ROOT / "base_station_verify" / "rtcm_compare"
if _CONFIG_DIR.is_dir():
    sys.path.insert(0, str(_CONFIG_DIR))

try:
    from f9p_configurator_v2 import F9pConfiguratorV2
except Exception:  # noqa: BLE001 - 依存が無い場合は後で明示的にエラーにする
    F9pConfiguratorV2 = None

# 福井大学 基準座標（基地局の固定座標）
DEFAULT_LAT = 36.0751418
DEFAULT_LON = 136.2133477
DEFAULT_ALT = 44.80  # 楕円体高 (m) = MSL 10.5m + ジオイド高 34.3m

DEFAULT_HOST = "raspi5.local"  # ラズパイのホスト名（mDNS。IPでも可）
DEFAULT_PORT = 50010
BROADCAST_HOST = "255.255.255.255"


def is_private_ipv4(ip: str) -> bool:
    """RFC1918 のプライベートIPv4か判定する（VPN等のキャリアグレードを除外）"""
    try:
        parts = [int(p) for p in ip.split(".")]
    except (ValueError, AttributeError):
        return False
    if len(parts) != 4:
        return False
    a, b = parts[0], parts[1]
    if a == 10:
        return True
    if a == 172 and 16 <= b <= 31:
        return True
    if a == 192 and b == 168:
        return True
    return False


def resolve_host(host: str) -> str:
    """ホスト名またはIPをIPv4アドレスに解決する

    - 既にIPアドレス（例: 192.168.11.50）ならそのまま返す
    - ホスト名（例: raspi5.local）は mDNS / DNS で解決する
    - 複数IPに解決された場合はプライベートIPv4を優先する
    """
    # IPアドレスとして解釈できればそのまま
    parts = host.split(".")
    if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        return host

    try:
        infos = socket.getaddrinfo(host, None,
                                   family=socket.AF_INET, type=socket.SOCK_DGRAM)
    except socket.gaierror as e:
        raise SystemExit(
            f"[ERROR] ホスト名 '{host}' を解決できませんでした: {e}\n"
            "        ラズパイと同一WiFiか確認し、必要なら --host 192.168.11.50 を指定してください"
        )

    ips = []
    seen = set()
    for info in infos:
        ip = info[4][0]
        if ip not in seen:
            seen.add(ip)
            ips.append(ip)

    if len(ips) == 1:
        return ips[0]

    private = [ip for ip in ips if is_private_ipv4(ip)]
    chosen = private[0] if private else ips[0]
    print(f"[INFO] '{host}' は複数のIPに解決されました: {', '.join(ips)}")
    print(f"[INFO] 使用IP: {chosen}（--host <IP> で明示指定可能）")
    return chosen


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を解析する"""
    p = argparse.ArgumentParser(
        description="F9P基地局 → UDP送信（MacBook側）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--host", default=DEFAULT_HOST,
                   help="送信先IPまたはホスト名（ユニキャスト）")
    p.add_argument("--port", type=int, default=DEFAULT_PORT,
                   help="UDP送信ポート番号")
    p.add_argument("--broadcast", action="store_true",
                   help="ブロードキャスト送信 (255.255.255.255) に切り替える")
    p.add_argument("--serial", default=None,
                   help="基地局F9Pのシリアルポート（省略時は自動検出）")
    p.add_argument("--baudrate", type=int, default=115200,
                   help="RTCM読み取り用ボーレート")
    p.add_argument("--config-baudrate", type=int, default=38400,
                   help="基地局設定用ボーレート")
    p.add_argument("--lat", type=float, default=DEFAULT_LAT, help="基準緯度（度）")
    p.add_argument("--lon", type=float, default=DEFAULT_LON, help="基準経度（度）")
    p.add_argument("--alt", type=float, default=DEFAULT_ALT, help="基準高度（楕円体高 m）")
    p.add_argument("--skip-config", action="store_true",
                   help="基地局設定をスキップ（事前設定済みの場合）")
    p.add_argument("--no-save", action="store_true",
                   help="設定をFlashに保存しない（RAMのみ。再起動で失われる）")
    p.add_argument("--seq-header", action="store_true",
                   help="UDPペイロードに連番ヘッダを付与して送信（受信側で欠落検出）")
    return p.parse_args()


def detect_serial_port() -> Optional[str]:
    """F9P のシリアルポートを自動検出する

    macOS と Linux（ラズパイ）の両方のデバイスパスに対応。
    複数見つかった場合は先頭を返す（--serial で明示指定が確実）。
    """
    candidates: List[str] = []
    candidates += sorted(glob.glob("/dev/cu.usbmodem*"))    # macOS (cu.*)
    candidates += sorted(glob.glob("/dev/tty.usbmodem*"))   # macOS (tty.*)
    candidates += sorted(glob.glob("/dev/ttyACM*"))         # Linux (USB CDC)
    candidates += sorted(glob.glob("/dev/ttyUSB*"))         # Linux (USBシリアル)

    if not candidates:
        return None
    if len(candidates) > 1:
        print("[WARN] シリアルポート候補が複数あります:")
        for c in candidates:
            print(f"         - {c}")
        print(f"[WARN] 先頭の {candidates[0]} を使用します（--serial で指定可能）")
    return candidates[0]


def extract_rtcm_frames(buffer: bytearray):
    """受信バッファから RTCM3 フレーム（0xD3 始まり）を1つずつ取り出す

    既存 rtk_RTCM_Log2.py / rtcm_receiver.py と同じフレーム解析ロジック。
    フレーム単位で yield するため、1フレーム = 1 UDP パケットで送れる。
    """
    while len(buffer) >= 6:
        if buffer[0] != 0xD3:
            buffer.pop(0)
            continue

        reserved = buffer[1] >> 2
        if reserved != 0:
            buffer.pop(0)
            continue

        frame_len = ((buffer[1] & 0x03) << 8) | buffer[2]
        if frame_len > 1023:  # RTCM3 の最大ペイロードは 1023
            buffer.pop(0)
            continue

        total_len = 6 + frame_len
        if len(buffer) < total_len:
            break

        frame = bytes(buffer[:total_len])
        del buffer[:total_len]
        yield frame


def run_sender(args: argparse.Namespace, port: str, target_host: str) -> None:
    """RTCM を読み取って UDP 送信する"""
    print("=" * 60)
    print("RTCM → UDP 送信を開始します")
    print(f"  シリアル: {port} @ {args.baudrate} bps")
    print(f"  送信先:   {target_host}:{args.port} "
          f"({'ブロードキャスト' if args.broadcast else 'ユニキャスト'})")
    print(f"  連番ヘッダ: {'有効(欠落検出用)' if args.seq_header else '無効'}")
    print("  Ctrl+C で終了")
    print("=" * 60)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if args.broadcast:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    ser = serial.Serial(port, args.baudrate, timeout=1.0)

    buffer = bytearray()
    frames_sent = 0
    bytes_sent = 0
    udp_packets_sent = 0
    udp_bytes_sent = 0
    seq = 0
    last_report = time.time()
    last_frame_time = time.time()

    try:
        while True:
            data = ser.read(4096)
            if data:
                buffer.extend(data)
                for frame in extract_rtcm_frames(buffer):
                    if args.seq_header:
                        payload = udp_seq.pack_seq_payload(seq, frame)
                        seq = (seq + 1) & 0xFFFFFFFF
                    else:
                        payload = frame
                    sock.sendto(payload, (target_host, args.port))
                    frames_sent += 1
                    bytes_sent += len(frame)
                    udp_packets_sent += 1
                    udp_bytes_sent += len(payload)
                    last_frame_time = time.time()

            # 5秒ごとに進捗表示
            if time.time() - last_report >= 5:
                elapsed = time.time() - last_frame_time
                status = "OK" if elapsed < 3 else "RTCM未受信"
                print(f"[INFO] frames={frames_sent}  bytes={bytes_sent}  "
                      f"udp_pkts={udp_packets_sent}  udp_bytes={udp_bytes_sent}  "
                      f"最終受信から{elapsed:.1f}秒 ({status})")
                if elapsed > 10:
                    print("[WARN] RTCMフレームが届いていません。"
                          "基地局設定（--skip-config を外す）やアンテナを確認してください")
                last_report = time.time()

    except KeyboardInterrupt:
        print("\n[INFO] Ctrl+C で終了します")
    finally:
        try:
            ser.close()
        except Exception:
            pass
        sock.close()
        print(f"[INFO] 送信終了（合計 frames={frames_sent}, bytes={bytes_sent}, "
              f"udp_pkts={udp_packets_sent}, udp_bytes={udp_bytes_sent}）")


def main() -> None:
    args = parse_args()

    port = args.serial or detect_serial_port()
    if not port:
        print("[ERROR] 基地局F9Pのシリアルポートを検出できませんでした")
        print("        --serial /dev/cu.usbmodemXXXX で明示指定してください")
        sys.exit(1)
    print(f"[INFO] 基地局F9P: {port}")

    # 基地局設定（毎回実行）
    if args.skip_config:
        print("[INFO] 基地局設定をスキップします（事前設定済み前提）")
    else:
        if F9pConfiguratorV2 is None:
            print("[ERROR] 既存の基地局設定モジュール "
                  "f9p_configurator_v2 を import できませんでした")
            print("        リポジトリ全体（base_station_verify/rtcm_compare/）を")
            print("        MacBook に用意し、pyubx2 をインストールしてください")
            sys.exit(1)

        save = not args.no_save
        print(f"[INFO] 基地局設定を実行します: "
              f"lat={args.lat:.7f} lon={args.lon:.7f} alt={args.alt:.2f} "
              f"save={'Flash' if save else 'RAMのみ'}")
        cfg = F9pConfiguratorV2(port, baudrate=args.config_baudrate)
        result = cfg.configure(lat=args.lat, lon=args.lon, alt=args.alt, save=save)

        if not result.get("all_ok"):
            print(f"[WARN] 設定に問題がある可能性があります "
                  f"(all_ok={result.get('all_ok')})")
            print("[WARN] ただし送信開始後に RTCM フレームが流れていれば設定は成功しています")

        if save:
            # Flash 保存時は F9P が再起動し、ポートが再列挙される
            print("[INFO] Flash保存のためF9Pが再起動します。5秒待機してポートを再検出...")
            time.sleep(5)
            if args.serial is None:
                port = detect_serial_port() or port
                print(f"[INFO] 再検出したポート: {port}")

    if args.broadcast:
        target_host = BROADCAST_HOST
    else:
        target_host = resolve_host(args.host)

    run_sender(args, port, target_host)


if __name__ == "__main__":
    main()
