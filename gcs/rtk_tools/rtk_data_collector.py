#!/usr/bin/env python3
"""
RTK Data Collector — u-blox基準局 + Pixhawk移動局 同時データ収集

u-blox F9P基準局からNMEA GGAを直接取得し、
GCS WebSocket API経由でPixhawk側のGPSデータを取得。
両者の位置差（誤差）をリアルタイム計算してCSVに保存し、
観測終了後に分析レポート（JSON）を生成する。

【使用例】
  python rtk_tools/rtk_data_collector.py
  python rtk_tools/rtk_data_collector.py --duration 120
  python rtk_tools/rtk_data_collector.py --gcs-url http://localhost:8000
  python rtk_tools/rtk_data_collector.py --simulate

【出力】
  logs/rtk_error_<timestamp>.csv     — 生データ＋誤差
  logs/rtk_analysis_<timestamp>.json — 統計分析レポート
"""

import argparse
import csv
import json
import math
import random
import signal
import socket
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

# ============================================================================
# 定数
# ============================================================================
METERS_PER_DEG_LAT = 111320.0

FIX_TYPE_NAMES: dict[int, str] = {
    0: "NO_GPS", 1: "NO_FIX", 2: "2D_FIX", 3: "3D_FIX",
    4: "DGPS", 5: "RTK_FLOAT", 6: "RTK_FIXED", 7: "STATIC", 8: "PPP",
}
NMEA_FIX_MAP: dict[int, int] = {0: 0, 1: 3, 2: 4, 4: 6, 5: 5}

# ============================================================================
# データ構造
# ============================================================================
@dataclass
class GpsSample:
    timestamp: float
    fix_type: int
    latitude: float
    longitude: float
    altitude: float
    satellites: int
    hdop: float
    source: str  # "ublox" or "pixhawk"

@dataclass
class ErrorSample:
    timestamp: float
    fix_u: int; sats_u: int; lat_u: float; lon_u: float
    alt_u: float; hdop_u: float
    fix_p: int; sats_p: int; lat_p: float; lon_p: float
    alt_p: float; hdop_p: float
    delta_lat_m: float; delta_lon_m: float; delta_alt_m: float
    horizontal_error_m: float

# ============================================================================
# NMEA パース
# ============================================================================
def _ddmm_to_degrees(raw: float) -> float:
    deg = int(raw / 100)
    return deg + (raw - deg * 100) / 60.0

def _nmea_checksum_ok(sentence: str) -> bool:
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
    line = line.strip()
    if not line or not (line.startswith("$GNGGA") or line.startswith("$GPGGA")):
        return None
    if not _nmea_checksum_ok(line):
        return None
    parts = line.split(",")
    if len(parts) < 10:
        return None
    try:
        if not parts[2] or not parts[4]:
            return None
        lat = _ddmm_to_degrees(float(parts[2]))
        if parts[3] == "S":
            lat = -lat
        lon = _ddmm_to_degrees(float(parts[4]))
        if parts[5] == "W":
            lon = -lon
        alt = float(parts[9]) if parts[9] else 0.0
        fix_quality = int(parts[6]) if parts[6] else 0
        sats = int(parts[7]) if parts[7] else 0
        hdop = float(parts[8]) if parts[8] else 99.9
        fix_type = NMEA_FIX_MAP.get(fix_quality, fix_quality)
        return GpsSample(timestamp=time.time(), fix_type=fix_type,
                         latitude=lat, longitude=lon, altitude=alt,
                         satellites=sats, hdop=hdop, source="ublox")
    except (ValueError, IndexError):
        return None


# ============================================================================
# u-blox シリアルリーダー（スレッド）
# ============================================================================
class UbloxReader:
    """u-blox F9P のシリアルポートから NMEA GGA を読み取るスレッド"""

    def __init__(self, port: str, baudrate: int = 38400):
        self.port = port
        self.baudrate = baudrate
        self._ser = None
        self._running = False
        self._thread = None
        self._lock = threading.Lock()
        self._latest = None
        self.samples: list[GpsSample] = []

    def start(self):
        import serial
        self._ser = serial.Serial(self.port, self.baudrate, timeout=1.0)
        self._ser.reset_input_buffer()
        self._running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        print(f"  [u-blox] シリアル接続開始: {self.port} @ {self.baudrate} bps")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        if self._ser and self._ser.is_open:
            self._ser.close()
        print(f"  [u-blox] 停止 (サンプル数: {len(self.samples)})")

    def _read_loop(self):
        while self._running:
            try:
                raw = self._ser.readline()
            except Exception:
                time.sleep(0.1)
                continue
            if not raw:
                continue
            try:
                line = raw.decode("ascii", errors="replace")
            except UnicodeDecodeError:
                continue
            sample = parse_nmea_gga(line)
            if sample is None:
                continue
            with self._lock:
                self._latest = sample
                self.samples.append(sample)

    def get_latest(self):
        with self._lock:
            return self._latest



