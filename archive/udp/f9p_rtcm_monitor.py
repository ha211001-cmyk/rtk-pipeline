#!/usr/bin/env python3
"""
F9P RTCM受信モニター (DroneCAN tunnel経由)

Pixhawk の USB(MAVLink) 経由で CAN にアクセスし、DroneCAN の
uavcan.tunnel.Targetted (target_node_id=125, serial_id=0) で運ばれる
F9P 内部 UART1 のバイト列から UBX-RXM-RTCM (class=0x02, id=0x32) を抽出し、
RTCM メッセージ種別(msgType)ごとの受信回数・CRC失敗・used分布を集計して、
「受信」「CRC確認」「使用」の3軸で F9P の RTCM 利用状況を確定します。

前提:
    - MAVCAN ドライバが起動時に MAV_CMD_CAN_FORWARD を自動で送信し
      CAN_FRAME 転送を有効化する(ドライバ内部io_processで1Hz送信)。
    - UBX-RXM-RTCM はポーリング不要で、RTCM 受信のたびに F9P が自動出力する。
    - 読み取り専用のため UART Locking は行わない。ただし Mission Planner 等が
      同じポートを同時に使っていないことを事前に確認すること。

使用例:
    source ~/Mavlink_venv/bin/activate
    python3 f9p_rtcm_monitor.py --monitor-rtcm 60
    python3 f9p_rtcm_monitor.py --monitor-rtcm 60 --port /dev/cu.usbmodem103 --target-node 125
"""

import argparse
import struct
import sys
import time
from collections import defaultdict

try:
    import dronecan
    from dronecan import uavcan
except ImportError:
    sys.exit("エラー: dronecan がインストールされていません。\n"
             "  source ~/Mavlink_venv/bin/activate")

# ---- 定数 ----
UBX_SYNC_1 = 0xB5
UBX_SYNC_2 = 0x62

# UBX-RXM-RTCM: class=0x02, id=0x32
UBX_RXM_RTCM_CLASS = 0x02
UBX_RXM_RTCM_ID = 0x32

# RTCM メッセージ種別(1000番台の一般RTK補正メッセージ)。一覧表示の順序用。
KNOWN_RTCM_MSG_TYPES = [
    1001, 1002, 1003, 1004, 1005, 1006, 1007, 1008, 1009, 1010,
    1011, 1012, 1013, 1019, 1020, 1033,
    1074, 1075, 1077, 1084, 1085, 1087, 1094, 1095, 1097,
    1117, 1124, 1127, 1230,
]


def ubx_checksum(data: bytes) -> bytes:
    """UBX チェックサム (CLASS..PAYLOAD に対して計算) を 2 バイトで返す。"""
    ck_a = 0
    ck_b = 0
    for b in data:
        ck_a = (ck_a + b) & 0xFF
        ck_b = (ck_b + ck_a) & 0xFF
    return bytes((ck_a, ck_b))


class UbxParser:
    """
    UBX バイト列を蓄積しつつ、完全なフレームを (cls, mid, payload) として
    取り出す増分パーサー。フレームが tunnel メッセージの境界で分割されても
    正しく組み立てる。

    フレーム構造:
        sync1 sync2 cls mid len_lo len_hi payload[0..len-1] ck_a ck_b
    """

    def __init__(self):
        self.buf = bytearray()

    def feed(self, data: bytes) -> list:
        """データを追加し、完全に揃った有効フレームのリストを返す。"""
        self.buf.extend(data)
        frames = []

        while True:
            idx = self.buf.find(b"\xb5\x62")
            if idx < 0:
                # sync が見つからない → 次回に先頭 sync が分割される場合に備え1バイト残す
                if len(self.buf) > 1:
                    del self.buf[:-1]
                break

            if idx > 0:
                # sync 前のゴミを破棄して再走査
                del self.buf[:idx]
                continue

            # idx == 0: ヘッダ最低6バイトが必要
            if len(self.buf) < 6:
                break

            cls = self.buf[2]
            mid = self.buf[3]
            length = self.buf[4] | (self.buf[5] << 8)

            total = 6 + length + 2
            if total > 8192:
                # 明らかに不正なフレーム長 → sync 2バイトを捨てて再同期
                del self.buf[:2]
                continue

            if len(self.buf) < total:
                # フレーム未完成 → 次のデータを待つ
                break

            payload = bytes(self.buf[6:6 + length])
            header = bytes((cls, mid, length & 0xFF, (length >> 8) & 0xFF))
            calc = ubx_checksum(header + payload)
            if calc[0] == self.buf[6 + length] and calc[1] == self.buf[6 + length + 1]:
                frames.append((cls, mid, payload))

            del self.buf[:total]

        return frames


