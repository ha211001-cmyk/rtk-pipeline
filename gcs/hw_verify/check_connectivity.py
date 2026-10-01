#!/usr/bin/env python3
"""check_connectivity.py — 物理実地検証前の疎通確認ヘルパー

①②③監視モジュール（TCP 対応版）＋ runner.py の物理ハードウェア実地検証に先立ち、
下記を一括で確認します。

  1. 機体 Raspberry Pi 5 への ICMP 疎通（ping）
  2. 機体 RPi5 の DroneCAN Serial Forwarding ポート（既定 5001）への TCP 到達
  3. 基地局 F9P（GCS PC へ USB 直結）のシリアルポート認識

標準ライブラリのみで動作します（外部依存なし）。

使い方:
    python3 gcs/hw_verify/check_connectivity.py --host 192.168.11.50
    python3 gcs/hw_verify/check_connectivity.py --serial-only
    python3 gcs/hw_verify/check_connectivity.py --self-test
"""

from __future__ import annotations

import argparse
import glob
import socket
import subprocess
import sys
import threading
from typing import List, Optional


# ---------------------------------------------------------------------------
# シリアルポート認識（基地局 F9P の USB シリアル）
# ---------------------------------------------------------------------------
def list_serial_ports() -> List[str]:
    """認識されているシリアルポートのデバイスパス一覧を返す。"""
    if sys.platform.startswith("win"):
        return []
    patterns = [
        "/dev/cu.usbmodem*",   # macOS: USB-シリアル（F9P 等）
        "/dev/tty.usbmodem*",  # macOS: 別シンボリックリンク
        "/dev/ttyACM*",        # Linux: USB CDC-ACM
        "/dev/ttyUSB*",        # Linux: USB-シリアル変換
    ]
    found: List[str] = []
    for pat in patterns:
        found.extend(sorted(glob.glob(pat)))
    return found


# ---------------------------------------------------------------------------
# ping（ICMP 疎通）
# ---------------------------------------------------------------------------
def ping(host: str, timeout_sec: float = 2.0) -> bool:
    """host への ICMP 疎通を確認する（終了コード 0 を成功とみなす）。"""
    if sys.platform.startswith("win"):
        cmd = ["ping", "-n", "1", "-w", str(int(timeout_sec * 1000)), host]
    else:
        cmd = ["ping", "-c", "1", "-W", str(int(timeout_sec)), host]
    try:
        proc = subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=timeout_sec + 5,
        )
        return proc.returncode == 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# TCP ポート到達確認
# ---------------------------------------------------------------------------
def check_tcp(host: str, port: int, timeout_sec: float = 3.0) -> Optional[str]:
    """host:port への TCP 接続を試み、成功なら None、失敗なら理由文字列を返す。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout_sec)
    try:
        sock.connect((host, port))
        return None
    except socket.timeout:
        return "タイムアウト（%g 秒以内に応答なし）" % timeout_sec
    except ConnectionRefusedError:
        return "接続拒否（ポートが待ち受けていない／サービス未起動）"
    except OSError as e:
        return "OS エラー: %s" % e
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# 自己検証用のローカル TCP リスナー（--self-test 用）
# ---------------------------------------------------------------------------
def _run_self_test() -> int:
    """ローカルに一時 TCP リスナーを立てて、本ツール自体の動作を検証する。"""
    host = "127.0.0.1"
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind((host, 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def _serve() -> None:
        try:
            conn, _ = srv.accept()
            conn.close()
        except OSError:
            pass

    t = threading.Thread(target=_serve, daemon=True)
    t.start()

    ok = True
    print("[self-test] ping(127.0.0.1) = %s" % ping(host))
    err = check_tcp(host, port)
    print("[self-test] TCP 127.0.0.1:%d = %s" % (port, "OK" if err is None else err))
    ok = ok and (err is None)
    print("[self-test] シリアルポート検出数 = %d" % len(list_serial_ports()))

    srv.close()
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="物理実地検証前の疎通確認（ping / TCP ポート / シリアル認識）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--host", default=None,
                   help="機体 RPi5 の IP アドレスまたはホスト名")
    p.add_argument("--port", type=int, default=5001,
                   help="DroneCAN Serial Forwarding の TCP ポート")
    p.add_argument("--ping-timeout", type=float, default=2.0,
                   help="ping のタイムアウト [秒]")
    p.add_argument("--tcp-timeout", type=float, default=3.0,
                   help="TCP 接続のタイムアウト [秒]")
    p.add_argument("--skip-ping", action="store_true", help="ping を省略")
    p.add_argument("--skip-tcp", action="store_true", help="TCP ポート確認を省略")
    p.add_argument("--serial-only", action="store_true",
                   help="シリアルポート認識のみ実行")
    p.add_argument("--self-test", action="store_true",
                   help="実機なしの自己検証（ローカル TCP リスナーで動作確認）")
    args = p.parse_args(argv)

    if args.self_test:
        return _run_self_test()

    ports = list_serial_ports()

    if args.serial_only:
        print("== 基地局 F9P のシリアルポート認識 ==")
        if ports:
            for port in ports:
                print("  [OK] %s" % port)
            print("  認識されたポート数: %d" % len(ports))
        else:
            print("  [NG] シリアルポートが見つかりません。")
            print("   → USB 接続と `ls /dev/cu.usbmodem* /dev/ttyACM*` を確認してください。")
        return 0 if ports else 1

    host = args.host
    if not host:
        print("[ERROR] --host を指定してください（例: --host 192.168.11.50）")
        print("        --serial-only を使うとシリアル認識のみ確認できます。")
        return 2

    exit_code = 0
    print("=" * 62)
    print("物理実地検証前 疎通確認")
    print("  機体 RPi5: %s (TCP port %d)" % (host, args.port))
    print("=" * 62)

    if not args.skip_ping:
        ok = ping(host, args.ping_timeout)
        print("\n[1] ICMP 疎通（ping %s）: %s" % (host, "OK" if ok else "NG"))
        if not ok:
            print("    → 同一 Wi-Fi ネットワークに接続されているか、IP を確認してください。")
            exit_code = 1

    if not args.skip_tcp:
        err = check_tcp(host, args.port, args.tcp_timeout)
        print("\n[2] TCP ポート到達（%s:%d）: %s"
              % (host, args.port, "OK" if err is None else "NG (%s)" % err))
        if err is not None:
            print("    → 機体側で DroneCAN Serial Forwarding サービス（TCP:%d）が"
                  "起動しているか確認してください。" % args.port)
            exit_code = 1

    print("\n[3] 基地局 F9P のシリアルポート認識:")
    if ports:
        for port in ports:
            print("    [OK] %s" % port)
        print("    認識されたポート数: %d" % len(ports))
    else:
        print("    [NG] シリアルポートが見つかりません。")
        print("     → 基地局 F9P を GCS PC へ USB 直結し、`ls /dev/cu.usbmodem* /dev/ttyACM*` を確認してください。")
        exit_code = 1

    print("\n" + "=" * 62)
    print("結果: %s" % ("全項目 OK" if exit_code == 0 else "要確認（上記 NG 項目を解消してください）"))
    print("=" * 62)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())