# ============================================================================
# GCS WebSocket テレメトリポーラー
# ============================================================================
class GcsPoller:
    """GCS WebSocket から Pixhawk GPS テレメトリを取得"""

    def __init__(self, base_url: str = "http://localhost:8000", system_id: int = 1):
        self.base_url = base_url.rstrip("/")
        self.system_id = system_id
        self._latest = None
        self.samples: list[GpsSample] = []

    def poll(self, timeout_s: float = 5.0):
        result = {"gps": None}

        def _ws_fetch():
            try:
                url = self.base_url.replace("http://", "").replace("https://", "")
                if ":" in url:
                    host, port_str = url.rsplit(":", 1)
                    port = int(port_str)
                else:
                    host, port = url, 8000
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5.0)
                sock.connect((host, port))
                key = "dGhlIHNhbXBsZSBub25jZQ=="
                req = (f"GET /ws/telemetry HTTP/1.1\r\n"
                       f"Host: {host}:{port}\r\n"
                       f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
                       f"Sec-WebSocket-Key: {key}\r\n"
                       f"Sec-WebSocket-Version: 13\r\n\r\n")
                sock.sendall(req.encode())
                resp = b""
                while b"\r\n\r\n" not in resp:
                    chunk = sock.recv(4096)
                    if not chunk:
                        return
                    resp += chunk
                if b"101" not in resp:
                    return
                buf = b""
                deadline = time.monotonic() + timeout_s
                while time.monotonic() < deadline:
                    try:
                        sock.settimeout(1.0)
                        data = sock.recv(65535)
                        if data:
                            buf += data
                            for msg_str in self._ws_extract_text(buf):
                                try:
                                    msg = json.loads(msg_str)
                                    gps = self._extract_gps(msg)
                                    if gps:
                                        result["gps"] = gps
                                        return
                                except json.JSONDecodeError:
                                    continue
                    except socket.timeout:
                        continue
            except Exception:
                pass
            finally:
                try:
                    sock.close()
                except Exception:
                    pass

        t = threading.Thread(target=_ws_fetch, daemon=True)
        t.start()
        t.join(timeout=timeout_s + 2)
        gps = result["gps"]
        if gps:
            sample = GpsSample(
                timestamp=time.time(),
                fix_type=gps.get("fix_type", -1),
                latitude=gps.get("lat") or 0.0,
                longitude=gps.get("lon") or 0.0,
                altitude=gps.get("alt") or 0.0,
                satellites=gps.get("satellites", 0),
                hdop=gps.get("hdop") or 99.9,
                source="pixhawk",
            )
            self.samples.append(sample)
            self._latest = gps
            return sample
        return None

    @staticmethod
    def _ws_extract_text(buf: bytes) -> list[str]:
        msgs = []
        pos = 0
        while pos + 2 <= len(buf):
            opcode = buf[pos] & 0x0F
            if opcode not in (1, 2):
                pos += 1
                continue
            pos += 1
            if pos >= len(buf):
                break
            second = buf[pos]; pos += 1
            masked = (second & 0x80) != 0
            length = second & 0x7F
            if length == 126:
                if pos + 2 > len(buf):
                    break
                length = int.from_bytes(buf[pos:pos+2], "big"); pos += 2
            elif length == 127:
                if pos + 8 > len(buf):
                    break
                length = int.from_bytes(buf[pos:pos+8], "big"); pos += 8
            mask = b""
            if masked:
                if pos + 4 > len(buf):
                    break
                mask = buf[pos:pos+4]; pos += 4
            if pos + length > len(buf):
                break
            payload = buf[pos:pos+length]; pos += length
            if masked:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            try:
                msgs.append(payload.decode("utf-8"))
            except UnicodeDecodeError:
                pass
        return msgs

    def _extract_gps(self, msg: dict):
        drones = msg.get("drones", {})
        drone = drones.get(str(self.system_id))
        if drone is None and drones:
            drone = list(drones.values())[0]
        if drone is None:
            return None
        return drone.get("gps")


