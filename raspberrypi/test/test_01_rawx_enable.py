#!/usr/bin/env python3
"""
[PPK テスト Step 1] RXM-RAWX / RXM-SFRBX 有効化 & 受信確認
=============================================================
u-blox F9P は通常 NMEA のみを出力しているが、
後処理RTK (PPK) のためには生観測値 (Raw Measurements) が必要。

必要なメッセージ:
  - UBX-RXM-RAWX  : 疑似距離・搬送波位相・ドップラー (計測値)
  - UBX-RXM-SFRBX : 航法メッセージサブフレーム (軌道情報)

このスクリプトでやること:
  1. CFG-VALSET で上記メッセージを UART1 に対して有効化
  2. 30秒受信して RAWX/SFRBX が届くか確認
  3. ACK/NAK も表示して設定成功/失敗を判定

実行後に設定は RAM のみ (電源断でリセット)。
保存したい場合は SET_LAYER_RAM | SET_LAYER_BBR を使う。

使い方:
  python3 test_01_rawx_enable.py [--port /dev/ttyACM0] [--baud 38400] [--save]
"""

import sys
import time
import argparse
import threading
from collections import defaultdict

try:
    import serial
except ImportError:
    print("Error: pyserial が必要です。  pip install pyserial")
    sys.exit(1)

try:
    from pyubx2 import UBXReader, UBXMessage, UBXMessageError, SET_LAYER_RAM, SET_LAYER_BBR, TXN_NONE, UBX_PROTOCOL, NMEA_PROTOCOL, SET
except ImportError:
    print("Error: pyubx2 が必要です。  pip install pyubx2")
    sys.exit(1)

# ============================================================
# 定数
# ============================================================
SERIAL_PORT  = "/dev/ttyACM0"
BAUD         = 38400
LISTEN_SEC   = 30        # 受信確認の最大待機秒数
RAWX_NEEDED  = 3         # 「成功」とみなす RAWX 受信数

# /dev/ttyACM0 は USB CDC インターフェース → _USB キーを使う
# CFG_USBOUTPROT_UBX: USB ポートに UBX プロトコル出力を有効化
# CFG_MSGOUT_UBX_RXM_RAWX_USB:  RAWX を USB に出力
# CFG_MSGOUT_UBX_RXM_SFRBX_USB: SFRBX を USB に出力
PPK_CFG = [
    ("CFG_USBOUTPROT_UBX",              1),
    ("CFG_MSGOUT_UBX_RXM_RAWX_USB",     1),
    ("CFG_MSGOUT_UBX_RXM_SFRBX_USB",    1),
]


def send_and_wait_ack(ser, msg_bytes, label="", timeout=2.0):
    """コマンドを送信して ACK/NAK を UBXReader で待つ"""
    ser.reset_input_buffer()
    ser.write(msg_bytes)
    ubr = UBXReader(ser, protfilter=UBX_PROTOCOL | NMEA_PROTOCOL)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            raw, parsed = ubr.read()
            if parsed is None:
                continue
            identity = parsed.identity if hasattr(parsed, "identity") else ""
            if identity == "ACK-ACK":
                print(f"  [ACK] {label}")
                return True
            if identity == "ACK-NAK":
                print(f"  [NAK] {label} — 設定が拒否されました")
                return False
        except Exception:
            pass
    print(f"  [TIMEOUT] {label} — ACK を受信できませんでした")
    return False


def enable_rawx(ser, save_to_flash=False):
    """RXM-RAWX と RXM-SFRBX を CFG-VALSET で有効化する"""
    layers = SET_LAYER_RAM
    if save_to_flash:
        layers = SET_LAYER_RAM | SET_LAYER_BBR  # BBR に保存 (電源断でも維持)
        print("  [INFO] BBR (バッテリバックアップRAM) にも保存します")
    else:
        print("  [INFO] RAM のみに設定 (電源断でリセット)")

    msg = UBXMessage.config_set(layers, TXN_NONE, PPK_CFG)
    return send_and_wait_ack(ser, msg.serialize(), label="CFG-VALSET (RXM-RAWX/SFRBX enable)")


