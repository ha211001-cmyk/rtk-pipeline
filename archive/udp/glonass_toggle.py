#!/usr/bin/env python3
"""glonass_toggle.py — 基地局 F9P の GLONASS RTCM 出力を一時 ON/OFF する

RTK が FLOAT のまま FIX しない原因切り分け用。
GLONASS（RTCM 1087: MSM7 観測値）と GLONASS バイアス（1230）の出力を
RAM のみ（Flash 非保存）で切り替えます。

- デフォルトは RAM のみ書き込み（layers=1）。電源再投入で自動的に元へ戻る。
- --save を付けると Flash にも保存（電源 OFF 後も保持）。

使い方:
    python3 glonass_toggle.py --off                     # GLONASS を一時 OFF
    python3 glonass_toggle.py --on                      # GLONASS を ON に戻す
    python3 glonass_toggle.py --off --serial /dev/cu.usbmodem312301

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

# GLONASS 関連の RTCM 出力キー（USB と UART1 の両方）
_GLONASS_KEYS = [
    "CFG_MSGOUT_RTCM_3X_TYPE1087_USB",    # GLO MSM7 (観測値)
    "CFG_MSGOUT_RTCM_3X_TYPE1087_UART1",
    "CFG_MSGOUT_RTCM_3X_TYPE1230_USB",    # GLO コードフェーズバイアス
    "CFG_MSGOUT_RTCM_3X_TYPE1230_UART1",
]

# 状態確認する他システムキー（OFF 操作で消えていないことの確認用）
_OTHER_KEYS = [
    "CFG_MSGOUT_RTCM_3X_TYPE1006_USB",
    "CFG_MSGOUT_RTCM_3X_TYPE1077_USB",
    "CFG_MSGOUT_RTCM_3X_TYPE1097_USB",
    "CFG_MSGOUT_RTCM_3X_TYPE1127_USB",
]

_NAMES = {
    "1087": "GLO MSM7",
    "1230": "GLO Bias",
    "1006": "Station XYZ",
    "1077": "GPS MSM7",
    "1097": "GAL MSM7",
    "1127": "BDS MSM7",
}

LAYER_RAM = 1          # RAM のみ（電源再投入で復元）
LAYER_ALL = 7          # RAM + BBR + FLASH（永続化）


def _key_tag(key: str) -> str:
    """キー文字列から '1087'/'1230' のようなタグを取り出す"""
    return key.replace("CFG_MSGOUT_RTCM_3X_TYPE", "").replace("_USB", "").replace("_UART1", "")


def detect_serial_port() -> Optional[str]:
    """基地局 F9P のシリアルポートを自動検出する"""
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


def _send_cfg(ser: serial.Serial, keys: List[str], val: int, layers: int) -> None:
    """CFG-VALSET で keys の値を val に設定する"""
    cfg = [(k, val) for k in keys]
    msg = UBXMessage.config_set(layers, 0, cfg)
    ser.write(msg.serialize())
    ser.flush()
    time.sleep(0.2)


def _read_cfg(ser: serial.Serial, keys: List[str]) -> dict:
    """CFG-VALGET で keys の現在値を読み取る"""
    ser.reset_input_buffer()
    msg = UBXMessage.config_poll(0, 0, keys)
    ser.write(msg.serialize())
    ser.flush()

    result = {}
    deadline = time.time() + 2.0
    ubr = UBXReader(ser, protfilter=3)  # UBX のみ
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
        description="基地局 F9P の GLONASS RTCM 出力（1087/1230）を一時 ON/OFF する",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--off", action="store_true", help="GLONASS 出力を OFF にする")
    group.add_argument("--on", action="store_true", help="GLONASS 出力を ON に戻す")
    p.add_argument("--serial", default=None, help="基地局 F9P のシリアルポート（省略時は自動検出）")
    p.add_argument("--baudrate", type=int, default=38400, help="シリアルボーレート")
    p.add_argument("--save", action="store_true",
                   help="Flash にも保存する（電源 OFF 後も保持。既定は RAM のみ）")
    args = p.parse_args()

    port = args.serial or detect_serial_port()
    if not port:
        print("[ERROR] 基地局 F9P のシリアルポートを検出できませんでした")
        print("        --serial /dev/cu.usbmodemXXXX で明示指定してください")
        sys.exit(1)

    val = 0 if args.off else 1
    layers = LAYER_ALL if args.save else LAYER_RAM
    action = "OFF" if args.off else "ON"

    print("=" * 60)
    print(f"GLONASS RTCM 出力を {action} に設定します")
    print(f"  シリアル: {port} @ {args.baudrate} bps")
    print(f"  保存先: {'RAM + FLASH（永続）' if args.save else 'RAM のみ（電源再投入で復元）'}")
    print("=" * 60)

    ser = serial.Serial(port, args.baudrate, timeout=1.0)
    time.sleep(0.3)

    try:
        _send_cfg(ser, _GLONASS_KEYS, val, layers)
        print(f"[INFO] 設定を送信しました（{len(_GLONASS_KEYS)} キー → {val}）")

        check_keys = _GLONASS_KEYS + _OTHER_KEYS
        current = _read_cfg(ser, check_keys)

        print("\n--- 設定確認 (CFG-VALGET) ---")
        all_ok = True
        for k in check_keys:
            tag = _key_tag(k)
            name = _NAMES.get(tag, tag)
            cur = current.get(k)
            if cur is None:
                print(f"  {tag:6s} {name:<14s} = ?   [読取失敗]")
                all_ok = False
                continue
            if k in _GLONASS_KEYS:
                ok = (cur == val)
            else:
                ok = (cur == 1)
            mark = "OK" if ok else "NG!"
            all_ok = all_ok and ok
            print(f"  {tag:6s} {name:<14s} = {cur}   [{mark}]")

        print("\n" + ("[OK] 設定完了" if all_ok else "[WARN] 一部 NG（上記確認）"))
        if args.off and not args.save:
            print("[INFO] GLONASS は RAM のみで OFF にしました。")
            print("       復元方法: 電源再投入 または 'python3 glonass_toggle.py --on'")
    finally:
        ser.close()

    print("[INFO] ポートを閉じました")


if __name__ == "__main__":
    main()
