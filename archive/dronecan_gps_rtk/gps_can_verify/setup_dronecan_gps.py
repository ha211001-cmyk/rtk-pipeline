#!/usr/bin/env python3
"""
DroneCAN H-RTK F9P Helical用 パラメータ設定スクリプト

Pixhawk6CのCAN1ポートに接続したDroneCAN GPSモジュールを有効化するための
パラメータ設定を行う。

【重要】ArduPilotはPARAM_SET受信時に自動でFlash/EEPROMへ即時書き込みを行うため、
MAV_CMD_PREFLIGHT_STORAGEは不要。最終確認でパラメータが正しく読み取れれば
保存は完了している。

使用方法:
    source ~/Mavlink_venv/bin/activate
    python3 setup_dronecan_gps.py
"""

import sys
import os
import time
import json

# 設定ファイル読み込み
CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')

# デフォルト接続設定（TELEM1ポート）
DEFAULT_PORT = '/dev/ttyAMA0'
DEFAULT_BAUD = 921600  # 921600bps (Pixhawk6C TELEM1)
DEFAULT_RTSCTS = True

def load_config():
    """config.jsonから接続設定を読み込む"""
    try:
        with open(CONFIG_PATH, 'r') as f:
            return json.load(f)
    except Exception:
        return {}

# pymavlinkのインポート（Mavlink_venvから）
try:
    from pymavlink import mavutil
except ImportError:
    print("エラー: pymavlinkがインストールされていません")
    print("以下のコマンドで仮想環境を有効化してください:")
    print("  source ~/Mavlink_venv/bin/activate")
    sys.exit(1)

# ================================
# DroneCAN GPS用パラメータ設定
# ================================

# 設定するパラメータ（型情報付き）
PARAMS_TO_SET = {
    # === CAN/DroneCAN基本設定 ===
    'CAN_P1_DRIVER': (1, 'AP_Int8', 'CAN1ポート有効化'),
    'CAN_D1_PROTOCOL': (1, 'AP_Int8', 'DroneCANプロトコル'),

    # === GPS設定 ===
    'GPS1_TYPE': (9, 'AP_Int8', 'GPS1タイプ: 9=DroneCAN'),
    'GPS_AUTO_CONFIG': (2, 'AP_Int8', 'DroneCAN AutoConfig'),
    'GPS_PRIMARY': (0, 'AP_Int8', 'プライマリGPS'),
    'GPS_AUTO_SWITCH': (0, 'AP_Int8', 'GPS自動切替無効'),

    # === コンパス設定（H-RTK内蔵コンパス使用）===
    'COMPASS_ENABLE': (1, 'AP_Int8', 'コンパス有効化'),
    'COMPASS_USE': (0, 'AP_Int8', '内蔵コンパス無効 (ノイズ回避)'),
    'COMPASS_USE2': (1, 'AP_Int8', 'H-RTK外付コンパス有効'),
    'COMPASS_USE3': (0, 'AP_Int8', '外付コンパス3無効'),
    'COMPASS_AUTODEC': (1, 'AP_Int8', '自動磁気偏角有効'),
}

# MAVLink型マッピング
MAV_PARAM_TYPE_MAP = {
    'AP_Int8': mavutil.mavlink.MAV_PARAM_TYPE_INT8,
    'AP_Int16': mavutil.mavlink.MAV_PARAM_TYPE_INT16,
    'AP_Int32': mavutil.mavlink.MAV_PARAM_TYPE_INT32,
    'AP_Float': mavutil.mavlink.MAV_PARAM_TYPE_REAL32,
}

# ================================
# ユーティリティ関数
# ================================

def clear_message_buffer(master, timeout=0.1):
    """メッセージバッファをクリアして古いメッセージを除去"""
    cleared_count = 0
    while True:
        msg = master.recv_match(blocking=False, timeout=timeout)
        if msg is None:
            break
        cleared_count += 1
    if cleared_count > 0:
        print(f"  [バッファ] {cleared_count}個の古いメッセージをクリア")
    return cleared_count

def wait_for_param_ack(master, param_name, expected_value, timeout=2.0):
    """特定のパラメータのPARAM_VALUEメッセージを待機"""
    start_time = time.time()

    while time.time() - start_time < timeout:
        msg = master.recv_match(type='PARAM_VALUE', blocking=False, timeout=0.05)
        if msg is None:
            continue

        msg_dict = msg.to_dict()
        msg_param_name = msg_dict.get('param_id', '').rstrip('\x00')

        if msg_param_name == param_name:
            received_value = msg_dict.get('param_value', None)
            return received_value, True

    return None, False

