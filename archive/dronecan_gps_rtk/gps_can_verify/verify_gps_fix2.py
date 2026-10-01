#!/usr/bin/env python3
"""
GPS Fix確認スクリプト（fix状態 詳細表示版）

MAVLinkストリームレートを設定してからGPSデータを受信する。
GPS_RAW_INT + GPS_STATUS メッセージからfix状態・衛星情報を取得し、
リアルタイムでわかりやすく表示する。

使用方法:
    source ~/Mavlink_venv/bin/activate
    python3 verify_gps_fix2.py
"""

import sys
import os
import time
import datetime

# デフォルト接続設定
DEFAULT_PORT = '/dev/ttyAMA0'
DEFAULT_BAUD = 921600
DEFAULT_RTSCTS = True

# pymavlinkのインポート
try:
    from pymavlink import mavutil
except ImportError:
    print("エラー: pymavlinkがインストールされていません")
    print("  source ~/Mavlink_venv/bin/activate")
    sys.exit(1)

# GPS Fix状態定義
GPS_FIX_TYPE = {
    0: "NO_FIX",
    1: "NO_FIX",
    2: "2D_FIX",
    3: "3D_FIX",
    4: "DGPS_FIX",
    5: "RTK_FLOAT",
    6: "RTK_FIXED",
}

# Fix状態に対応するアイコンとANSIカラー
FIX_DISPLAY = {
    0: ("🔴", "NO_FIX",       "\033[31m"),      # 赤
    1: ("🔴", "NO_FIX",       "\033[31m"),      # 赤
    2: ("🟠", "2D_FIX",       "\033[33m"),      # 黄
    3: ("🟡", "3D_FIX",       "\033[32m"),      # 緑
    4: ("🟢", "DGPS_FIX",     "\033[36m"),      # シアン
    5: ("🟣", "RTK_FLOAT",    "\033[35m"),      # マゼンタ
    6: ("⭐", "RTK_FIXED",    "\033[1;32m"),    # 太字緑
}
RESET_COLOR = "\033[0m"


def request_message_interval(master, msg_id, interval_us):
    """
    MAV_CMD_SET_MESSAGE_INTERVALで特定メッセージの送信間隔を設定
    interval_us: マイクロ秒 (例: 100000 = 10Hz)
    """
    master.mav.command_long_send(
        master.target_system,
        master.target_component,
        mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
        0,
        msg_id,
        interval_us,
        0, 0, 0, 0, 0
    )
    time.sleep(0.2)


def request_data_stream(master, stream_id, rate_hz):
    """
    REQUEST_DATA_STREAMでストリームを要求
    """
    master.mav.request_data_stream_send(
        master.target_system,
        master.target_component,
        stream_id,
        rate_hz,
        1  # START
    )
    time.sleep(0.2)


def print_fix_status_bar(fix_type, satellites, lat, lon, alt, eph, epv, vel, cog, last_fix_type):
    """
    リアルタイムステータスバーを表示
    fix状態が変化したらハイライト表示
    """
    icon, status, color = FIX_DISPLAY.get(fix_type, ("❓", f"UNKNOWN({fix_type})", "\033[37m"))

    # fix状態が変化した場合、ハイライト
    changed = (fix_type != last_fix_type)
    change_marker = " ★変化★" if changed else ""

    # ステータスバー
    bar = (
        f"\n{color}"
        f"┌{'─' * 58}┐\n"
        f"│ {icon} GPS FIX ステータス: {status}{change_marker:<8} │\n"
        f"│ 衛星数: {satellites:>3}個  "
        f"| 緯度: {lat:>12.7f}°  "
        f"| 経度: {lon:>12.7f}° │\n"
        f"│ 高度: {alt:>7.1f}m  "
        f"| EPH: {eph:.2f}m  "
        f"| EPV: {epv:.2f}m  "
        f"| 速度: {vel:.2f}m/s │\n"
        f"└{'─' * 58}┘{RESET_COLOR}"
    )
    print(bar)

    # 状態変化時の詳細表示
    if changed:
        print(f"\n  ╔{'═' * 50}╗")
        print(f"  ║  🔄 Fix状態が変化しました！                          ║")
        old_icon, old_status, _ = FIX_DISPLAY.get(last_fix_type, ("❓", f"UNKNOWN({last_fix_type})", ""))
        print(f"  ║  前: {old_icon} {old_status:<20}                        ║")
        print(f"  ║  新: {icon} {status:<20}                        ║")
        print(f"  ╚{'═' * 50}╝")

    return fix_type


