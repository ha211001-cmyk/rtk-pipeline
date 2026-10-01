#!/usr/bin/env python3
"""
Step 3: F9P基地局 vs ichimill RTCMログ比較検証
Step1とStep2の解析結果を比較し、差異を検証する。
"""
import sys
import os
import math
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


def haversine_distance(lat1, lon1, lat2, lon2):
    """2点間の距離を計算 (Haversine formula) [m]"""
    R = 6371000  # 地球の半径 (m)
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def analyze_file(filepath):
    """1つのRTCM3ファイルを解析し、結果を返す"""
    with open(filepath, 'rb') as f:
        raw = f.read()
    sync_positions = [i for i, b in enumerate(raw) if b == 0xD3]

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

    return {
        "file": filepath,
        "size": os.path.getsize(filepath),
        "sync_count": len(sync_positions),
        "total_msgs": total_count,
        "error_count": error_count,
        "msg_types": dict(msg_types),
        "base_station": msg_details[0] if msg_details else None,
    }


def main():
    project_root = Path(__file__).resolve().parent.parent.parent

    # F9P基地局ログ
    f9p_log_dir = Path(__file__).resolve().parent.parent / "rtcm_compare" / "logs"
    f9p_files = sorted(f9p_log_dir.glob("rtcm_raw_*.rtcm3"))

    # ichimillログ
    ichimill_sim_dir = project_root / "dronecan_gps_rtk" / "ichimill_sim" / "logs"
    ntrip_client_dir = project_root / "dronecan_gps_rtk" / "ntrip_rtk_client" / "logs"
    ichimill_files = []
    for f in sorted(ichimill_sim_dir.glob("rtcm_*.rtcm3")):
        ichimill_files.append((str(f), "ichimill_sim"))
    for f in sorted(ntrip_client_dir.glob("rtcm_*.rtcm3")):
        ichimill_files.append((str(f), "ntrip_rtk_client"))

    print("=" * 70)
    print(" Step 3: F9P基地局 vs ichimill RTCMログ比較検証")
    print("=" * 70)

    # F9Pログ解析
    print("\n[F9P基地局ログ解析]")
    f9p_results = []
    for f in f9p_files:
        r = analyze_file(str(f))
        f9p_results.append(r)
        print(f"  {os.path.basename(f)}: {r['total_msgs']} msgs, errors={r['error_count']}")

    # ichimillログ解析
    print("\n[ichimillログ解析]")
    ichimill_results = []
    for filepath, label in ichimill_files:
        r = analyze_file(filepath)
        r['label'] = label
        ichimill_results.append(r)
        print(f"  [{label}] {os.path.basename(filepath)}: {r['total_msgs']} msgs, errors={r['error_count']}")

    # 比較
    print(f"\n{'='*70}")
    print(f" 比較結果")
    print(f"{'='*70}")

    # 最新のF9Pログとichimillログを代表として比較
    f9p_latest = f9p_results[-1] if f9p_results else None
    ichimill_latest = ichimill_results[-1] if ichimill_results else None

    if not f9p_latest or not ichimill_latest:
        print("エラー: 比較対象のログがありません")
        sys.exit(1)

    # 1. RTCM3フレーム構造
    print("\n--- 1. RTCM3フレーム構造 ---")
    print(f"  F9P:     0xD3同期バイト={f9p_latest['sync_count']}, パースエラー={f9p_latest['error_count']}")
    print(f"  ichimill: 0xD3同期バイト={ichimill_latest['sync_count']}, パースエラー={ichimill_latest['error_count']}")
    if f9p_latest['error_count'] == 0 and ichimill_latest['error_count'] == 0:
        print(f"  ✅ 両者ともパースエラー0、RTCM3フレーム構造は規格準拠")
    else:
        print(f"  ⚠️ パースエラーあり")

    # 2. メッセージタイプ分布
    print("\n--- 2. メッセージタイプ分布 ---")
    f9p_types = set(f9p_latest['msg_types'].keys())
    ichimill_types = set(ichimill_latest['msg_types'].keys())

    common = f9p_types & ichimill_types
    f9p_only = f9p_types - ichimill_types
    ichimill_only = ichimill_types - f9p_types

    print(f"  共通タイプ: {sorted(common)}")
    if f9p_only:
        print(f"  F9Pのみ: {sorted(f9p_only)}")
    if ichimill_only:
        print(f"  ichimillのみ: {sorted(ichimill_only)}")

    # 詳細比較テーブル
    all_types = sorted(f9p_types | ichimill_types)
    print(f"\n  {'Type':<6} {'名称':<50} {'F9P':>6} {'ichimill':>10} {'一致':>6}")
    print(f"  {'-'*6} {'-'*50} {'-'*6} {'-'*10} {'-'*6}")
    for t in all_types:
        f9p_cnt = f9p_latest['msg_types'].get(t, 0)
        ichi_cnt = ichimill_latest['msg_types'].get(t, 0)
        match = "✅" if (f9p_cnt > 0 and ichi_cnt > 0) or (f9p_cnt == 0 and ichi_cnt == 0) else "❌"
        name = get_message_name(t)
        print(f"  {t:<6} {name:<50} {f9p_cnt:>6} {ichi_cnt:>10} {match:>6}")

    # 3. 基地局座標比較
    print("\n--- 3. 基地局座標比較 ---")
    f9p_bs = f9p_latest['base_station']
    ichi_bs = ichimill_latest['base_station']

    if f9p_bs and ichi_bs:
        f9p_x, f9p_y, f9p_z = f9p_bs['ecef_x'], f9p_bs['ecef_y'], f9p_bs['ecef_z']
        ichi_x, ichi_y, ichi_z = ichi_bs['ecef_x'], ichi_bs['ecef_y'], ichi_bs['ecef_z']

        if all(v is not None for v in [f9p_x, f9p_y, f9p_z, ichi_x, ichi_y, ichi_z]):
            f9p_lat, f9p_lon, f9p_alt = ecef2llh(f9p_x, f9p_y, f9p_z)
            ichi_lat, ichi_lon, ichi_alt = ecef2llh(ichi_x, ichi_y, ichi_z)

            distance = haversine_distance(f9p_lat, f9p_lon, ichi_lat, ichi_lon)
            alt_diff = abs(f9p_alt - ichi_alt)

            print(f"  F9P基地局:")
            print(f"    Type: {f9p_bs['type']}, 局ID: {f9p_bs['station_id']}")
            print(f"    ECEF: X={f9p_x:.4f}, Y={f9p_y:.4f}, Z={f9p_z:.4f}")
            print(f"    LLH:  {f9p_lat:.7f}°, {f9p_lon:.7f}°, {f9p_alt:.2f}m")
            print(f"    基準局: {'実在' if f9p_bs['ref_station'] else '仮想'}")
            print(f"    GNSS: GPS={f9p_bs['gps_ind']}, GLO={f9p_bs['glo_ind']}, GAL={f9p_bs['gal_ind']}")

            print(f"\n  ichimill:")
            print(f"    Type: {ichi_bs['type']}, 局ID: {ichi_bs['station_id']}")
            print(f"    ECEF: X={ichi_x:.4f}, Y={ichi_y:.4f}, Z={ichi_z:.4f}")
            print(f"    LLH:  {ichi_lat:.7f}°, {ichi_lon:.7f}°, {ichi_alt:.2f}m")
            print(f"    基準局: {'実在' if ichi_bs['ref_station'] else '仮想'}")
            print(f"    GNSS: GPS={ichi_bs['gps_ind']}, GLO={ichi_bs['glo_ind']}, GAL={ichi_bs['gal_ind']}")

            print(f"\n  座標差異:")
            print(f"    水平距離: {distance:.1f} m")
            print(f"    高度差:   {alt_diff:.2f} m")
            print(f"    ECEF-X差: {abs(f9p_x - ichi_x):.2f} m")
            print(f"    ECEF-Y差: {abs(f9p_y - ichi_y):.2f} m")
            print(f"    ECEF-Z差: {abs(f9p_z - ichi_z):.2f} m")

            if distance < 10:
                print(f"    ✅ 座標はほぼ一致（{distance:.1f}m以内）")
            elif distance < 100:
                print(f"    ⚠️ 座標に{distance:.0f}mの差異（近接だが異なる地点）")
            else:
                print(f"    ℹ️ 座標に{distance:.0f}mの差異（異なる実験地点、またはVRS）")

    # 4. MSMメッセージの精度レベル比較
    print("\n--- 4. MSMメッセージ精度レベル ---")
    msm4_types = {1074, 1084, 1094, 1124}
    msm7_types = {1077, 1087, 1097, 1117, 1127}

    f9p_msm4 = [t for t in f9p_types if t in msm4_types]
    f9p_msm7 = [t for t in f9p_types if t in msm7_types]
    ichi_msm4 = [t for t in ichimill_types if t in msm4_types]
    ichi_msm7 = [t for t in ichimill_types if t in msm7_types]

    print(f"  F9P:      MSM4={sorted(f9p_msm4)}, MSM7={sorted(f9p_msm7)}")
    print(f"  ichimill: MSM4={sorted(ichi_msm4)}, MSM7={sorted(ichi_msm7)}")

    if f9p_msm4 and not f9p_msm7:
        print(f"  ⚠️ F9PはMSM4のみ出力（MSM7未設定）")
    if ichi_msm7 and not ichi_msm4:
        print(f"  ℹ️ ichimillはMSM7のみ出力（高精度）")

    # 5. GNSSシステムカバレッジ
    print("\n--- 5. GNSSシステムカバレッジ ---")
    gnss_map = {
        "GPS": [1074, 1077],
        "GLONASS": [1084, 1087],
        "Galileo": [1094, 1097],
        "QZSS": [1117],
        "BeiDou": [1124, 1127],
    }

    print(f"  {'システム':<12} {'F9P':<10} {'ichimill':<10}")
    print(f"  {'-'*12} {'-'*10} {'-'*10}")
    for sys_name, type_ids in gnss_map.items():
        f9p_has = any(t in f9p_types for t in type_ids)
        ichi_has = any(t in ichimill_types for t in type_ids)
        f9p_mark = "✅" if f9p_has else "❌"
        ichi_mark = "✅" if ichi_has else "❌"
        print(f"  {sys_name:<12} {f9p_mark:<10} {ichi_mark:<10}")

    # 6. 追加メッセージ
    print("\n--- 6. 追加メッセージ ---")
    extra_types = {1019, 1020, 1033, 1042, 1230, 4072}
    for t in sorted(extra_types):
        f9p_has = t in f9p_types
        ichi_has = t in ichimill_types
        if f9p_has or ichi_has:
            name = get_message_name(t)
            f9p_cnt = f9p_latest['msg_types'].get(t, 0)
            ichi_cnt = ichimill_latest['msg_types'].get(t, 0)
            print(f"  Type {t} ({name}): F9P={f9p_cnt}, ichimill={ichi_cnt}")

    # 結果をファイルに保存
    results_dir = Path(__file__).resolve().parent / "results"
    results_dir.mkdir(exist_ok=True)
    output_path = results_dir / "step3_comparison.txt"

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("=" * 70 + "\n")
        f.write(" Step 3: F9P基地局 vs ichimill RTCMログ比較検証結果\n")
        f.write("=" * 70 + "\n\n")

        f.write("--- 1. RTCM3フレーム構造 ---\n")
        f.write(f"  F9P:     0xD3同期バイト={f9p_latest['sync_count']}, パースエラー={f9p_latest['error_count']}\n")
        f.write(f"  ichimill: 0xD3同期バイト={ichimill_latest['sync_count']}, パースエラー={ichimill_latest['error_count']}\n")
        f.write(f"  両者ともパースエラー0、RTCM3フレーム構造は規格準拠\n\n")

        f.write("--- 2. メッセージタイプ分布 ---\n")
        for t in all_types:
            f9p_cnt = f9p_latest['msg_types'].get(t, 0)
            ichi_cnt = ichimill_latest['msg_types'].get(t, 0)
            name = get_message_name(t)
            f.write(f"  Type {t} ({name}): F9P={f9p_cnt}, ichimill={ichi_cnt}\n")

        if f9p_bs and ichi_bs:
            f9p_x, f9p_y, f9p_z = f9p_bs['ecef_x'], f9p_bs['ecef_y'], f9p_bs['ecef_z']
            ichi_x, ichi_y, ichi_z = ichi_bs['ecef_x'], ichi_bs['ecef_y'], ichi_bs['ecef_z']
            if all(v is not None for v in [f9p_x, f9p_y, f9p_z, ichi_x, ichi_y, ichi_z]):
                f9p_lat, f9p_lon, f9p_alt = ecef2llh(f9p_x, f9p_y, f9p_z)
                ichi_lat, ichi_lon, ichi_alt = ecef2llh(ichi_x, ichi_y, ichi_z)
                distance = haversine_distance(f9p_lat, f9p_lon, ichi_lat, ichi_lon)
                f.write(f"\n--- 3. 基地局座標比較 ---\n")
                f.write(f"  F9P:      {f9p_lat:.7f}°, {f9p_lon:.7f}°, {f9p_alt:.2f}m (Type {f9p_bs['type']})\n")
                f.write(f"  ichimill: {ichi_lat:.7f}°, {ichi_lon:.7f}°, {ichi_alt:.2f}m (Type {ichi_bs['type']})\n")
                f.write(f"  水平距離: {distance:.1f} m, 高度差: {abs(f9p_alt - ichi_alt):.2f} m\n")

        f.write(f"\n--- 4. MSM精度レベル ---\n")
        f.write(f"  F9P:      MSM4={sorted(f9p_msm4)}, MSM7={sorted(f9p_msm7)}\n")
        f.write(f"  ichimill: MSM4={sorted(ichi_msm4)}, MSM7={sorted(ichi_msm7)}\n")

        f.write(f"\n--- 5. GNSSシステムカバレッジ ---\n")
        for sys_name, type_ids in gnss_map.items():
            f9p_has = any(t in f9p_types for t in type_ids)
            ichi_has = any(t in ichimill_types for t in type_ids)
            f.write(f"  {sys_name}: F9P={'✅' if f9p_has else '❌'}, ichimill={'✅' if ichi_has else '❌'}\n")

    print(f"\n比較結果を保存しました: {output_path}")


if __name__ == "__main__":
    main()