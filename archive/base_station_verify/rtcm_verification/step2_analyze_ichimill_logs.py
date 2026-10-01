#!/usr/bin/env python3
"""
Step 2: ichimill RTCMログ解析
dronecan_gps_rtk/ichimill_sim/logs/ と dronecan_gps_rtk/ntrip_rtk_client/logs/ 内の
全 .rtcm3 ファイルを解析し、メッセージタイプ分布・基地局座標を抽出する。
"""
import sys
import os
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
try:
    from pyrtcm import RTCMReader
except ImportError:
    print("エラー: pyrtcmがインストールされていません")
    print("  pip install pyrtcm")
    sys.exit(1)


def get_message_name(msg_type):
    names = {
        1005: "Stationary RTK Reference Station ARP",
        1006: "Stationary RTK Reference Station ARP (with antenna height)",
        1019: "GPS Ephemeris",
        1020: "GLONASS Ephemeris",
        1033: "Receiver and Antenna Description",
        1042: "BDS Ephemeris",
        1074: "GPS MSM4",
        1077: "GPS MSM7",
        1084: "GLONASS MSM4",
        1087: "GLONASS MSM7",
        1094: "Galileo MSM4",
        1097: "Galileo MSM7",
        1117: "QZSS MSM7",
        1124: "BeiDou MSM4",
        1127: "BeiDou MSM7",
        1230: "GLONASS L1 & L2 Code-Phase Biases",
        4072: "u-blox Proprietary",
    }
    return names.get(msg_type, f"Unknown({msg_type})")


def ecef2llh(x, y, z):
    import math
    a = 6378137.0
    f = 1 / 298.257223563
    e2 = 2 * f - f * f
    lon = math.atan2(y, x)
    p = math.sqrt(x * x + y * y)
    lat = math.atan2(z, p * (1 - e2))
    for _ in range(10):
        sin_lat = math.sin(lat)
        N = a / math.sqrt(1 - e2 * sin_lat * sin_lat)
        prev_lat = lat
        lat = math.atan2(z + e2 * N * sin_lat, p)
        if abs(lat - prev_lat) < 1e-12:
            break
    sin_lat = math.sin(lat)
    N = a / math.sqrt(1 - e2 * sin_lat * sin_lat)
    if p < 1e-12:
        alt = abs(z) - a * (1 - e2) / math.sqrt(1 - e2)
    else:
        alt = p / math.cos(lat) - N
    return math.degrees(lat), math.degrees(lon), alt


def analyze_file(filepath, label):
    """1つのRTCM3ファイルを解析"""
    print(f"\n{'='*70}")
    print(f" [{label}] 解析: {filepath}")
    print(f"{'='*70}")
    print(f"  ファイルサイズ: {os.path.getsize(filepath):,} bytes")

    with open(filepath, 'rb') as f:
        raw = f.read()
    sync_positions = [i for i, b in enumerate(raw) if b == 0xD3]
    print(f"  0xD3同期バイト出現回数: {len(sync_positions)}")
    if sync_positions:
        avg_interval = (sync_positions[-1] - sync_positions[0]) / max(len(sync_positions) - 1, 1)
        print(f"  0xD3間隔平均: {avg_interval:.1f} bytes")

    msg_types = Counter()
    msg_details = []
    error_count = 0
    total_count = 0

    with open(filepath, 'rb') as f:
        rtr = RTCMReader(f, quitonerror=0)
        while True:
            try:
                raw_data, parsed_data = rtr.read()
                if raw_data is None and parsed_data is None:
                    break
                total_count += 1
                if parsed_data is not None:
                    msg_type = int(parsed_data.identity)
                    msg_types[msg_type] += 1
                    if msg_type in (1005, 1006):
                        msg_details.append({
                            "type": msg_type,
                            "station_id": getattr(parsed_data, 'DF003', None),
                            "ecef_x": getattr(parsed_data, 'DF025', None),
                            "ecef_y": getattr(parsed_data, 'DF026', None),
                            "ecef_z": getattr(parsed_data, 'DF027', None),
                            "itrf_year": getattr(parsed_data, 'DF021', None),
                            "gps_ind": getattr(parsed_data, 'DF022', None),
                            "glo_ind": getattr(parsed_data, 'DF023', None),
                            "gal_ind": getattr(parsed_data, 'DF024', None),
                            "ref_station": getattr(parsed_data, 'DF141', None),
                        })
                else:
                    error_count += 1
            except StopIteration:
                break
            except Exception:
                error_count += 1
                if error_count > 100:
                    break

    print(f"\n  pyrtcm検出メッセージ数: {total_count}")
    print(f"  正常パース: {total_count - error_count}")
    print(f"  パースエラー: {error_count}")

    print(f"\n  メッセージタイプ分布:")
    print(f"  {'Type':<6} {'名称':<50} {'件数':>6}")
    print(f"  {'-'*6} {'-'*50} {'-'*6}")
    for msg_type, cnt in sorted(msg_types.items()):
        name = get_message_name(msg_type)
        print(f"  {msg_type:<6} {name:<50} {cnt:>6}")

    if msg_details:
        print(f"\n  基地局座標 (Type {msg_details[0]['type']}):")
        first = msg_details[0]
        x, y, z = first['ecef_x'], first['ecef_y'], first['ecef_z']
        if x is not None and y is not None and z is not None:
            lat, lon, alt = ecef2llh(x, y, z)
            print(f"    局ID: {first['station_id']}")
            print(f"    ECEF-X: {x:.4f} m")
            print(f"    ECEF-Y: {y:.4f} m")
            print(f"    ECEF-Z: {z:.4f} m")
            print(f"    緯度: {lat:.7f}°")
            print(f"    経度: {lon:.7f}°")
            print(f"    楕円体高: {alt:.2f} m")
            print(f"    ITRF年: {first['itrf_year']}")
            print(f"    GPS: {first['gps_ind']}, GLONASS: {first['glo_ind']}, Galileo: {first['gal_ind']}")
            print(f"    基準局: {'実在' if first['ref_station'] else '仮想'}")

        if len(msg_details) >= 2:
            x_vals = [d['ecef_x'] for d in msg_details if d['ecef_x'] is not None]
            y_vals = [d['ecef_y'] for d in msg_details if d['ecef_y'] is not None]
            z_vals = [d['ecef_z'] for d in msg_details if d['ecef_z'] is not None]
            if x_vals and y_vals and z_vals:
                x_range = max(x_vals) - min(x_vals)
                y_range = max(y_vals) - min(y_vals)
                z_range = max(z_vals) - min(z_vals)
                print(f"\n  座標変動範囲 ({len(msg_details)}件):")
                print(f"    ECEF-X: {x_range:.4f} m")
                print(f"    ECEF-Y: {y_range:.4f} m")
                print(f"    ECEF-Z: {z_range:.4f} m")
                if x_range < 0.1 and y_range < 0.1 and z_range < 0.1:
                    print(f"    ✅ 座標は安定しています")
                else:
                    print(f"    ⚠️ 座標が変動しています")

    return {
        "file": filepath,
        "label": label,
        "size": os.path.getsize(filepath),
        "sync_count": len(sync_positions),
        "total_msgs": total_count,
        "error_count": error_count,
        "msg_types": dict(msg_types),
        "base_station": msg_details[0] if msg_details else None,
    }


