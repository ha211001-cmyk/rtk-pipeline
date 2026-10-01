#!/usr/bin/env python3
"""
Standalone GPS Observation - F9P 単独測位 観測スクリプト

RTKなしでF9PからNMEAセンテンスを受信し、指定時間観測した後、
最良Fix品質のグループの平均座標を表示します。

使用例:
  python rtk_tools/standalone_obs.py
  python rtk_tools/standalone_obs.py --port /dev/ttyACM0 --baudrate 115200 --duration 120
  python rtk_tools/standalone_obs.py --csv
  python rtk_tools/standalone_obs.py --set-rover  # 基地局モードを解除して観測
"""

import argparse
import csv
import math
import os
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import serial
from pyubx2 import UBXMessage, SET

from config_loader import load_hardware_config
try:
    _hw_config = load_hardware_config() or {}
except Exception as _e:
    # 設定ファイルが無い場合はデフォルト設定で動作（単体起動を許容）
    print(f"[WARN] ハードウェア設定を読み込めませんでした（デフォルト設定を使用）: {_e}")
    _hw_config = {}

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------
FIX_NAMES = {
    0: "NoFix",
    1: "GPS",
    2: "DGPS",
    4: "RTK_FIXED",
    5: "RTK_FLOAT",
}

FIX_PRIORITY = {
    0: 0,
    1: 1,
    2: 2,
    5: 3,
    4: 4,
}

METERS_PER_DEG_LAT = 111320.0


# ---------------------------------------------------------------------------
# データクラス
# ---------------------------------------------------------------------------
@dataclass
class GpsSample:
    """1回のGPS観測を表すデータクラス"""
    fix_type: int
    latitude: float
    longitude: float
    altitude: float       # 楕円体高 (HAE) = MSL + ジオイド分離量
    geoid_sep: float      # ジオイド分離量 [m]
    altitude_msl: float   # 平均海面高 [m]
    satellites_used: int
    hdop: float
    timestamp: float


# ---------------------------------------------------------------------------
# NMEA パース
# ---------------------------------------------------------------------------
def _ddmm_to_degrees(raw: float) -> float:
    """ddmm.mmmm → 度単位に変換 (rtk_base_station.py と同じ計算方式)"""
    deg = int(raw / 100)
    return deg + (raw - deg * 100) / 60.0


def _nmea_checksum_ok(sentence: str) -> bool:
    """簡易チェックサム検証 ($ と * の間の XOR)"""
    if "*" not in sentence:
        return True
    try:
        data, csum_str = sentence.split("*")
        csum_expected = int(csum_str.strip(), 16)
    except ValueError:
        return False
    csum_calc = 0
    for ch in data[1:]:
        csum_calc ^= ord(ch)
    return csum_calc == csum_expected


def parse_nmea_gga(line: str) -> Optional[GpsSample]:
    """$GxGGA センテンス1行をパース"""
    line = line.strip()
    if not line:
        return None

    if not (line.startswith("$GNGGA") or line.startswith("$GPGGA")):
        return None

    if not _nmea_checksum_ok(line):
        return None

    parts = line.split(",")
    if len(parts) < 10:
        return None

    try:
        if not parts[2] or not parts[4]:
            return None

        lat_raw = float(parts[2])
        lat = _ddmm_to_degrees(lat_raw)
        if parts[3] == "S":
            lat = -lat

        lon_raw = float(parts[4])
        lon = _ddmm_to_degrees(lon_raw)
        if parts[5] == "W":
            lon = -lon

        # GGA: field6=fix, field7=sats, field8=hdop, field9=alt(MSL), field10=M, field11=geoid_sep
        alt_msl = float(parts[9]) if parts[9] else 0.0
        geoid_sep = float(parts[11]) if len(parts) > 11 and parts[11] else 0.0
        alt_hae = alt_msl + geoid_sep  # 楕円体高 = MSL + ジオイド分離量
        fix_type = int(parts[6]) if parts[6] else 0
        sats = int(parts[7]) if parts[7] else 0
        hdop = float(parts[8]) if parts[8] else 99.9

        return GpsSample(
            fix_type=fix_type,
            latitude=lat,
            longitude=lon,
            altitude=alt_hae,        # HAE (楕円体高)
            geoid_sep=geoid_sep,
            altitude_msl=alt_msl,
            satellites_used=sats,
            hdop=hdop,
            timestamp=time.time(),
        )
    except (ValueError, IndexError):
        return None