def parse_rxm_rtcm(payload: bytes):
    """
    UBX-RXM-RTCM ペイロードを解析し、 (msgType, msgUsed) を返す。

    ペイロード構成:
        offset 0: version        U1
        offset 1: flags          X1  (bit0=crcFailed, bit1-2=msgUsed)
        offset 2: subType        U2
        offset 4: refStation     U2
        offset 6: msgType        U2
    msgUsed: 0=不明, 1=未使用, 2=使用済み
    """
    if len(payload) < 8:
        return None

    version = payload[0]
    flags = payload[1]
    _, ref_station, msg_type = struct.unpack("<HHH", payload[2:8])

    msg_used = (flags >> 1) & 0x03

    return {
        "version": version,
        "flags": flags,
        "crc_failed": bool(flags & 0x01),
        "msg_used": msg_used,
        "sub_type": payload[2] | (payload[3] << 8),
        "ref_station": ref_station,
        "msg_type": msg_type,
    }


MSG_USED_NAMES = {
    0: "不明",
    1: "未使用",
    2: "使用済み",
}


def format_msg_used(msg_used: int) -> str:
    return MSG_USED_NAMES.get(msg_used, f"未知({msg_used})")


def new_rtcm_stat():
    """msgType ごとの集計辞書を新規作成して返す。"""
    return {
        "count": 0,            # 受信回数
        "crc_failed_count": 0,  # CRC失敗回数
        "used_counts": {0: 0, 1: 0, 2: 0},  # msgUsed別件数(0=不明,1=未使用,2=使用済み)
        "ref_station": None,    # 基準局ID(最後の値)
    }


def add_rxm_rtcm_stat(stats, info):
    """RXM-RTCM 1件分の info を stats(msgTypeごとの集計辞書) に加算する。"""
    mt = info["msg_type"]
    st = stats[mt]
    st["count"] += 1
    if info["crc_failed"]:
        st["crc_failed_count"] += 1
    # msgUsed: 0=不明, 1=未使用, 2=使用済み, 3=予約(ここでは不明扱い)
    mu = info["msg_used"]
    if mu not in (0, 1, 2):
        mu = 0
    st["used_counts"][mu] += 1
    st["ref_station"] = info["ref_station"]
    return st


def compute_rtcm_totals(stats):
    """stats から全体合計 (総受信件数, 総CRC失敗件数, used分布合計) を返す。"""
    total_count = sum(st["count"] for st in stats.values())
    total_crc_failed = sum(st["crc_failed_count"] for st in stats.values())
    total_used = {0: 0, 1: 0, 2: 0}
    for st in stats.values():
        for k in (0, 1, 2):
            total_used[k] += st["used_counts"][k]
    return total_count, total_crc_failed, total_used


def judge_rtcm(total_count, total_crc_failed, total_used):
    """
    受信 / CRC確認 / 使用 の3軸で最終判定し、結果辞書を返す。

    - 受信    : 総受信件数 > 0 なら OK、0 なら NG
    - CRC確認 : 総CRC失敗件数 = 0 なら OK、> 0 なら NG
    - 使用    : used=2 が受信件数の過半(過半数を超える)を占めれば OK、それ以外 NG
    """
    rx_ok = total_count > 0
    crc_ok = total_crc_failed == 0
    crc_fail_rate = (total_crc_failed / total_count * 100.0) if total_count > 0 else 0.0

    # 過半 = 過半数を超える (used=2 が全受信件数の半分より多い)
    used_ok = total_used[2] * 2 > total_count
    used_pct = (total_used[2] / total_count * 100.0) if total_count > 0 else 0.0

    all_ok = rx_ok and crc_ok and used_ok
    ng_axes = []
    if not rx_ok:
        ng_axes.append("受信")
    if not crc_ok:
        ng_axes.append("CRC確認")
    if not used_ok:
        ng_axes.append("使用")

    return {
        "rx_ok": rx_ok,
        "crc_ok": crc_ok,
        "used_ok": used_ok,
        "crc_fail_rate": crc_fail_rate,
        "used_pct": used_pct,
        "all_ok": all_ok,
        "ng_axes": ng_axes,
    }