def print_satellite_info(msg):
    """
    GPS_STATUSメッセージから衛星ごとの情報を表示
    """
    if not hasattr(msg, 'satellite_info') or msg.satellite_info is None:
        return

    satellites = msg.satellites_visible
    print(f"\n  📡 衛星詳細情報（{satellites}個の衛星を捕捉中）")
    print(f"  {'PRN':>4} {'仰角':>6} {'方位角':>6} {'SNR':>5} {'使用中':>6}")
    print(f"  {'─' * 4} {'─' * 6} {'─' * 6} {'─' * 5} {'─' * 6}")

    used_count = 0
    for sat in msg.satellite_info:
        if sat.satellite_prn == 0:
            continue
        used = "✅" if sat.used else "❌"
        if sat.used:
            used_count += 1
        print(f"  {sat.satellite_prn:>4} {sat.elevation:>5}° {sat.azimuth:>5}° {sat.snr:>4}dB {used:>6}")

    print(f"  ──────────────────────────────")
    print(f"  使用中: {used_count}個 / 捕捉中: {satellites}個")


def main():
    print("\n" + "=" * 60)
    print("GPS Fix確認（fix状態 詳細表示版）")
    print("=" * 60)

    port = DEFAULT_PORT
    baud = DEFAULT_BAUD
    rtscts = DEFAULT_RTSCTS

    print(f"\n📡 接続中: {port} @ {baud}bps (RTS/CTS: {rtscts})")

    try:
        master = mavutil.mavlink_connection(port, baud=baud, rtscts=rtscts)
        master.wait_heartbeat(timeout=10)
        print(f"✅ 接続完了 (システム: {master.target_system}, コンポーネント: {master.target_component})")
    except Exception as e:
        print(f"❌ 接続エラー: {e}")
        sys.exit(1)

    # MAVLinkストリームレート設定
    print("\n📡 MAVLinkストリームレート設定中...")

    # GPS_RAW_INT: 10Hz
    print("  GPS_RAW_INT (ID=24) を10Hzで要求...")
    request_message_interval(master, 24, 100000)

    # GLOBAL_POSITION_INT: 10Hz
    print("  GLOBAL_POSITION_INT (ID=33) を10Hzで要求...")
    request_message_interval(master, 33, 100000)

    # REQUEST_DATA_STREAMでも要求
    print("  REQUEST_DATA_STREAM (GPS) を10Hzで要求...")
    request_data_stream(master, mavutil.mavlink.MAV_DATA_STREAM_POSITION, 10)
    request_data_stream(master, mavutil.mavlink.MAV_DATA_STREAM_EXTRA1, 10)

    # ログファイル準備
    log_dir = os.path.join(os.path.dirname(__file__), 'logs')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"gps_fix2_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")

    with open(log_file, 'w') as f:
        f.write("timestamp,msg_type,fix_type,fix_name,satellites,lat,lon,alt,eph,epv,vel,cog\n")

    print(f"\n📡 GPSデータ受信開始... (Ctrl+Cで停止)")
    print(f"   ログ: {log_file}")
    print("-" * 60)

    gps_raw_count = 0
    global_pos_count = 0
    gps_status_count = 0
    start_time = time.time()
    last_fix_type = -1
    fix_history = []  # fix状態の遷移履歴
    last_status_print_time = 0  # GPS_STATUSの表示間隔制御用

    try:
        while time.time() - start_time < 60:  # 60秒間
            msg = master.recv_match(
                type=['GPS_RAW_INT', 'GLOBAL_POSITION_INT', 'GPS_STATUS', 'HEARTBEAT', 'STATUSTEXT'],
                blocking=True,
                timeout=2.0
            )

            if msg is None:
                elapsed = time.time() - start_time
                print(f"  [{int(elapsed)}秒] メッセージ受信待機中...")
                continue

            msg_type = msg.get_type()

            if msg_type == 'GPS_RAW_INT':
                gps_raw_count += 1
                fix_type = msg.fix_type
                satellites = msg.satellites_visible
                lat = msg.lat / 1e7
                lon = msg.lon / 1e7
                alt = msg.alt / 1000
                eph = msg.eph / 100
                epv = msg.epv / 100
                vel = msg.vel / 100
                cog = msg.cog / 100

                fix_status = GPS_FIX_TYPE.get(fix_type, f"UNKNOWN({fix_type})")

                # fix状態の遷移を記録
                if fix_type != last_fix_type:
                    fix_history.append({
                        'time': datetime.datetime.now().isoformat(),
                        'count': gps_raw_count,
                        'from': last_fix_type,
                        'to': fix_type,
                        'from_name': GPS_FIX_TYPE.get(last_fix_type, f"UNKNOWN({last_fix_type})"),
                        'to_name': fix_status,
                    })

                # リアルタイムステータスバー表示
                last_fix_type = print_fix_status_bar(
                    fix_type, satellites, lat, lon, alt, eph, epv, vel, cog, last_fix_type
                )

                # 警告
                if fix_type < 3:
                    if satellites < 4:
                        print(f"     ⚠️ 衛星数不足（{satellites}個）- 最低4個必要")
                    else:
                        print(f"     ⚠️ Fix未取得（衛星数: {satellites}個）- 空が開けた場所へ移動してください")
                elif satellites < 8:
                    print(f"     💡 衛星数が少なめ（{satellites}個）- 精度向上には8個以上推奨")

                # ログ保存
                with open(log_file, 'a') as f:
                    f.write(f"{datetime.datetime.now().isoformat()},GPS_RAW_INT,{fix_type},{fix_status},{satellites},{lat:.7f},{lon:.7f},{alt:.1f},{eph:.2f},{epv:.2f},{vel:.2f},{cog:.1f}\n")

            elif msg_type == 'GPS_STATUS':
                gps_status_count += 1
                # 衛星詳細情報は5秒に1回表示（情報量が多いため）
                now = time.time()
                if now - last_status_print_time >= 5.0:
                    print_satellite_info(msg)
                    last_status_print_time = now

            elif msg_type == 'GLOBAL_POSITION_INT':
                global_pos_count += 1
                # GLOBAL_POSITION_INTはステータスバーで十分なので簡略表示
                # （必要な場合はコメント解除）
                # lat = msg.lat / 1e7
                # lon = msg.lon / 1e7
                # alt = msg.alt / 1000
                # rel_alt = msg.relative_alt / 1000
                # vx = msg.vx / 100
                # vy = msg.vy / 100
                # vz = msg.vz / 100
                # hdg = msg.hdg / 100
                # print(f"\n  📍 [GLOBAL_POSITION_INT] #{global_pos_count}")
                # print(f"     緯度: {lat:.7f}°  経度: {lon:.7f}°  高度: {alt:.1f}m  方位: {hdg:.1f}°")

            elif msg_type == 'STATUSTEXT':
                text = msg.text.rstrip('\x00')
                print(f"  [STATUSTEXT] {text}")

            time.sleep(0.1)  # 10Hz対応のため短めに

    except KeyboardInterrupt:
        print("\n\n停止しました。")

    # ================================
    # 結果サマリー
    # ================================
    print("\n" + "=" * 60)
    print("  検証結果サマリー")
    print("=" * 60)
    print(f"  GPS_RAW_INT受信数:     {gps_raw_count}")
    print(f"  GPS_STATUS受信数:      {gps_status_count}")
    print(f"  GLOBAL_POSITION_INT受信数: {global_pos_count}")
    print(f"  ログファイル: {log_file}")
    print("=" * 60)

    # Fix状態の遷移履歴
    if fix_history:
        print("\n" + "─" * 60)
        print("  📋 Fix状態 遷移履歴")
        print("─" * 60)
        for i, entry in enumerate(fix_history, 1):
            from_icon, _, _ = FIX_DISPLAY.get(entry['from'], ("❓", "UNKNOWN", ""))
            to_icon, _, _ = FIX_DISPLAY.get(entry['to'], ("❓", "UNKNOWN", ""))
            print(f"  {i}. [{entry['time']}] #{entry['count']}")
            print(f"     {from_icon} {entry['from_name']} → {to_icon} {entry['to_name']}")
        print("─" * 60)

    # 最終fix状態の判定
    if gps_raw_count > 0:
        final_fix = last_fix_type
        final_status = GPS_FIX_TYPE.get(final_fix, f"UNKNOWN({final_fix})")
        icon, _, color = FIX_DISPLAY.get(final_fix, ("❓", f"UNKNOWN({final_fix})", ""))

        print(f"\n  {color}最終GPS Fix状態: {icon} {final_status}{RESET_COLOR}")

        if final_fix >= 6:
            print("\n🎉 RTK FIXED 達成！センチメートル級の高精度測位が可能です。")
        elif final_fix == 5:
            print("\n🟣 RTK FLOAT - RTK補正を受信中ですが、整数値確定前です。")
            print("   しばらく待つとRTK FIXEDに移行する可能性があります。")
        elif final_fix == 4:
            print("\n🟢 DGPS FIX - ディファレンシャルGPS補正済み（サブメートル級）")
        elif final_fix == 3:
            print("\n🟡 3D FIX - 3次元測位完了（通常のGPS精度: 2-5m）")
        elif final_fix == 2:
            print("\n🟠 2D FIX - 2次元測位のみ（高度情報なし）")
        else:
            print("\n🔴 NO FIX - GPS信号を捕捉できていません")
            print("   確認事項:")
            print("   - GPSアンテナが空の見える場所にあるか")
            print("   - 屋内ではないか")
            print("   - CANケーブルの接続は正しいか")

        print("\n✅ GPS_RAW_INTメッセージ受信確認！")
        print("   DroneCAN GPSがPixhawk6Cに認識されています。")
    else:
        print("\n❌ GPS_RAW_INTメッセージが受信されませんでした。")
        print("   MAVLinkストリームレート設定を確認してください。")

    if global_pos_count > 0:
        print("\n✅ GLOBAL_POSITION_INTメッセージ受信確認！")
        print("   EKFが位置情報を計算しています。")
    else:
        print("\n❌ GLOBAL_POSITION_INTメッセージが受信されませんでした。")
        print("   EKFが位置情報を計算できていません。")


if __name__ == "__main__":
    main()