# ---------------------------------------------------------------------------
# ポート自動検出（USBポートのみ、VID=0x1546 + PID=0x01A9）
# ---------------------------------------------------------------------------
def _auto_detect_port() -> str:
    """利用可能なCOMポートをスキャンし、EVK-F9PのUSBポートを返す。

    USBポート（VID=0x1546, PID=0x01A9）を最優先で検出する。
    USBポートがない場合は UART1（PID=0x0507）→ UART2（PID=0x0508）の順にフォールバック。

    Returns:
        ポート名（例: "COM10", "COM3", "/dev/ttyACM0"）

    Raises:
        SystemExit: シリアルポートが1つも見つからない場合
    """
    import serial.tools.list_ports

    ports = list(serial.tools.list_ports.comports())
    if not ports:
        print("[ERROR] シリアルポートが見つかりません。")
        print("  - F9P の USB ケーブルを確認してください。")
        print("  - `--port` でポートを直接指定することもできます。")
        sys.exit(1)

    # ポート一覧表示
    print("\n検出されたシリアルポート:")
    print(f"  {'ポート':<12} {'VID:PID':<14} {'説明'}")
    print(f"  {'-'*12} {'-'*14} {'-'*40}")
    for p in ports:
        vid_pid = f"{p.vid:04x}:{p.pid:04x}" if p.vid and p.pid else "(none)"
        marker = ""
        if p.vid == 0x1546 and p.pid == 0x01A9:
            marker = " ← USB(推奨)"
        elif p.vid == 0x1546:
            marker = " ← F9P"
        print(f"  {p.device:<12} {vid_pid:<14} {p.description}{marker}")
    print()

    # 優先順: USB(PID=0x01A9) > UART1(PID=0x0507) > UART2(PID=0x0508)
    priority_pids = [0x01A9, 0x0507, 0x0508]
    for pid in priority_pids:
        for p in ports:
            if p.vid == 0x1546 and p.pid == pid:
                port_name = f"USBネイティブ" if pid == 0x01A9 else f"UART{'1' if pid == 0x0507 else '2'}"
                print(f"→ {port_name} ポートを検出: {p.device}")
                print(f"\n→ 使用ポート: {p.device}")
                return p.device

    # F9P以外のポートがあれば最初のポートを使う
    print(f"  [WARN] F9Pポートが見つかりません。")
    print(f"  → 最初のポートを使用: {ports[0].device}")
    return ports[0].device