def main():
    parser = argparse.ArgumentParser(
        description="DroneCAN tunnel 経由で F9P の UBX-RXM-RTCM を集計する"
    )
    parser.add_argument(
        "--monitor-rtcm",
        type=float,
        required=True,
        help="受信を継続する秒数(例: 30〜60)",
    )
    parser.add_argument(
        "--port",
        default="/dev/cu.usbmodem101",
        help="Pixhawk の MAVLink USB ポート (default: /dev/cu.usbmodem101)",
    )
    parser.add_argument(
        "--target-node",
        type=int,
        default=125,
        help="F9P/GPS の DroneCAN node_id (default: 125)",
    )
    parser.add_argument(
        "--serial-id",
        type=int,
        default=0,
        help="uavcan.tunnel.Targetted の serial_id (default: 0)",
    )
    parser.add_argument(
        "--local-node",
        type=int,
        default=100,
        help="本スクリプト自身の DroneCAN node_id (default: 100)",
    )
    parser.add_argument(
        "--bus-number",
        type=int,
        default=1,
        help="MAVCAN が接続する CAN バス番号(1始まり, default: 1)",
    )
    parser.add_argument(
        "--mavlink-target-system",
        type=int,
        default=0,
        help="MAVLINK target_system (0=自動, default: 0)",
    )
    args = parser.parse_args()

    monitor_sec = args.monitor_rtcm
    if monitor_sec <= 0:
        parser.error("--monitor-rtcm は正の秒数で指定してください")

    print("=" * 66)
    print("F9P RTCM 受信モニター (UBX-RXM-RTCM 集計)")
    print("=" * 66)
    print(f"  Port                : {args.port}")
    print(f"  DroneCAN node_id    : mavcan:{args.port} (local={args.local_node})")
    print(f"  CAN bus number      : {args.bus_number}")
    print(f"  F9P target_node_id  : {args.target_node}")
    print(f"  tunnel serial_id    : {args.serial_id}")
    print(f"  監視時間            : {monitor_sec:g} 秒")
    print("=" * 66)

    # MAVCAN ドライバは起動時から CAN_FORWARD(コマンドID 32000) を1Hzで
    # 自動送信して CAN_FRAME 転送を有効化する。
    print("\n[接続] MAVLink USB 経由で CAN に接続しています…")
    print("        (ドライバが MAV_CMD_CAN_FORWARD を自動送信します)")

    try:
        node = dronecan.make_node(
            f"mavcan:{args.port}",
            node_id=args.local_node,
            bus_number=args.bus_number,
            mavlink_target_system=args.mavlink_target_system,
        )
    except Exception as e:
        sys.exit(f"[エラー] DroneCAN ノードの初期化に失敗: {e}")

    ubx_parser = UbxParser()
    # 集計: msgType -> {count, crc_failed_count, used_counts, ref_station}
    stats = defaultdict(new_rtcm_stat)
    tunnel_msg_count = 0
    rx_byte_count = 0
    rxm_rtcm_count = 0

    def on_tunnel(event):
        nonlocal tunnel_msg_count, rx_byte_count, rxm_rtcm_count
        msg = event.message
        # 対象ノードと serial_id が一致するものだけ処理
        if getattr(msg, "target_node", None) != args.target_node:
            return
        if getattr(msg, "serial_id", None) != args.serial_id:
            return

        tunnel_msg_count += 1

        # buffer は dronecan.transport.ArrayValue。items が生バイト列(list[int])。
        buf = getattr(msg, "buffer", None)
        items = getattr(buf, "items", None) if buf is not None else None
        if not items:
            return

        raw = bytes(items)
        rx_byte_count += len(raw)

        for cls, mid, payload in ubx_parser.feed(raw):
            if cls == UBX_RXM_RTCM_CLASS and mid == UBX_RXM_RTCM_ID:
                info = parse_rxm_rtcm(payload)
                if info is None:
                    continue
                rxm_rtcm_count += 1
                add_rxm_rtcm_stat(stats, info)

    node.add_handler(uavcan.tunnel.Targetted, on_tunnel)

    print("\n[受信] UBX-RXM-RTCM を待機しています…")
    print("        (中断する場合は Ctrl+C)\n")

    start = time.monotonic()
    try:
        while time.monotonic() - start < monitor_sec:
            node.spin(timeout=0.1)
    except KeyboardInterrupt:
        print("\n[中断] キーボード割り込みで受信を終了します。")

    # ---- 結果出力 ----
    print("\n" + "=" * 66)
    print("監視結果サマリー")
    print("=" * 66)
    print(f"  監視時間            : {monitor_sec:g} 秒")
    print(f"  受信 tunnel メッセージ数 : {tunnel_msg_count}")
    print(f"  受信バイト数        : {rx_byte_count}")
    print(f"  UBX-RXM-RTCM 件数   : {rxm_rtcm_count}")
    print("=" * 66)

    # 出現した msgType を既知リスト順 → その他昇順で表示
    present = set(stats.keys())
    display_order = [mt for mt in KNOWN_RTCM_MSG_TYPES if mt in present]
    display_order += sorted(mt for mt in present if mt not in KNOWN_RTCM_MSG_TYPES)

    # ---- msgType 別集計テーブル ----
    print("\n【msgType 別 集計】(used=0:不明 / 1:未使用 / 2:使用済み)")
    header = (
        f"{'msgType':>8}  {'受信回数':>6}  {'CRC失敗':>7}  "
        f"{'used=2':>6}  {'used=1':>6}  {'used=0':>6}  {'基準局ID':>8}"
    )
    print(header)
    print("-" * len(header))
    for mt in display_order:
        st = stats[mt]
        uc = st["used_counts"]
        ref_station = st["ref_station"] if st["ref_station"] is not None else "-"
        print(
            f"{mt:>8}  {st['count']:>6}  {st['crc_failed_count']:>7}  "
            f"{uc[2]:>6}  {uc[1]:>6}  {uc[0]:>6}  {ref_station:>8}"
        )

    # ---- 全体合計行 ----
    total_count, total_crc_failed, total_used = compute_rtcm_totals(stats)
    print("-" * len(header))
    print(
        f"{'(合計)':>8}  {total_count:>6}  {total_crc_failed:>7}  "
        f"{total_used[2]:>6}  {total_used[1]:>6}  {total_used[0]:>6}  {'-':>8}"
    )

    # ---- 最終判定(受信 / CRC確認 / 使用 の3軸) ----
    verdict = judge_rtcm(total_count, total_crc_failed, total_used)
    print("\n【最終判定 (3軸)】")
    print(
        f"  受信     : {'OK' if verdict['rx_ok'] else 'NG'}  "
        f"(総受信件数: {total_count} 件)"
    )
    print(
        f"  CRC確認  : {'OK' if verdict['crc_ok'] else 'NG'}  "
        f"(CRC失敗: {total_crc_failed} 件 / 失敗率: {verdict['crc_fail_rate']:.1f}%)"
    )
    print(
        f"  使用     : {'OK' if verdict['used_ok'] else 'NG'}  "
        f"(used=2: {total_used[2]} 件({verdict['used_pct']:.1f}%) / "
        f"used=1: {total_used[1]} 件 / used=0: {total_used[0]} 件)"
    )
    if verdict["all_ok"]:
        print("  判定     : F9PはRTCMを受信・CRC確認・使用していると確定")
    else:
        print(f"  判定     : NG (該当軸: {', '.join(verdict['ng_axes'])})")

    # 参考: 対象 msgType で受信が無かった既知メッセージ種別
    missing = [mt for mt in KNOWN_RTCM_MSG_TYPES if mt not in present]
    if missing:
        print("\n【確認候補メッセージ種別(受信なし)】")
        print("  " + ", ".join(str(mt) for mt in missing))
    else:
        print("\n【確認候補メッセージ種別(受信なし)】 なし")

    try:
        node.close()
    except Exception:
        pass


if __name__ == "__main__":
    main()