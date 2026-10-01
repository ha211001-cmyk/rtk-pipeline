#!/usr/bin/env python3
"""
GPSStatistics クラスの標準偏差・最大誤差計算、および
生データCSV・統計結果ファイル出力を既知データで検証するユニットテスト。

実行方法:
    cd raspberrypi/test
    python3 -m unittest test_gps_statistics -v
    または
    python3 test_gps_statistics.py
"""

import csv
import json
import math
import os
import statistics
import sys
import tempfile
import unittest

# 上位ディレクトリ（raspberrypi/）を sys.path に追加して gps_statistics を import する
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gps_statistics
from gps_statistics import GPSStatistics


def _haversine(lat1, lon1, lat2, lon2):
    """GPSStatistics.calculate_error_distance とは独立の距離計算（検証用）"""
    R = 6371000
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


class TestGPSStatistics(unittest.TestCase):
    """Welfordによる標準偏差・平均、メートル換算、最大誤差の検証"""

    def test_mean_and_std_dev_match_reference_stdev(self):
        stats = GPSStatistics()
        lats = [35.0, 35.0001, 35.0002]
        lons = [136.0, 136.0002, 136.0004]
        alts = [100.0, 100.2, 100.4]
        for lat, lon, alt in zip(lats, lons, alts):
            stats.add_sample(lat, lon, alt, quality=4, numSV=12)

        results = stats.calculate_statistics()

        # 平均値が stdlib statistics.mean と一致する
        self.assertAlmostEqual(results['mean_lat'], statistics.mean(lats), places=12)
        self.assertAlmostEqual(results['mean_lon'], statistics.mean(lons), places=12)
        self.assertAlmostEqual(results['mean_alt'], statistics.mean(alts), places=12)

        # 標本標準偏差（n-1）が stdlib statistics.stdev と一致する
        self.assertAlmostEqual(results['std_lat'], statistics.stdev(lats), places=12)
        self.assertAlmostEqual(results['std_lon'], statistics.stdev(lons), places=12)
        self.assertAlmostEqual(results['std_alt'], statistics.stdev(alts), places=12)

    def test_meter_conversion(self):
        stats = GPSStatistics()
        lats = [35.0, 35.0001, 35.0002]
        lons = [136.0, 136.0002, 136.0004]
        for lat, lon in zip(lats, lons):
            stats.add_sample(lat, lon, 100.0)

        results = stats.calculate_statistics()
        mean_lat = statistics.mean(lats)
        expected_std_lat_m = statistics.stdev(lats) * gps_statistics.METERS_PER_DEG_LAT
        expected_std_lon_m = (
            statistics.stdev(lons)
            * gps_statistics.METERS_PER_DEG_LAT
            * math.cos(math.radians(mean_lat))
        )

        self.assertAlmostEqual(results['std_lat_m'], expected_std_lat_m, places=6)
        self.assertAlmostEqual(results['std_lon_m'], expected_std_lon_m, places=6)

    def test_max_error_and_distance_std_dev(self):
        stats = GPSStatistics()
        points = [
            (36.0, 136.0, 100.0),
            (36.0, 136.0, 100.0),
            (36.0002, 136.0, 100.0),  # 平均緯度から最も離れた点
        ]
        for lat, lon, alt in points:
            stats.add_sample(lat, lon, alt)

        results = stats.calculate_statistics()
        mean_lat = results['mean_lat']
        mean_lon = results['mean_lon']

        distances = [_haversine(lat, lon, mean_lat, mean_lon) for lat, lon, alt in points]
        expected_max = max(distances)
        self.assertAlmostEqual(results['max_error'], expected_max, places=6)

        # 距離の標本標準偏差（n-1）
        mean_d = sum(distances) / len(distances)
        expected_std_d = math.sqrt(
            sum((d - mean_d) ** 2 for d in distances) / (len(distances) - 1)
        )
        self.assertAlmostEqual(results['std_distance'], expected_std_d, places=6)

    def test_single_sample(self):
        stats = GPSStatistics()
        stats.add_sample(36.0, 136.0, 100.0, quality=1, numSV=8)
        results = stats.calculate_statistics()
        self.assertIsNotNone(results)
        self.assertEqual(results['valid_samples'], 1)
        # n=1 のとき自由度 0 なので標準偏差は 0
        self.assertEqual(results['std_lat'], 0.0)
        self.assertEqual(results['std_lon'], 0.0)
        self.assertEqual(results['std_alt'], 0.0)

    def test_no_sample_returns_none(self):
        stats = GPSStatistics()
        self.assertIsNone(stats.calculate_statistics())

    def test_quality_and_rtk_counting(self):
        stats = GPSStatistics()
        for i in range(5):
            stats.add_sample(36.0 + i * 0.00001, 136.0, 100.0, quality=4, numSV=15)
        for i in range(3):
            stats.add_sample(36.0 + i * 0.00001, 136.0, 100.0, quality=5, numSV=12)
        stats.add_sample(36.0, 136.0, 100.0, quality=1, numSV=8)

        self.assertEqual(stats.n, 9)
        self.assertEqual(stats.rtk_fix_samples, 5)
        self.assertEqual(stats.rtk_float_samples, 3)
        self.assertEqual(stats.max_satellites, 15)
        self.assertEqual(stats.quality_counts[4], 5)
        self.assertEqual(stats.quality_counts[5], 3)
        self.assertEqual(stats.quality_counts[1], 1)