# ---------------------------------------------------------------------------
# 観測クラス
# ---------------------------------------------------------------------------
class StandaloneObserver:
    """F9P 単独測位 観測クラス"""

    def __init__(self, port: str, baudrate: int, duration_sec: int,
                 show_csv: bool = False, set_rover: bool = False,
                 save_csv: bool = False, output_path: Optional[str] = None):
        self.port = port
        self.baudrate = baudrate
        self.duration_sec = duration_sec
        self.show_csv = show_csv
        self.set_rover = set_rover
        self.save_csv = save_csv
        self.output_path = output_path
        self.samples: list[GpsSample] = []
        self.best_fix_seen = 0
        self._interrupted = False
        signal.signal(signal.SIGINT, self._sigint_handler)

    def _sigint_handler(self, signum, frame):
        self._interrupted = True

    def _open_serial(self):
        """シリアルポートを開く"""
        print(f"シリアル接続中... {self.port} @ {self.baudrate} bps")
        try:
            ser = serial.Serial(self.port, self.baudrate, timeout=1.0)
            ser.reset_input_buffer()
            return ser
        except serial.SerialException as e:
            print(f"[ERROR] シリアルポートを開けません: {e}")
            sys.exit(1)

    def _set_rover_mode(self, ser: serial.Serial) -> bool:
        """F9Pを移動局（Rover）モードに設定する

        CFG_TMODE_MODE を 0（Disabled）に設定し、
        RAM + FLASH に永続化する。
        ACK/NAK を確認して成功/失敗を返す。
        """
        print("\n[ROVER] F9P を移動局モードに設定中...")
        msg = UBXMessage.config_set(
            layers=0x05,  # RAM + FLASH
            transaction=0,
            cfgData=[("CFG_TMODE_MODE", 0)],  # 0 = Disabled (Rover mode)
        )
        packet = msg.serialize()

        ser.reset_input_buffer()
        ser.write(packet)

        deadline = time.time() + 2.0
        buf = b""
        while time.time() < deadline:
            buf += ser.read(ser.in_waiting or 1)
            ack_idx = buf.find(b"\xb5\x62\x05\x01")
            nak_idx = buf.find(b"\xb5\x62\x05\x00")
            if ack_idx != -1 and len(buf) >= ack_idx + 8:
                print("  [ACK] TMODE3 reset to Disabled (Rover mode)")
                return True
            if nak_idx != -1 and len(buf) >= nak_idx + 8:
                print("  [NAK] TMODE3 reset failed - NAK received")
                return False

        print("  [WARN] ACK not found, but command sent")
        return True

    def _format_fix(self, fix_type: int) -> str:
        """Fixタイプの可読表現"""
        name = FIX_NAMES.get(fix_type, f"UNKNOWN({fix_type})")
        return f"{name}({fix_type})"

    def _print_realtime(self, remaining: float, sample: Optional[GpsSample]):
        """リアルタイムステータス表示（行上書き）"""
        fix_str = self._format_fix(sample.fix_type) if sample else "---"
        line = (
            f"\r  [残り {remaining:4.0f}s] "
            f"Fix={fix_str}  "
            f"サンプル数={len(self.samples):4d}  "
            f"最高Fix={self._format_fix(self.best_fix_seen)}  "
        )
        sys.stdout.write(line.ljust(100))
        sys.stdout.flush()

    def _lon_scale(self, lat_deg: float) -> float:
        """指定緯度での経度1度あたりの距離 [m]"""
        return METERS_PER_DEG_LAT * math.cos(math.radians(lat_deg))

    def _stats_for_group(self, samples: list[GpsSample], fix_name: str):
        """指定グループの統計を表示"""
        n = len(samples)
        if n == 0:
            print(f"\n  [{fix_name}] サンプルなし")
            return

        lats = [s.latitude for s in samples]
        lons = [s.longitude for s in samples]
        alts = [s.altitude for s in samples]
        satss = [s.satellites_used for s in samples]
        hdops = [s.hdop for s in samples]

        mean_lat = sum(lats) / n
        mean_lon = sum(lons) / n
        mean_alt = sum(alts) / n
        mean_sats = sum(satss) / n
        mean_hdop = sum(hdops) / n

        def _stdev(values, mean):
            if n < 2:
                return 0.0
            var = sum((v - mean) ** 2 for v in values) / (n - 1)
            return math.sqrt(var)

        std_lat_deg = _stdev(lats, mean_lat)
        std_lon_deg = _stdev(lons, mean_lon)
        std_alt = _stdev(alts, mean_alt)
        std_lat_m = std_lat_deg * METERS_PER_DEG_LAT
        std_lon_m = std_lon_deg * self._lon_scale(mean_lat)

        print(f"\n{'='*60}")
        print(f"  ★ 最良Fix品質グループ: {fix_name} の統計")
        print(f"{'='*60}")
        print(f"  平均緯度:       {mean_lat:.7f} °")
        print(f"  平均経度:       {mean_lon:.7f} °")
        print(f"  平均高度(MSL):  {mean_alt:.2f} m")
        print(f"  標準偏差(緯度): {std_lat_deg:.7f}°  ({std_lat_m:.3f} m)")
        print(f"  標準偏差(経度): {std_lon_deg:.7f}°  ({std_lon_m:.3f} m)")
        print(f"  標準偏差(高度): {std_alt:.2f} m")
        print(f"  サンプル数:     {n}")
        print(f"  平均衛星数:     {mean_sats:.1f}")
        print(f"  平均HDOP:       {mean_hdop:.2f}")

        if self.show_csv and n > 0:
            self._print_csv(samples, fix_name)

    def _print_csv(self, samples: list[GpsSample], fix_name: str):
        """指定グループの全サンプルをCSV形式で表示"""
        print(f"\n  [{fix_name}] 全サンプル (CSV):")
        print("  fix_type,latitude,longitude,altitude,satellites,hdop,timestamp")
        for s in samples:
            print(
                f"  {s.fix_type},{s.latitude:.7f},{s.longitude:.7f},"
                f"{s.altitude:.2f},{s.satellites_used},{s.hdop:.2f},"
                f"{s.timestamp:.3f}"
            )

    def _save_csv_file(self) -> Optional[str]:
        """全サンプルをCSVファイルに保存する。

        Returns:
            保存したファイルパス、またはサンプルがない場合は None。
        """
        if not self.samples:
            print("\n  [警告] 保存するサンプルがありません。")
            return None

        # 出力パスの決定
        if self.output_path:
            out_path = Path(self.output_path)
        else:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_path = Path(__file__).resolve().parent / "logs" / f"base_obs_{ts}.csv"

        out_path.parent.mkdir(parents=True, exist_ok=True)

        with open(out_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "fix_type", "latitude", "longitude",
                             "altitude", "satellites", "hdop"])
            for s in self.samples:
                writer.writerow([
                    f"{s.timestamp:.3f}",
                    s.fix_type,
                    f"{s.latitude:.8f}",
                    f"{s.longitude:.8f}",
                    f"{s.altitude:.2f}",
                    s.satellites_used,
                    f"{s.hdop:.2f}",
                ])

        print(f"\n  [CSV保存] {out_path} ({len(self.samples)} サンプル)")
        return str(out_path)

    def run(self):
        """メイン観測ループ"""
        print("=" * 60)
        print("  F9P 単独GPS観測 - Standalone Observation")
        print("=" * 60)
        print(f"  ポート:     {self.port}")
        print(f"  ボーレート: {self.baudrate}")
        print(f"  観測時間:   {self.duration_sec} 秒")
        print()

        ser = self._open_serial()

        if self.set_rover:
            self._set_rover_mode(ser)

        print("観測を開始します... Ctrl+C で中断\n")

        start_time = time.time()
        end_time = start_time + self.duration_sec
        last_display = 0.0

        try:
            while time.time() < end_time and not self._interrupted:
                try:
                    raw = ser.readline()
                except serial.SerialException as e:
                    print(f"\n[ERROR] シリアル読み取りエラー: {e}")
                    break

                if not raw:
                    continue

                try:
                    line = raw.decode("ascii", errors="replace")
                except UnicodeDecodeError:
                    continue

                sample = parse_nmea_gga(line)
                if sample is None:
                    continue

                self.samples.append(sample)

                if FIX_PRIORITY.get(sample.fix_type, -1) > FIX_PRIORITY.get(self.best_fix_seen, -1):
                    self.best_fix_seen = sample.fix_type

                now = time.time()
                if now - last_display >= 1.0 or self._interrupted:
                    remaining = max(0, end_time - now)
                    self._print_realtime(remaining, sample)
                    last_display = now

        except KeyboardInterrupt:
            self._interrupted = True

        finally:
            ser.close()
            print("\n")

        self._print_results()

    def _print_results(self):
        """観測結果の集計と表示"""
        total = len(self.samples)

        print("=" * 60)
        print("  観測サマリ")
        print("=" * 60)
        print(f"  総観測数: {total}")

        if total > 0:
            elapsed = self.samples[-1].timestamp - self.samples[0].timestamp
            rate = total / max(elapsed, 0.1)
            print(f"  観測時間: {elapsed:.1f} 秒  ({rate:.1f} サンプル/秒)")

        print()

        if total == 0:
            print("  [警告] 観測データがありません。")
            print("  - シリアル接続とF9Pの電源を確認してください。")
            print("  - F9PがNMEA GGAセンテンスを出力しているか確認してください。")
            return

        counts: dict[int, int] = {}
        for s in self.samples:
            counts[s.fix_type] = counts.get(s.fix_type, 0) + 1

        print("  Fix品質 内訳:")
        for ft in sorted(counts.keys()):
            name = self._format_fix(ft)
            cnt = counts[ft]
            pct = cnt / total * 100
            bar = "█" * int(pct / 2)
            print(f"    {name:<18s} {cnt:5d}  ({pct:5.1f}%)  {bar}")

        best_fix = max(counts.keys(), key=lambda ft: FIX_PRIORITY.get(ft, -1))
        best_name = self._format_fix(best_fix)
        best_samples = [s for s in self.samples if s.fix_type == best_fix]
        self._stats_for_group(best_samples, best_name)

        # CSVファイル保存（--save 指定時）
        if self.save_csv:
            self._save_csv_file()

        print()


