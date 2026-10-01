#!/usr/bin/env python3
"""
set_rtcm_rate.py — 基地局 F9P の RTCM 出力レート（測定レート）を変更する

基地局 F9P の CFG_RATE_MEAS（測定レート、ms）を変更して RTCM 出力を 1Hz などに変更する。
RTCM の MSGOUT キーは 1（毎エポック）のままなので、CFG_RATE_MEAS を変えるだけで
全 RTCM（1006/1077/1097/1127 等）の出力レートが変わる。

- 既定は RAM のみ書き込み（layers=1）。電源再投入で元に戻る。
- --save を付けると Flash にも保存。

使い方:
    python3 set_rtcm_rate.py --rate 1              # 1Hz に変更（RAM のみ）
    python3 set_rtcm_rate.py --rate 5              # 5Hz に変更
    python3 set_rtcm_rate.py --restore 200         # 200ms(=5Hz) へ復元
    python3 set_rtcm_rate.py --rate 1 --save       # Flash にも保存

依存: pip install pyserial pyubx2
"""

import argparse
import glob
import sys
import time
from typing import List, Optional

import serial

try:
    from pyubx2 import UBXMessage, UBXReader
except ImportError:
    print("[ERROR] pyubx2 がインストールされていません。 pip install pyubx2")
    sys.exit(1)

LAYER_RAM = 1          # RAM のみ（電源再投入で復元）
LAYER_ALL = 7          # RAM + BBR + FLASH（永続化）


def _hz(ms) -> str:
    """ミリ秒を Hz 表記にする。"""
    if ms in (None, 0):
        return "?"
    return "%.2f Hz" % (1000.0 / ms)


def detect_serial_port() -> Optional[str]:
    """基地局 F9P のシリアルポートを自動検出する。"""
    candidates: List[str] = []
    candidates += sorted(glob.glob("/dev/cu.usbmodem*"))
    candidates += sorted(glob.glob("/dev/tty.usbmodem*"))
    candidates += sorted(glob.glob("/dev/ttyACM*"))
    candidates += sorted(glob.glob("/dev/ttyUSB*"))
    if not candidates:
        return None
    if len(candidates) > 1:
        print("[WARN] シリアルポート候補が複数あります:")
        for c in candidates:
            print("         - %s" % c)
        print("[WARN] 先頭の %s を使用します（--serial で指定可能）" % candidates[0])
    return candidates[0]


def _read_cfg(ser: serial.Serial, keys: List[str]) -> dict:
    """CFG-VALGET で keys の現在値を読み取る。"""
    ser.reset_input_buffer()
    msg = UBXMessage.config_poll(0, 0, keys)
    ser.write(msg.serialize())
    ser.flush()

    result = {}
    deadline = time.time() + 2.0
    ubr = UBXReader(ser)
    while time.time() < deadline:
        try:
            raw, parsed = ubr.read()
            if parsed and parsed.identity == "CFG-VALGET":
                for k in keys:
                    try:
                        result[k] = getattr(parsed, k)
                    except AttributeError:
                        result[k] = None
                return result
        except Exception:
            time.sleep(0.05)
    return result


def main() -> None:
    p = argparse.ArgumentParser(
        description="基地局 F9P の RTCM 出力レートを変更",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--rate", type=float, help="目標レート（Hz）。例: 1")
    g.add_argument("--restore", type=int, help="CFG_RATE_MEAS の値(ms)へ復元。例: 200（=5Hz）")
    p.add_argument("--serial", default=None, help="基地局 F9P のシリアルポート（省略時は自動検出）")
    p.add_argument("--baudrate", type=int, default=38400, help="シリアルボーレート")
    p.add_argument("--save", action="store_true", help="Flash にも保存する（既定は RAM のみ）")
    args = p.parse_args()

    port = args.serial or detect_serial_port()
    if not port:
        print("[ERROR] 基地局 F9P のシリアルポートを検出できませんでした")
        print("        --serial /dev/cu.usbmodemXXXX で明示指定してください")
        sys.exit(1)

    if args.rate is not None:
        if args.rate <= 0:
            print("[ERROR] --rate は正の値で指定してください")
            sys.exit(1)
        target_ms = int(round(1000.0 / args.rate))
    else:
        target_ms = args.restore

    layers = LAYER_ALL if args.save else LAYER_RAM

    print("=" * 60)
    print("基地局 F9P の RTCM 出力レート変更")
    print("  シリアル: %s @ %d bps" % (port, args.baudrate))
    print("  保存先: %s" % ("RAM + FLASH（永続）" if args.save else "RAM のみ（電源再投入で復元）"))
    print("=" * 60)

    ser = serial.Serial(port, args.baudrate, timeout=1.0)
    time.sleep(0.3)

    try:
        # 現在値
        current = _read_cfg(ser, ["CFG_RATE_MEAS", "CFG_RATE_NAV"])
        cur_meas = current.get("CFG_RATE_MEAS")
        cur_nav = current.get("CFG_RATE_NAV")
        print("\n--- 現在値 ---")
        print("  CFG_RATE_MEAS = %s ms（%s）" % (cur_meas, _hz(cur_meas)))
        print("  CFG_RATE_NAV  = %s" % cur_nav)

        # 設定
        ser.write(UBXMessage.config_set(layers, 0, [("CFG_RATE_MEAS", target_ms)]).serialize())
        ser.flush()
        time.sleep(0.3)
        print("\n[INFO] CFG_RATE_MEAS を %d ms（%s）に設定しました" % (target_ms, _hz(target_ms)))

        # 検証
        after = _read_cfg(ser, ["CFG_RATE_MEAS"])
        new_meas = after.get("CFG_RATE_MEAS")
        print("\n--- 設定後 ---")
        if new_meas is not None:
            ok = (int(new_meas) == target_ms)
            print("  CFG_RATE_MEAS = %s ms（%s）  [%s]"
                  % (new_meas, _hz(new_meas), "OK" if ok else "NG!"))
        else:
            print("  [WARN] 設定後の値が確認できませんでした")

        print("\n" + "=" * 60)
        if args.rate is not None:
            print("[OK] %.2f Hz に設定完了（RAM のみ）" % args.rate)
            print("     復元方法: python3 set_rtcm_rate.py --restore %s" % cur_meas)
        else:
            print("[OK] %d ms に復元完了" % target_ms)
    finally:
        ser.close()

    print("[INFO] ポートを閉じました")


if __name__ == "__main__":
    main()
