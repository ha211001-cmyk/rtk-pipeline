#!/usr/bin/env python3
"""
base_recorder.py — 基地局 F9P から RTCM3 を読み取り .rtcm3 へ保存（＋任意で UDP 送信）

開けた場所での 10 分静止記録用。基地局 F9P をシリアルで読み、
RTCM3 フレームを .rtcm3 ファイルへ保存しつつ、ラズパイへ UDP 送信も行う。

前提:
  - 基地局 F9P は基地局モード（TMODE3 + RTCM3 出力）で動作していること。
    --lat/--lon/--alt を指定すると、このスクリプトが基地局を設定してから記録する。
    設定済みの場合は座標指定なしでそのまま記録する。

使い方:
    python3 base_recorder.py                       # 記録 + UDP 送信（設定済み前提）
    python3 base_recorder.py --no-udp              # 記録のみ（UDP 送信なし）
    python3 base_recorder.py --lat 36.07 --lon 136.21 --alt 48.0   # 基地局設定 + 記録
    python3 base_recorder.py --serial /dev/cu.usbmodemXXX --log-dir logs
"""

import argparse
import glob
import socket
import sys
import time
from pathlib import Path
from typing import List, Optional

import serial

from rtcm_logger import RtcmFrameLogger

# 既存の基地局設定モジュール（f9p_configurator_v2.py）を再利用する
_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_DIR = _REPO_ROOT / "base_station_verify" / "rtcm_compare"
if _CONFIG_DIR.is_dir():
    sys.path.insert(0, str(_CONFIG_DIR))

try:
    from f9p_configurator_v2 import F9pConfiguratorV2
except Exception:  # noqa: BLE001 - 依存が無い場合は後で明示的にエラーにする
    F9pConfiguratorV2 = None

DEFAULT_HOST = "raspi5.local"
DEFAULT_PORT = 50010


def detect_serial_port() -> Optional[str]:
    """F9P のシリアルポートを自動検出する（macOS / Linux 対応）。"""
    candidates: List[str] = []
    candidates += sorted(glob.glob("/dev/cu.usbmodem*"))    # macOS (cu.*)
    candidates += sorted(glob.glob("/dev/tty.usbmodem*"))   # macOS (tty.*)
    candidates += sorted(glob.glob("/dev/ttyACM*"))         # Linux (USB CDC)
    candidates += sorted(glob.glob("/dev/ttyUSB*"))         # Linux (USB serial)
    return candidates[0] if candidates else None


def resolve_host(host: str) -> str:
    """ホスト名または IP を IPv4 アドレスに解決する。"""
    parts = host.split(".")
    if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        return host
    infos = socket.getaddrinfo(host, None, family=socket.AF_INET, type=socket.SOCK_DGRAM)
    return infos[0][4][0]


def extract_rtcm_frames(buffer: bytearray):
    """受信バッファから RTCM3 フレーム（0xD3 始まり）を1つずつ取り出す。"""
    while len(buffer) >= 6:
        if buffer[0] != 0xD3:
            buffer.pop(0)
            continue
        if (buffer[1] >> 2) != 0:
            buffer.pop(0)
            continue
        frame_len = ((buffer[1] & 0x03) << 8) | buffer[2]
        if frame_len > 1023:  # RTCM3 の最大ペイロードは 1023
            buffer.pop(0)
            continue
        total = 6 + frame_len
        if len(buffer) < total:
            break
        yield bytes(buffer[:total])
        del buffer[:total]