# ---------------------------------------------------------------------------
# 公開API（他のモジュールからの再利用用）
# ---------------------------------------------------------------------------
def auto_detect_port() -> str:
    """外部から呼び出し可能な USB ポート自動検出"""
    return _auto_detect_port()


def auto_observe_position(port: str, baudrate: int = 115200,
                          duration_sec: int = 60) -> Optional[dict]:
    """指定ポートで単独測位し、最良Fix品質グループの平均座標を返す。

    Returns:
        {'lat': float, 'lon': float, 'alt': float(HAE),
         'alt_msl': float, 'geoid_sep': float, 'fix_type': int,
         'samples': int, 'std_lat_m': float, 'std_lon_m': float, 'std_alt': float}
        または None（データ不足時）
    """
    observer = StandaloneObserver(
        port=port, baudrate=baudrate, duration_sec=duration_sec,
        set_rover=True, show_csv=False, save_csv=False,
    )
    observer.run()

    if not observer.samples:
        return None

    # 最良Fix品質のグループを抽出
    counts: dict[int, int] = {}
    for s in observer.samples:
        counts[s.fix_type] = counts.get(s.fix_type, 0) + 1
    best_fix = max(counts.keys(), key=lambda ft: FIX_PRIORITY.get(ft, -1))
    best_samples = [s for s in observer.samples if s.fix_type == best_fix]

    if not best_samples:
        return None

    n = len(best_samples)
    lats = [s.latitude for s in best_samples]
    lons = [s.longitude for s in best_samples]
    alts = [s.altitude for s in best_samples]

    mean_lat = sum(lats) / n
    mean_lon = sum(lons) / n
    mean_alt = sum(alts) / n

    def _stdev(values, mean):
        if n < 2:
            return 0.0
        return math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1))

    std_lat_m = _stdev(lats, mean_lat) * METERS_PER_DEG_LAT
    std_lon_m = _stdev(lons, mean_lon) * (METERS_PER_DEG_LAT * math.cos(math.radians(mean_lat)))
    std_alt = _stdev(alts, mean_alt)

    # 標高表示用（サンプル0番目のgeoid_sepを参考表示）
    geoid_sep = best_samples[0].geoid_sep
    alt_msl = best_samples[0].altitude_msl

    print(f"\n{'='*60}")
    print(f"  ★ 自動測位結果（最良Fix品質グループ）")
    print(f"{'='*60}")
    print(f"  Fix品質:    {FIX_NAMES.get(best_fix, f'UNKNOWN({best_fix})')}")
    print(f"  平均緯度:   {mean_lat:.7f} °")
    print(f"  平均経度:   {mean_lon:.7f} °")
    print(f"  平均高度:   {mean_alt:.2f} m (楕円体高 HAE)")
    print(f"  平均高度:   {alt_msl:.2f} m (海抜 MSL)")
    print(f"  ジオイド分離量: {geoid_sep:.2f} m")
    print(f"  標準偏差:   緯度{std_lat_m:.3f}m / 経度{std_lon_m:.3f}m / 高度{std_alt:.2f}m")
    print(f"  サンプル数: {n}")
    print()

    return {
        'lat': mean_lat,
        'lon': mean_lon,
        'alt': mean_alt,          # 楕円体高 (HAE)
        'alt_msl': alt_msl,
        'geoid_sep': geoid_sep,
        'fix_type': best_fix,
        'samples': n,
        'std_lat_m': std_lat_m,
        'std_lon_m': std_lon_m,
        'std_alt': std_alt,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="F9P 単独GPS観測 - 最良Fix品質の平均座標を表示",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  python rtk_tools/standalone_obs.py
  python rtk_tools/standalone_obs.py --port /dev/ttyACM0 --baudrate 115200
  python rtk_tools/standalone_obs.py --duration 120 --csv
        """,
    )
    parser.add_argument(
        "--port",
        default=None,
        help=f"シリアルポート (省略時は自動検出)",
    )
    parser.add_argument(
        "--baudrate",
        type=int,
        default=_hw_config['f9p']['baudrate'],
        help=f"ボーレート (デフォルト: {_hw_config['f9p']['baudrate']})",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=60,
        help="観測時間 [秒] (デフォルト: 60)",
    )
    parser.add_argument(
        "--csv",
        action="store_true",
        help="最良Fix品質グループの全サンプルをCSV形式で表示",
    )
    parser.add_argument(
        "--set-rover",
        action="store_true",
        help="観測前にF9Pを移動局（Rover）モードに設定 (TMODE3 → Disabled)",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="全サンプルを logs/base_obs_<timestamp>.csv に保存",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="CSV出力ファイルパス (--save時。省略時は自動生成)",
    )
    args = parser.parse_args()

    # ポート未指定 → 自動検出
    port = args.port
    if port is None:
        port = _auto_detect_port()

    observer = StandaloneObserver(
        port=port,
        baudrate=args.baudrate,
        duration_sec=args.duration,
        show_csv=args.csv,
        set_rover=args.set_rover,
        save_csv=args.save,
        output_path=args.output,
    )
    observer.run()


if __name__ == "__main__":
    main()