def main():
    project_root = Path(__file__).resolve().parent.parent.parent
    ichimill_sim_dir = project_root / "dronecan_gps_rtk" / "ichimill_sim" / "logs"
    ntrip_client_dir = project_root / "dronecan_gps_rtk" / "ntrip_rtk_client" / "logs"

    log_files = []
    for f in sorted(ichimill_sim_dir.glob("rtcm_*.rtcm3")):
        log_files.append((str(f), "ichimill_sim"))
    for f in sorted(ntrip_client_dir.glob("rtcm_*.rtcm3")):
        log_files.append((str(f), "ntrip_rtk_client"))

    if not log_files:
        print("エラー: ichimillログファイルが見つかりません")
        sys.exit(1)

    print("=" * 70)
    print(" Step 2: ichimill RTCMログ解析")
    print("=" * 70)
    print(f"対象ファイル数: {len(log_files)}")
    print()

    all_results = []
    for filepath, label in log_files:
        result = analyze_file(filepath, label)
        all_results.append(result)

    # サマリ
    print(f"\n{'='*70}")
    print(f" 全ファイルサマリ")
    print(f"{'='*70}")
    print(f"  {'ソース':<20} {'ファイル':<40} {'サイズ':>10} {'メッセージ数':>12} {'エラー':>6}")
    print(f"  {'-'*20} {'-'*40} {'-'*10} {'-'*12} {'-'*6}")
    for r in all_results:
        fname = os.path.basename(r['file'])
        print(f"  {r['label']:<20} {fname:<40} {r['size']:>10,} {r['total_msgs']:>12} {r['error_count']:>6}")

    # 結果をファイルに保存
    results_dir = Path(__file__).resolve().parent / "results"
    results_dir.mkdir(exist_ok=True)
    output_path = results_dir / "step2_ichimill_analysis.txt"

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("=" * 70 + "\n")
        f.write(" Step 2: ichimill RTCMログ解析結果\n")
        f.write("=" * 70 + "\n\n")
        for r in all_results:
            f.write(f"ソース: {r['label']}\n")
            f.write(f"ファイル: {r['file']}\n")
            f.write(f"  サイズ: {r['size']:,} bytes\n")
            f.write(f"  0xD3同期バイト: {r['sync_count']}\n")
            f.write(f"  メッセージ数: {r['total_msgs']} (エラー: {r['error_count']})\n")
            f.write(f"  メッセージタイプ分布:\n")
            for msg_type, cnt in sorted(r['msg_types'].items()):
                f.write(f"    Type {msg_type} ({get_message_name(msg_type)}): {cnt}\n")
            if r['base_station']:
                bs = r['base_station']
                x, y, z = bs['ecef_x'], bs['ecef_y'], bs['ecef_z']
                if x is not None and y is not None and z is not None:
                    lat, lon, alt = ecef2llh(x, y, z)
                    f.write(f"  基地局座標:\n")
                    f.write(f"    局ID: {bs['station_id']}\n")
                    f.write(f"    ECEF: X={x:.4f}, Y={y:.4f}, Z={z:.4f}\n")
                    f.write(f"    LLH: {lat:.7f}°, {lon:.7f}°, {alt:.2f}m\n")
            f.write("\n")

    print(f"\n解析結果を保存しました: {output_path}")


if __name__ == "__main__":
    main()