def set_parameter_reliable(master, param_name, param_value, param_type, max_retries=5):
    """パラメータを確実に設定する"""
    mav_param_type = MAV_PARAM_TYPE_MAP.get(param_type, mavutil.mavlink.MAV_PARAM_TYPE_REAL32)

    for attempt in range(max_retries):
        clear_message_buffer(master, timeout=0.05)

        master.mav.param_set_send(
            master.target_system,
            master.target_component,
            param_name.encode('utf-8'),
            float(param_value),
            mav_param_type
        )

        time.sleep(0.2)

        received_value, received = wait_for_param_ack(master, param_name, param_value, timeout=1.5)

        if received and received_value is not None:
            if abs(float(received_value) - float(param_value)) < 0.0001:
                return True, received_value
            else:
                if attempt < max_retries - 1:
                    print(f'    ⚠️ リトライ {attempt + 1}/{max_retries}: 設定値={param_value}, 確認値={received_value}')
                    time.sleep(0.3)
                else:
                    print(f'    ❌ 最終失敗: 設定値={param_value}, 確認値={received_value}')
                    return False, received_value
        else:
            if attempt < max_retries - 1:
                print(f'    ⚠️ タイムアウト リトライ {attempt + 1}/{max_retries}')
                time.sleep(0.3)
            else:
                print(f'    ❌ タイムアウト（設定失敗）')
                return False, None

    return False, None

def verify_parameter(master, param_name, expected_value):
    """パラメータを読み込んで値を確認"""
    clear_message_buffer(master, timeout=0.05)

    master.mav.param_request_read_send(
        master.target_system,
        master.target_component,
        param_name.encode('utf-8'),
        -1
    )

    time.sleep(0.15)
    received_value, received = wait_for_param_ack(master, param_name, expected_value, timeout=1.5)

    if received and received_value is not None:
        return float(received_value), True
    else:
        return None, False

# ================================
# メイン処理
# ================================

def main():
    print("\n" + "="*60)
    print("DroneCAN H-RTK F9P Helical パラメータ設定")
    print("="*60)

    # 設定読み込み
    config = load_config()

    # 接続設定（デフォルトを優先）
    port = DEFAULT_PORT
    baud = DEFAULT_BAUD
    rtscts = DEFAULT_RTSCTS

    print(f"\n接続中: {port} @ {baud}bps (RTS/CTS: {rtscts})")
    print("（Pixhawk6C TELEM1ポート、ハードウェアフロー制御有効）")
    master = mavutil.mavlink_connection(port, baud=baud, rtscts=rtscts)

    # ハートビート確認
    print("ハートビート待機中...")
    master.wait_heartbeat(timeout=10)
    print(f"✅ 接続完了 (システム: {master.target_system}, コンポーネント: {master.target_component})")

    # パラメータ設定
    print("\n" + "-"*60)
    print("パラメータ設定開始")
    print("-"*60)

    failed_params = {}
    total = len(PARAMS_TO_SET)
    success_count = 0

    for idx, (param_name, (param_value, param_type, param_comment)) in enumerate(PARAMS_TO_SET.items(), 1):
        print(f"\n[{idx}/{total}] {param_name}")
        print(f"  設定値: {param_value} ({param_comment})")

        success, received_value = set_parameter_reliable(master, param_name, param_value, param_type)

        if success:
            print(f"  ✅ 確認値: {received_value}")
            success_count += 1
        else:
            print(f"  ❌ 設定失敗")
            failed_params[param_name] = (param_value, param_type, param_comment)

    print("\n" + "="*60)
    print(f"設定完了: {success_count}/{total} 成功")
    print("="*60)

    # FC側の処理完了を待つ
    print("\nFC側の処理完了を待機中...")
    time.sleep(3)

    # 不一致パラメータの再設定
    if failed_params:
        print("\n" + "="*60)
        print(f"⚠️ {len(failed_params)}個のパラメータが不一致です。再設定を試みます...")
        print("="*60)

        for param_name, (param_value, param_type, param_comment) in failed_params.items():
            print(f"\n再設定: {param_name}")
            success, received_value = set_parameter_reliable(master, param_name, param_value, param_type, max_retries=3)

            if success:
                print(f"  ✅ 再設定成功: {received_value}")
            else:
                print(f"  ❌ 再設定失敗: {received_value}")

    # 最終確認
    print("\n" + "="*60)
    print("最終確認を実施中...")
    print("="*60)

    final_failed = []
    final_success = 0

    for param_name, (param_value, param_type, param_comment) in PARAMS_TO_SET.items():
        received_value, verified = verify_parameter(master, param_name, param_value)

        if verified and received_value is not None:
            if abs(float(received_value) - float(param_value)) < 0.0001:
                print(f"✅ {param_name} = {received_value}")
                final_success += 1
            else:
                print(f"❌ {param_name} = {received_value} (期待値: {param_value})")
                final_failed.append(param_name)
        else:
            print(f"❌ {param_name} (データ取得失敗)")
            final_failed.append(param_name)

    print("\n" + "="*60)
    print(f"最終結果: {final_success}/{total} 成功")
    if final_failed:
        print(f"失敗: {len(final_failed)}個")
        for name in final_failed[:10]:
            print(f"  - {name}")
    print("="*60)

    if final_failed:
        print(f"\n❌ {len(final_failed)}個のパラメータが正しく設定できませんでした")
    else:
        print("\n✅ 全てのパラメータが正しく設定されました！")
        print("   ArduPilotはPARAM_SET受信時に自動でFlashへ保存するため、")
        print("   再起動後も設定は維持されます。")
        print("   DroneCAN H-RTK F9P Helicalが使用可能です。")

    print("\n次のステップ: python3 verify_gps_fix2.py でGPS状態を確認してください。")
    print("完了")

if __name__ == "__main__":
    main()