def main() -> None:
    p = argparse.ArgumentParser(
        description="基地局 RTCM 記録 + UDP 送信",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--serial", default=None, help="基地局F9Pのシリアルポート（省略時は自動検出）")
    p.add_argument("--baudrate", type=int, default=115200, help="RTCM読み取り用ボーレート")
    p.add_argument("--host", default=DEFAULT_HOST, help="UDP送信先IPまたはホスト名")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help="UDP送信ポート")
    p.add_argument("--no-udp", action="store_true", help="UDP送信を行わない（記録のみ）")
    p.add_argument("--log-dir", default="logs", help="RTCM保存先ディレクトリ")
    p.add_argument("--tag", default="base", help="ログファイル名の識別子")
    p.add_argument("--lat", type=float, default=None,
                   help="基地局の基準緯度（度）。指定時のみ基地局設定を実行")
    p.add_argument("--lon", type=float, default=None, help="基地局の基準経度（度）")
    p.add_argument("--alt", type=float, default=None, help="基地局の基準高度（楕円体高 m）")
    p.add_argument("--config-baudrate", type=int, default=38400, help="基地局設定用ボーレート")
    p.add_argument("--no-save", action="store_true", help="設定をFlashに保存しない（RAMのみ）")
    args = p.parse_args()

    port = args.serial or detect_serial_port()
    if not port:
        print("[ERROR] 基地局F9Pのシリアルポートを検出できませんでした")
        print("        --serial /dev/cu.usbmodemXXXX で明示指定してください")
        sys.exit(1)

    # 基地局設定（--lat/--lon/--alt をすべて指定した場合のみ実行）
    if args.lat is not None and args.lon is not None and args.alt is not None:
        if F9pConfiguratorV2 is None:
            print("[ERROR] 基地局設定モジュール f9p_configurator_v2 を import できませんでした")
            print("        リポジトリ全体（base_station_verify/rtcm_compare/）と pyubx2 が必要です")
            sys.exit(1)
        save = not args.no_save
        print("[INFO] 基地局設定を実行: lat=%.7f lon=%.7f alt=%.2f save=%s"
              % (args.lat, args.lon, args.alt, "Flash" if save else "RAMのみ"))
        cfg = F9pConfiguratorV2(port, baudrate=args.config_baudrate)
        result = cfg.configure(lat=args.lat, lon=args.lon, alt=args.alt, save=save)
        if not result.get("all_ok"):
            print("[WARN] 設定に問題がある可能性があります (all_ok=%s)" % result.get("all_ok"))
            print("[WARN] ただし記録開始後に RTCM フレームが流れていれば設定は成功しています")
        if save:
            # Flash 保存時は F9P が再起動し、ポートが再列挙される
            print("[INFO] Flash保存のためF9Pが再起動します。5秒待機してポートを再検出...")
            time.sleep(5)
            if args.serial is None:
                port = detect_serial_port() or port
                print("[INFO] 再検出したポート: %s" % port)
    else:
        print("[INFO] 基地局設定をスキップします（設定済み前提。--lat/--lon/--alt で設定可能）")

    logger = RtcmFrameLogger(log_dir=args.log_dir, tag=args.tag)

    sock = None
    target_host = None
    if not args.no_udp:
        try:
            target_host = resolve_host(args.host)
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            print("[INFO] UDP送信先: %s:%d" % (target_host, args.port))
        except Exception as e:
            print("[WARN] ホスト '%s' の解決に失敗（UDP送信を無効化）: %s" % (args.host, e))
            target_host = None

    print("[INFO] 基地局F9P: %s @ %d bps" % (port, args.baudrate))
    print("[INFO] Ctrl+C で終了")
    print("=" * 60)

    ser = serial.Serial(port, args.baudrate, timeout=1.0)
    buffer = bytearray()
    frames = 0
    last_report = time.time()
    last_frame_time = time.time()

    try:
        while True:
            data = ser.read(4096)
            if data:
                buffer.extend(data)
                for frame in extract_rtcm_frames(buffer):
                    logger.write(frame)
                    if sock is not None and target_host:
                        sock.sendto(frame, (target_host, args.port))
                    frames += 1
                    last_frame_time = time.time()

            if time.time() - last_report >= 5:
                elapsed = time.time() - last_frame_time
                status = "OK" if elapsed < 3 else "RTCM未受信"
                print("[INFO] frames=%d bytes=%d 最終受信から%.1f秒 (%s)"
                      % (frames, logger.total_bytes, elapsed, status))
                last_report = time.time()
    except KeyboardInterrupt:
        print("\n[INFO] Ctrl+C で終了します")
    finally:
        logger.summary()
        logger.close()
        try:
            ser.close()
        except Exception:
            pass
        if sock is not None:
            sock.close()
        print("[INFO] 終了（合計 frames=%d）" % frames)


if __name__ == "__main__":
    main()
