#!/usr/bin/env python3
"""
Position Observer - 単独測位で基地局座標を取得するモジュール

F9PのNMEA GGA出力から指定秒数分の位置情報を収集し、
平均座標を基地局の固定座標として使用する。

Usage:
    from position_observer import PositionObserver

    observer = PositionObserver("/dev/ttyACM2", baudrate=115200)
    result = observer.observe(duration_sec=60)
    # result = {'lat': 36.0751418, 'lon': 136.2133477, 'alt': 44.80, 'samples': 600}
"""

import logging
import time
from typing import Optional

import serial


class PositionObserver:
    """単独測位で基地局座標を取得するクラス

    F9PのNMEA GGA出力から指定秒数分の位置情報を収集し、
    平均座標を基地局の固定座標として使用する。

    Args:
        serial_port: F9Pのシリアルポートパス (例: /dev/ttyACM2)
        baudrate: シリアル通信ボーレート (デフォルト: 115200)
        logger: ロガーインスタンス
    """

    def __init__(self, serial_port: str, baudrate: int = 115200,
                 logger: Optional[logging.Logger] = None):
        self.serial_port = serial_port
        self.baudrate = baudrate
        self.log = logger or logging.getLogger("PositionObserver")

    def observe(self, duration_sec: int = 60) -> Optional[dict]:
        """指定秒数単独測位し、平均座標を返す

        Args:
            duration_sec: 測位時間 (秒)

        Returns:
            {
                'lat': float,      # 平均緯度 (10進数度)
                'lon': float,      # 平均経度 (10進数度)
                'alt': float,      # 平均高度 (m, HAE)
                'samples': int,    # 有効サンプル数
                'std_lat': float,  # 緯度標準偏差 (m)
                'std_lon': float,  # 経度標準偏差 (m)
                'std_alt': float,  # 高度標準偏差 (m)
            }
            または失敗時はNone
        """
        self.log.info(f"単独測位開始: {duration_sec}秒間 ({self.serial_port})")

        ser = None
        try:
            ser = serial.Serial(self.serial_port, self.baudrate, timeout=1.0)
            time.sleep(0.5)
            ser.reset_input_buffer()

            lats = []
            lons = []
            alts = []
            start_time = time.time()
            last_print = start_time

            while time.time() - start_time < duration_sec:
                try:
                    line = ser.readline()
                    if not line:
                        continue

                    line_str = line.decode('ascii', errors='replace').strip()

                    # $GNGGA 行を解析
                    if '$GNGGA' in line_str or '$GPGGA' in line_str:
                        gga = self._parse_gga(line_str)
                        if gga and gga['fix'] >= 1:  # GPS Fix以上
                            lats.append(gga['lat'])
                            lons.append(gga['lon'])
                            alts.append(gga['alt'])

                            # 進捗表示 (5秒ごと)
                            now = time.time()
                            if now - last_print >= 5:
                                elapsed = now - start_time
                                remaining = duration_sec - elapsed
                                self.log.info(
                                    f"  測位中... 経過: {elapsed:.0f}s / 残り: {remaining:.0f}s | "
                                    f"サンプル: {len(lats)} | "
                                    f"現在: lat={gga['lat']:.7f} lon={gga['lon']:.7f} alt={gga['alt']:.1f}m")
                                last_print = now

                except (serial.SerialException, OSError) as e:
                    self.log.warning(f"シリアル読み取りエラー: {e}")
                    time.sleep(0.5)
                    continue

            if len(lats) < 10:
                self.log.error(f"有効サンプル不足: {len(lats)} < 10")
                return None

            # 平均値計算
            import statistics
            avg_lat = statistics.mean(lats)
            avg_lon = statistics.mean(lons)
            avg_alt = statistics.mean(alts)

            # 標準偏差計算 (度 → メートル換算)
            # 緯度1度 ≒ 111,320m, 経度1度 ≒ 111,320m * cos(lat)
            import math
            cos_lat = math.cos(math.radians(avg_lat))
            std_lat = statistics.stdev(lats) * 111320.0 if len(lats) > 1 else 0.0
            std_lon = statistics.stdev(lons) * 111320.0 * cos_lat if len(lons) > 1 else 0.0
            std_alt = statistics.stdev(alts) if len(alts) > 1 else 0.0

            result = {
                'lat': avg_lat,
                'lon': avg_lon,
                'alt': avg_alt,
                'samples': len(lats),
                'std_lat': std_lat,
                'std_lon': std_lon,
                'std_alt': std_alt,
            }

            self.log.info(
                f"単独測位完了: lat={avg_lat:.7f} lon={avg_lon:.7f} alt={avg_alt:.2f}m "
                f"(samples={len(lats)}, std_lat={std_lat:.3f}m, std_lon={std_lon:.3f}m, "
                f"std_alt={std_alt:.3f}m)")

            return result

        except serial.SerialException as e:
            self.log.error(f"シリアルポートオープン失敗: {e}")
            return None
        except Exception as e:
            self.log.error(f"単独測位エラー: {type(e).__name__}: {e}")
            return None
        finally:
            if ser and ser.is_open:
                ser.close()

    def _parse_gga(self, sentence: str) -> Optional[dict]:
        """NMEA $GNGGA センテンスを解析する

        Args:
            sentence: NMEA GGAセンテンス文字列

        Returns:
            {
                'lat': float,   # 緯度 (10進数度)
                'lon': float,   # 経度 (10進数度)
                'alt': float,   # 高度 (m, HAE)
                'fix': int,     # Fix quality
                'sats': int,    # 衛星数
                'hdop': float,  # HDOP
            }
            または解析失敗時はNone
        """
        try:
            # チェックサム検証
            if '*' in sentence:
                body, checksum_str = sentence.split('*')
                body = body.lstrip('$')
                checksum = 0
                for char in body:
                    checksum ^= ord(char)
                if checksum != int(checksum_str, 16):
                    return None
            else:
                body = sentence.lstrip('$')

            parts = body.split(',')
            if len(parts) < 15:
                return None

            # 時刻
            time_str = parts[1]

            # 緯度 (DDMM.MMMM)
            lat_str = parts[2]
            lat_dir = parts[3]
            if not lat_str or not lat_dir:
                return None
            lat_raw = float(lat_str)
            lat_deg = int(lat_raw / 100)
            lat_min = lat_raw - lat_deg * 100
            lat = lat_deg + lat_min / 60.0
            if lat_dir == 'S':
                lat = -lat

            # 経度 (DDDMM.MMMM)
            lon_str = parts[4]
            lon_dir = parts[5]
            if not lon_str or not lon_dir:
                return None
            lon_raw = float(lon_str)
            lon_deg = int(lon_raw / 100)
            lon_min = lon_raw - lon_deg * 100
            lon = lon_deg + lon_min / 60.0
            if lon_dir == 'W':
                lon = -lon

            # Fix quality
            fix = int(parts[6]) if parts[6] else 0

            # 衛星数
            sats = int(parts[7]) if parts[7] else 0

            # HDOP
            hdop = float(parts[8]) if parts[8] else 0.0

            # 高度 (HAE)
            alt = float(parts[9]) if parts[9] else 0.0

            return {
                'lat': lat,
                'lon': lon,
                'alt': alt,
                'fix': fix,
                'sats': sats,
                'hdop': hdop,
            }

        except (ValueError, IndexError) as e:
            self.log.debug(f"GGA解析エラー: {e} | sentence={sentence[:80]}")
            return None