# ============================================================================
# シミュレーション（ハードウェアなしテスト用）
# ============================================================================
class SimulatedUblox:
    """u-blox基準局のシミュレーション — 固定基準点＋微小ノイズ"""
    def __init__(self, base_lat=35.6800000, base_lon=139.7600000, base_alt=40.0):
        self.base_lat = base_lat
        self.base_lon = base_lon
        self.base_alt = base_alt
        self.samples: list[GpsSample] = []

    def get_sample(self) -> GpsSample:
        s = GpsSample(
            timestamp=time.time(), fix_type=4,
            latitude=self.base_lat + random.gauss(0, 0.0000005),
            longitude=self.base_lon + random.gauss(0, 0.0000005),
            altitude=self.base_alt + random.gauss(0, 0.02),
            satellites=random.randint(18, 26),
            hdop=round(random.uniform(0.5, 0.9), 2),
            source="ublox",
        )
        self.samples.append(s)
        return s


class SimulatedPixhawk:
    """Pixhawk移動局のシミュレーション"""
    def __init__(self, base_lat=35.6800000, base_lon=139.7600000, base_alt=40.0,
                 offset_east_m=1.5, offset_north_m=-0.8, rtk_fixed=False):
        self.base_lat = base_lat
        self.base_lon = base_lon
        self.base_alt = base_alt
        self.offset_north_m = offset_north_m
        self.offset_east_m = offset_east_m
        self.rtk_fixed = rtk_fixed
        self.samples: list[GpsSample] = []
        self._cnt = 0

    def get_sample(self) -> GpsSample:
        self._cnt += 1
        lat_off = self.offset_north_m / METERS_PER_DEG_LAT
        lon_off = self.offset_east_m / (METERS_PER_DEG_LAT * math.cos(math.radians(self.base_lat)))
        fix_type = 6 if (self.rtk_fixed and self._cnt > 5) else (5 if self.rtk_fixed else 3)
        s = GpsSample(
            timestamp=time.time(), fix_type=fix_type,
            latitude=self.base_lat + lat_off + random.gauss(0, 0.0000010),
            longitude=self.base_lon + lon_off + random.gauss(0, 0.0000010),
            altitude=self.base_alt + random.gauss(0, 0.05),
            satellites=random.randint(15, 24),
            hdop=round(random.uniform(0.6, 1.2), 2),
            source="pixhawk",
        )
        self.samples.append(s)
        return s


# ============================================================================
# 地理計算ユーティリティ
# ============================================================================
def _lon_scale(lat_deg: float) -> float:
    return METERS_PER_DEG_LAT * math.cos(math.radians(lat_deg))


def compute_error(u: GpsSample, p: GpsSample) -> ErrorSample:
    dlat = (p.latitude - u.latitude) * METERS_PER_DEG_LAT
    dlon = (p.longitude - u.longitude) * _lon_scale(u.latitude)
    dalt = p.altitude - u.altitude
    hdist = math.sqrt(dlat ** 2 + dlon ** 2)
    return ErrorSample(
        timestamp=u.timestamp,
        fix_u=u.fix_type, sats_u=u.satellites,
        lat_u=u.latitude, lon_u=u.longitude, alt_u=u.altitude, hdop_u=u.hdop,
        fix_p=p.fix_type, sats_p=p.satellites,
        lat_p=p.latitude, lon_p=p.longitude, alt_p=p.altitude, hdop_p=p.hdop,
        delta_lat_m=dlat, delta_lon_m=dlon, delta_alt_m=dalt,
        horizontal_error_m=hdist,
    )