def listen_for_rawx(ser, listen_sec=LISTEN_SEC):
    """受信ループで RAWX/SFRBX をカウントする"""
    print(f"\n[受信確認] {listen_sec} 秒間 RAWX/SFRBX を待ちます…")
    # parsebitfield=0: X1型を生バイトとして受け取る
    ubr = UBXReader(ser, protfilter=UBX_PROTOCOL | NMEA_PROTOCOL, parsebitfield=0)
    counts = defaultdict(int)
    deadline = time.time() + listen_sec
    first_rawx = None

    while time.time() < deadline:
        try:
            raw, parsed = ubr.read()
            if parsed is None:
                continue
            identity = parsed.identity if hasattr(parsed, "identity") else str(type(parsed))
            counts[identity] += 1

            if identity == "RXM-RAWX":
                if first_rawx is None:
                    first_rawx = parsed
                    num = getattr(parsed, "numMeas", "?")
                    tow = getattr(parsed, "rcvTow", "?")
                    week = getattr(parsed, "week", "?")
                    print(f"\n  ★ RXM-RAWX 受信! numMeas={num}, TOW={tow:.3f}s, Week={week}")
                if counts["RXM-RAWX"] % 5 == 0:
                    print(f"  RAWX: {counts['RXM-RAWX']} 件  SFRBX: {counts['RXM-SFRBX']} 件  "
                          f"(経過 {int(listen_sec - (deadline - time.time()))}s)")
            elif identity == "RXM-SFRBX":
                if counts["RXM-SFRBX"] == 1:
                    gnssId = getattr(parsed, "gnssId", "?")
                    svId   = getattr(parsed, "svId",   "?")
                    print(f"\n  ★ RXM-SFRBX 受信! gnssId={gnssId}, svId={svId}")

        except KeyboardInterrupt:
            print("\n  Ctrl+C で停止")
            break
        except Exception as e:
            # パースエラーは無視して続行
            pass

    return counts


def main():
    parser = argparse.ArgumentParser(description="PPK Step1: RXM-RAWX/SFRBX 有効化確認")
    parser.add_argument("--port",  default=SERIAL_PORT, help=f"シリアルポート (default: {SERIAL_PORT})")
    parser.add_argument("--baud",  type=int, default=BAUD, help=f"ボーレート (default: {BAUD})")
    parser.add_argument("--save",  action="store_true", help="BBR にも保存する (電源断後も維持)")
    parser.add_argument("--listen", type=int, default=LISTEN_SEC, help=f"受信確認秒数 (default: {LISTEN_SEC})")
    args = parser.parse_args()

    print("=" * 60)
    print("PPK テスト Step 1: RXM-RAWX / RXM-SFRBX 有効化確認")
    print("=" * 60)
    print(f"  ポート : {args.port} @ {args.baud} baud")

    try:
        ser = serial.Serial(args.port, args.baud, timeout=1)
    except serial.SerialException as e:
        print(f"[エラー] シリアルポートを開けません: {e}")
        sys.exit(1)

    print("\n[Step 1] RXM-RAWX / RXM-SFRBX を有効化…")
    ok = enable_rawx(ser, save_to_flash=args.save)
    if not ok:
        print("[警告] 設定コマンドの ACK が取れませんでした。受信確認は続けます。")

    counts = listen_for_rawx(ser, listen_sec=args.listen)

    # --- 結果表示 ---
    print("\n" + "=" * 60)
    print("受信メッセージ集計:")
    for k in sorted(counts):
        print(f"  {k:30s}: {counts[k]:5d} 件")

    rawx_count  = counts.get("RXM-RAWX",  0)
    sfrbx_count = counts.get("RXM-SFRBX", 0)
    print("=" * 60)
    if rawx_count >= RAWX_NEEDED:
        print(f"✅ PASS: RXM-RAWX {rawx_count} 件受信 → PPK ロギングが可能です")
        print("   次のステップ: python3 test_02_rawx_verify.py")
    else:
        print(f"❌ FAIL: RXM-RAWX が {rawx_count} 件しか受信できていません (必要: {RAWX_NEEDED}+)")
        print("   考えられる原因:")
        print("   - F9P の設定が適用されていない")
        print("   - CFG-VALSET が NAK → F9P のファームウェアバージョンを確認")
        print("   - シリアルポートが別のプロセスに使われている")

    ser.close()


if __name__ == "__main__":
    main()