class TestCSVLogger(unittest.TestCase):
    """生データCSVロガーのヘッダ・行書き出しの検証"""

    def test_csv_logger_writes_header_and_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'gps_log_test.csv')
            logger = gps_statistics.CSVLogger(path)
            logger.write_row([
                '2026-09-27 12:00:00.000000', '12:00:00',
                '36.00000000', '136.00000000', '100.000',
                4, 'RTK Fixed', 12, '0.57', '$GNGGA,...',
            ])
            logger.close()

            with open(path, newline='', encoding='utf-8') as f:
                rows = list(csv.reader(f))

            self.assertEqual(rows[0], gps_statistics.CSV_HEADER)
            self.assertEqual(len(rows), 2)  # ヘッダ + 1行
            self.assertEqual(rows[1][0], '2026-09-27 12:00:00.000000')
            self.assertEqual(rows[1][5], '4')
            self.assertEqual(rows[1][6], 'RTK Fixed')
            self.assertEqual(rows[1][7], '12')
            self.assertEqual(rows[1][8], '0.57')


class TestSaveResults(unittest.TestCase):
    """統計結果の JSON / TXT ファイル出力の検証"""

    def test_save_results_writes_json_and_txt(self):
        stats = GPSStatistics()
        for lat, lon, alt in [
            (36.0, 136.0, 100.0),
            (36.0001, 136.0001, 100.2),
            (36.0002, 136.0002, 100.4),
        ]:
            stats.add_sample(lat, lon, alt, quality=4, numSV=12)

        results = stats.calculate_statistics()
        with tempfile.TemporaryDirectory() as tmp:
            json_path, txt_path = gps_statistics.save_results(stats, results, output_dir=tmp)

            self.assertTrue(os.path.exists(json_path))
            self.assertTrue(os.path.exists(txt_path))

            with open(json_path, encoding='utf-8') as f:
                data = json.load(f)
            self.assertEqual(data['valid_samples'], 3)
            self.assertAlmostEqual(data['std_lat_m'], results['std_lat_m'], places=6)
            self.assertAlmostEqual(data['max_error_m'], results['max_error'], places=6)
            self.assertEqual(data['quality_counts']['4'], 3)

            with open(txt_path, encoding='utf-8') as f:
                txt = f.read()
            self.assertIn('有効サンプル数', txt)
            self.assertIn('標準偏差（メートル換算）', txt)
            self.assertIn('最大誤差', txt)


if __name__ == '__main__':
    unittest.main(verbosity=2)