# ============================================================================
# メインコレクター
# ============================================================================
class RtkDataCollector:
    """RTK誤差データ収集・分析"""

    CSV_HEADER = [
        "timestamp", "fix_u", "sats_u", "lat_u", "lon_u", "alt_u", "hdop_u",
        "fix_p", "sats_p", "lat_p", "lon_p", "alt_p", "hdop_p",
        "delta_lat_m", "delta_lon_m", "delta_alt_m", "horizontal_error_m",
    ]

    def __init__(self, ublox_port="/dev/tty.usbmodem113301", ublox_baud=38400,
                 gcs_url="http://localhost:8000", system_id=1,
                 duration_sec=60, interval_sec=1.0, simulate=False,
                 output_csv=None, output_json=None):
        self.ublox_port = ublox_port
        self.ublox_baud = ublox_baud
        self.gcs_url = gcs_url
        self.system_id = system_id
        self.duration_sec = duration_sec
        self.interval_sec = interval_sec
        self.simulate = simulate
        self.output_csv = output_csv
        self.output_json = output_json
        self.errors: list[ErrorSample] = []
        self._interrupted = False
        signal.signal(signal.SIGINT, self._sigint_handler)

    def _sigint_handler(self, signum, frame):
        self._interrupted = True

    @staticmethod
    def _fmt_fix(ft: int) -> str:
        name = FIX_TYPE_NAMES.get(ft, f"UNK({ft})")
        return f"{name}({ft})"

    def _print_header(self, ublox_ok, gcs_ok):
        print()
        print("=" * 90)
        print("  RTK データコレクター")
        print("=" * 90)
        if self.simulate:
            print("  モード:       シミュレーション")
        else:
            print(f"  u-blox ポート: {self.ublox_port} @ {self.ublox_baud} bps")
            print(f"  GCS URL:       {self.gcs_url}")
            print(f"  System ID:     {self.system_id}")
        print(f"  収集時間:      {self.duration_sec} 秒")
        print(f"  サンプリング:  {self.interval_sec}s 間隔")
        print(f"  u-blox接続:    {'OK' if ublox_ok else 'NG'}")
        print(f"  GCS接続:       {'OK' if gcs_ok else 'NG'}")
        print("=" * 90)
        print(f"  {'#':>4} {'時刻':>7} {'Fix_U':>12} {'Sats':>5}  {'Fix_P':>12} {'Sats':>5}  {'水平誤差':>10} {'高度誤差':>10}")
        print("-" * 90)



    # ── ファイル保存 ──────────────────────────────────────────────
    def _save_csv(self):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = Path(self.output_csv) if self.output_csv else Path("logs") / f"rtk_error_{ts}.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        n = len(self.errors)
        with open(csv_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(self.CSV_HEADER)
            for e in self.errors:
                w.writerow([
                    f"{e.timestamp:.3f}", e.fix_u, e.sats_u,
                    f"{e.lat_u:.8f}", f"{e.lon_u:.8f}", f"{e.alt_u:.2f}", f"{e.hdop_u:.2f}",
                    e.fix_p, e.sats_p,
                    f"{e.lat_p:.8f}", f"{e.lon_p:.8f}", f"{e.alt_p:.2f}", f"{e.hdop_p:.2f}",
                    f"{e.delta_lat_m:.3f}", f"{e.delta_lon_m:.3f}",
                    f"{e.delta_alt_m:.3f}", f"{e.horizontal_error_m:.3f}",
                ])
        print(f"\n  [CSV保存] {csv_path} ({n} サンプル)")
        return csv_path, ts

    # ── 分析 ──────────────────────────────────────────────────────
    def _analyze(self, ts: str) -> Path:
        json_path = Path(self.output_json) if self.output_json else Path("logs") / f"rtk_analysis_{ts}.json"
        json_path.parent.mkdir(parents=True, exist_ok=True)
        n = len(self.errors)
        if n == 0:
            analysis = {"error": "no data collected"}
        else:
            fix_u_counts, fix_p_counts = {}, {}
            fix_p_timeline = []
            last_fix_p = -1
            h_errors, v_errors = [], []
            for e in self.errors:
                fix_u_counts[e.fix_u] = fix_u_counts.get(e.fix_u, 0) + 1
                fix_p_counts[e.fix_p] = fix_p_counts.get(e.fix_p, 0) + 1
                if e.fix_p != last_fix_p and e.fix_p >= 3:
                    fix_p_timeline.append({"timestamp": round(e.timestamp, 1),
                        "fix_type": e.fix_p, "fix_name": FIX_TYPE_NAMES.get(e.fix_p, "UNKNOWN")})
                    last_fix_p = e.fix_p
                h_errors.append(e.horizontal_error_m)
                v_errors.append(abs(e.delta_alt_m))

            def _stats(vals):
                if not vals:
                    return {}
                m = sum(vals) / len(vals)
                var = sum((x - m) ** 2 for x in vals) / (len(vals) - 1) if len(vals) > 1 else 0
                sv = sorted(vals)
                return {"count": len(vals), "mean": round(m, 3), "std": round(math.sqrt(var), 3),
                        "min": round(sv[0], 3), "max": round(sv[-1], 3),
                        "rms": round(math.sqrt(sum(x**2 for x in vals) / len(vals)), 3)}

            rtk_fixed_achieved = (6 in fix_p_counts)
            rtk_samples = [e for e in self.errors if e.fix_p == 6]
            analysis = {
                "timestamp": ts, "total_samples": n,
                "duration_sec": round(self.errors[-1].timestamp - self.errors[0].timestamp, 1) if n > 1 else 0,
                "rtk_fixed_achieved": rtk_fixed_achieved,
                "fix_u_distribution": {FIX_TYPE_NAMES.get(k, f"UNK({k})"): v
                                        for k, v in sorted(fix_u_counts.items())},
                "fix_p_distribution": {FIX_TYPE_NAMES.get(k, f"UNK({k})"): v
                                        for k, v in sorted(fix_p_counts.items())},
                "fix_p_timeline": fix_p_timeline,
                "horizontal_error_all": _stats(h_errors),
                "vertical_error_all": _stats(v_errors),
                "horizontal_error_rtk_fixed": _stats([e.horizontal_error_m for e in rtk_samples]),
                "vertical_error_rtk_fixed": _stats([abs(e.delta_alt_m) for e in rtk_samples]),
                "rtk_convergence_time_s": None,
            }
            if rtk_fixed_achieved:
                for e in self.errors:
                    if e.fix_p == 6:
                        analysis["rtk_convergence_time_s"] = round(e.timestamp - self.errors[0].timestamp, 1)
                        break

        with open(json_path, "w") as f:
            json.dump(analysis, f, indent=2, ensure_ascii=False)
        print(f"  [分析保存] {json_path}")
        self._print_analysis_summary(analysis)


    def _print_analysis_summary(self, a: dict):
        print(); print("=" * 60); print("  RTK 分析サマリー"); print("=" * 60)
        if "error" in a:
            print(f"  ERROR: {a['error']}"); return
        print(f"  サンプル数:      {a['total_samples']}")
        print(f"  収集時間:        {a['duration_sec']} 秒")
        rtk_ok = a["rtk_fixed_achieved"]
        print(f"  RTK Fixed達成:   {'YES' if rtk_ok else 'NO'}")
        if rtk_ok and a.get("rtk_convergence_time_s"):
            print(f"  RTK収束時間:     {a['rtk_convergence_time_s']} 秒")
        he = a.get("horizontal_error_all", {})
        ve = a.get("vertical_error_all", {})
        print(f"\n  [全Fix 水平誤差]  平均={he.get('mean','N/A')}m  std={he.get('std','N/A')}m  rms={he.get('rms','N/A')}m")
        print(f"  [全Fix 垂直誤差]  平均={ve.get('mean','N/A')}m  std={ve.get('std','N/A')}m  rms={ve.get('rms','N/A')}m")
        hrtk = a.get("horizontal_error_rtk_fixed", {})
        vrtk = a.get("vertical_error_rtk_fixed", {})
        if hrtk.get("count", 0) > 0:
            print(f"  [RTK Fixed 水平] 平均={hrtk.get('mean','N/A')}m  std={hrtk.get('std','N/A')}m  rms={hrtk.get('rms','N/A')}m")
        if vrtk.get("count", 0) > 0:
            print(f"  [RTK Fixed 垂直] 平均={vrtk.get('mean','N/A')}m  std={vrtk.get('std','N/A')}m")
        print(f"\n  Fix分布 (Pixhawk):")
        for name, cnt in a.get("fix_p_distribution", {}).items():
            pct = cnt / max(a["total_samples"], 1) * 100
            print(f"    {name:<18s} {cnt:5d}  ({pct:5.1f}%)  {'#' * int(pct / 2)}")
        tl = a.get("fix_p_timeline", [])
        if tl:
            print(f"\n  Fix遷移タイムライン:")
            for t in tl:
                print(f"    t={t['timestamp']:>6.1f}s → {t['fix_name']}")
        print("=" * 60)

    # ── メイン実行 ────────────────────────────────────────────────
    def run(self):
        ublox = None; gcs = None; sim_u = None; sim_p = None
        if self.simulate:
            sim_u = SimulatedUblox()
            sim_p = SimulatedPixhawk(rtk_fixed=True)
            ublox_ok = gcs_ok = True
        else:
            try:
                ublox = UbloxReader(self.ublox_port, self.ublox_baud)
                ublox.start()
                ublox_ok = True
            except Exception as e:
                print(f"  [ERROR] u-blox 接続失敗: {e}")
                ublox_ok = False
            gcs = GcsPoller(self.gcs_url, self.system_id)
            gcs_ok = gcs.poll(timeout_s=5.0) is not None
            if gcs_ok:
                print(f"  [GCS] Pixhawkテレメトリ取得成功 (SysID={self.system_id})")
            else:
                print(f"  [WARN] GCS未接続 — WebSocketを確認")

        if not ublox_ok and not gcs_ok:
            print("  [FATAL] データソースなし。終了。")
            return

        self._print_header(ublox_ok, gcs_ok)
        start_time = time.time()
        end_time = start_time + self.duration_sec
        sample_no = 0
        last_u = None

        try:
            while time.time() < end_time and not self._interrupted:
                t0 = time.time()
                # u-blox
                if self.simulate and sim_u:
                    u_s = sim_u.get_sample(); last_u = u_s
                elif ublox and ublox_ok:
                    u_s = ublox.get_latest()
                    if u_s:
                        last_u = u_s
                else:
                    u_s = None
                # Pixhawk
                if self.simulate and sim_p:
                    p_s = sim_p.get_sample()
                elif gcs and gcs_ok:
                    p_s = gcs.poll(timeout_s=3.0)
                else:
                    p_s = None

                if u_s and p_s:
                    e = compute_error(u_s, p_s)
                    self.errors.append(e)
                    sample_no += 1
                    elapsed = time.time() - start_time
                    print(f"  {sample_no:>4} {elapsed:>6.1f}s  {self._fmt_fix(e.fix_u):>12} {e.sats_u:>4}   {self._fmt_fix(e.fix_p):>12} {e.sats_p:>4}   {e.horizontal_error_m:>9.3f}m  {e.delta_alt_m:>9.3f}m")
                else:
                    missing = []
                    if not u_s: missing.append("u-blox")
                    if not p_s: missing.append("Pixhawk")
                    elapsed = time.time() - start_time
                    print(f"  {'---':>4} {elapsed:>6.1f}s  --- データ欠損: {', '.join(missing)}")

                dt = time.time() - t0
                if dt < self.interval_sec:
                    time.sleep(self.interval_sec - dt)

        except KeyboardInterrupt:
            self._interrupted = True
            print("\n  [INFO] Ctrl+C")

        finally:
            if ublox:
                ublox.stop()

        if not self.errors:
            print("\n  [WARN] 有効サンプルなし")
            return

        csv_path, ts = self._save_csv()
        self._analyze(ts)
        print(f"\nDone: {csv_path}")
        print(f"      logs/rtk_analysis_{ts}.json")


# ============================================================================
# CLI
# ============================================================================
def main():
    p = argparse.ArgumentParser(
        description="RTK Data Collector — u-blox基準局 + Pixhawk移動局 同時データ収集",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="使用例:\n  python rtk_tools/rtk_data_collector.py\n"
               "  python rtk_tools/rtk_data_collector.py --duration 120\n"
               "  python rtk_tools/rtk_data_collector.py --simulate")
    p.add_argument("--ublox-port", "-u", default="/dev/tty.usbmodem113301", help="u-blox シリアルポート")
    p.add_argument("--ublox-baud", type=int, default=38400, help="u-blox ボーレート")
    p.add_argument("--gcs-url", default="http://localhost:8000", help="GCS WebSocket URL")
    p.add_argument("--system-id", type=int, default=1, help="Pixhawk MAVLink System ID")
    p.add_argument("--duration", "-d", type=int, default=60, help="収集時間 [秒] (デフォルト: 60)")
    p.add_argument("--interval", type=float, default=1.0, help="サンプリング間隔 [秒]")
    p.add_argument("--simulate", "-s", action="store_true", help="シミュレーションモード")
    p.add_argument("--output-csv", "-o", default=None, help="CSV出力パス")
    p.add_argument("--output-json", "-j", default=None, help="JSON分析出力パス")
    args = p.parse_args()

    c = RtkDataCollector(
        ublox_port=args.ublox_port, ublox_baud=args.ublox_baud,
        gcs_url=args.gcs_url, system_id=args.system_id,
        duration_sec=args.duration, interval_sec=args.interval,
        simulate=args.simulate,
        output_csv=args.output_csv, output_json=args.output_json,
    )
    c.run()


if __name__ == "__main__":
    main()
