import sys
import os
import csv
import datetime
from pathlib import Path

def gps_to_utc_str(gwk, gms):
    if not gwk or not gms:
        return ""
    # GPSエポック (1980年1月6日) からの経過時間を計算 (うるう秒約18秒を引く)
    gps_epoch = datetime.datetime(1980, 1, 6)
    dt = gps_epoch + datetime.timedelta(weeks=gwk, milliseconds=gms) - datetime.timedelta(seconds=18)
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

def extract_ardupilot_bin(bin_file, output_csv):
    try:
        from pymavlink import mavutil
    except ImportError:
        print("エラー: pymavlink がインストールされていません。\n'pip install pymavlink' を実行してください。")
        sys.exit(1)

    print(f"ArduPilot DataFlashログ (.bin) を解析中: {bin_file}")
    mlog = mavutil.mavlink_connection(bin_file)
    
    with open(output_csv, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["utc_datetime", "time_us", "msg_type", "lat_deg", "lon_deg", "alt_m", "status", "sats"])
        
        count = 0
        hp_count = 0
        while True:
            msg = mlog.recv_msg()
            if msg is None:
                break
            
            msg_type = msg.get_type()
            
            # 標準のGPSログ
            if msg_type == 'GPS':
                m_dict = msg.to_dict()
                lat = m_dict.get('Lat', 0) / 1e7
                lon = m_dict.get('Lng', 0) / 1e7
                alt = m_dict.get('Alt', 0)
                status = m_dict.get('Status', 0)
                sats = m_dict.get('NSats', 0)
                time_us = m_dict.get('TimeUS', 0)
                
                gwk = m_dict.get('GWk', 0)
                gms = m_dict.get('GMS', 0)
                utc_str = gps_to_utc_str(gwk, gms)
                
                writer.writerow([utc_str, time_us, 'GPS', lat, lon, alt, status, sats])
                count += 1
                
            # UBXの生ログ (高精度)
            elif msg_type.startswith('UBX'):
                m_dict = msg.to_dict()
                if 'lat' in m_dict and 'latHp' in m_dict:
                    lat = (m_dict['lat'] + m_dict['latHp'] * 1e-2) / 1e7
                    lon = (m_dict['lon'] + m_dict['lonHp'] * 1e-2) / 1e7
                    alt = (m_dict['hMSL'] + m_dict['hMSLHp'] * 1e-2) / 1000.0
                    time_us = m_dict.get('TimeUS', 0)
                    # UBXログにはGWk/GMSが直接入っていないことが多いので空欄にするか直前の時刻を使う
                    writer.writerow(["", time_us, msg_type, lat, lon, alt, "RTK_HP", 0])
                    hp_count += 1

    print(f"抽出完了! -> {output_csv}")
    print(f" - 標準GPSデータ: {count} 件")
    print(f" - 超高精度(UBX_HP)データ: {hp_count} 件")

def extract_px4_ulog(ulg_file, output_csv):
    try:
        from pyulog import ULog
    except ImportError:
        print("エラー: pyulog がインストールされていません。\n'pip install pyulog' を実行してください。")
        sys.exit(1)
        
    print(f"PX4 ULog (.ulg) を解析中: {ulg_file}")
    ulog = ULog(ulg_file)
    
    with open(output_csv, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["utc_datetime", "time_us", "msg_type", "lat_deg", "lon_deg", "alt_m", "status", "sats"])
        
        count = 0
        for d in ulog.data_list:
            if d.name == 'sensor_gps':
                data = d.data
                for i in range(len(data['timestamp'])):
                    lat = data['lat'][i] / 1e7
                    lon = data['lon'][i] / 1e7
                    alt = data['alt'][i] / 1000.0
                    status = data['fix_type'][i]
                    sats = data['satellites_used'][i]
                    time_us = data['timestamp'][i]
                    
                    # PX4のsensor_gpsは time_utc_usec を持つことが多い
                    utc_usec = data.get('time_utc_usec', [0])[i]
                    utc_str = ""
                    if utc_usec > 0:
                        dt = datetime.datetime.utcfromtimestamp(utc_usec / 1e6)
                        utc_str = dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                        
                    writer.writerow([utc_str, time_us, 'sensor_gps', lat, lon, alt, status, sats])
                    count += 1
                    
    print(f"抽出完了! -> {output_csv}")
    print(f" - GPSデータ: {count} 件")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使い方: python3 parse_fc_log.py <ログファイルへのパス.bin または .ulg>")
        sys.exit(1)
        
    log_path = sys.argv[1]
    if not os.path.exists(log_path):
        print(f"ファイルが見つかりません: {log_path}")
        sys.exit(1)
        
    out_csv = Path(log_path).with_suffix('.csv')
    ext = Path(log_path).suffix.lower()
    
    if ext == '.bin':
        extract_ardupilot_bin(log_path, out_csv)
    elif ext == '.ulg':
        extract_px4_ulog(log_path, out_csv)
    else:
        print(f"未対応の拡張子です ({ext})。ArduPilotの .bin か PX4の .ulg を指定してください。")
