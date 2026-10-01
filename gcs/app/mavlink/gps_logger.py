"""
GPS Logger — MAVLink GPS メッセージの継続的収集と CSV/JSON 保存

【収集対象メッセージ】
  - GPS_RAW_INT: fix_type, lat, lon, alt, eph(hdop), epv(vdop), satellites_visible
  - GPS_GLOBAL_ORIGIN: 基地局アンカー位置
  - GPS_RTK / GPS2_RTK: RTKベースライン情報
  - GLOBAL_POSITION_INT: グローバル位置（補助）

【データソース識別】
  - system_id ベースで Base F9P と Rover F9P を区別
  - config で base_system_id / rover_system_id を指定可能

【出力形式】
  - CSV: logs/gps_{source}_{YYYYMMDD}.csv
  - JSON Lines: logs/gps_{source}_{YYYYMMDD}.jsonl
"""

import csv
import json
import logging
import os
import time
from datetime import datetime, timezone
from threading import Lock
from typing import Optional, Set

logger = logging.getLogger("gps_logger")

FIX_TYPE_NAMES: dict[int, str] = {
    0: "NO_GPS", 1: "NO_FIX", 2: "2D_FIX", 3: "3D_FIX",
    4: "DGPS", 5: "RTK_FLOAT", 6: "RTK_FIXED",
    7: "STATIC", 8: "PPP",
}

CSV_HEADER = [
    "timestamp_utc", "timestamp_unix",
    "source", "system_id", "msg_type",
    "fix_type", "fix_name",
    "lat", "lon", "alt_msl_mm",
    "hdop_cm", "vdop_cm",
    "satellites_visible",
    "vel_cm_s", "cog_cdeg", "yaw_deg",
    "rtk_receiver_id", "rtk_health",
    "rtk_rate_hz", "rtk_nsats",
    "baseline_a_mm", "baseline_b_mm", "baseline_c_mm",
    "accuracy_mm", "iar_num_hypotheses",
    "origin_lat", "origin_lon", "origin_alt_mm",
]


class GpsLogger:
    """MAVLink GPS message continuous logger with CSV/JSONL output."""

    def __init__(
        self,
        base_system_ids: Optional[Set[int]] = None,
        rover_system_ids: Optional[Set[int]] = None,
        log_dir: str = "logs",
        csv_enabled: bool = True,
        jsonl_enabled: bool = True,
        flush_interval: float = 5.0,
    ):
        self.base_system_ids = base_system_ids or set()
        self.rover_system_ids = rover_system_ids or set()
        self.log_dir = log_dir
        self.csv_enabled = csv_enabled
        self.jsonl_enabled = jsonl_enabled
        self.flush_interval = flush_interval

        self._lock = Lock()
        self._csv_files: dict[str, object] = {}
        self._csv_writers: dict[str, object] = {}
        self._jsonl_files: dict[str, object] = {}
        self._last_flush: dict[str, float] = {}
        self._current_date: dict[str, str] = {}
        self._record_count: dict[str, int] = {}
        self._auto_classified: dict[int, str] = {}
        self._seen_autopilot: dict[int, int] = {}

        os.makedirs(self.log_dir, exist_ok=True)
        logger.info(
            "GpsLogger init: base=%s rover=%s csv=%s jsonl=%s",
            self.base_system_ids, self.rover_system_ids,
            csv_enabled, jsonl_enabled)

    # -- public API --------------------------------------------------------

    def on_gps_message(self, system_id: int, msg) -> None:
        msg_type = msg.get_type()
        if msg_type not in (
            "GPS_RAW_INT", "GPS_GLOBAL_ORIGIN",
            "GPS_RTK", "GPS2_RTK", "GLOBAL_POSITION_INT",
        ):
            return
        source = self._classify_system(system_id)
        record = self._build_record(system_id, source, msg_type, msg)
        self._write_record(source, record)

    def on_heartbeat(self, system_id: int, msg) -> None:
        try:
            self._seen_autopilot[system_id] = getattr(msg, "autopilot", -1)
        except Exception:
            pass

    def flush_all(self) -> None:
        with self._lock:
            for fh in list(self._csv_files.values()):
                try: fh.flush()
                except Exception: pass
            for fh in list(self._jsonl_files.values()):
                try: fh.flush()
                except Exception: pass

    def close(self) -> None:
        with self._lock:
            for fh in list(self._csv_files.values()):
                try: fh.close()
                except Exception: pass
            self._csv_files.clear()
            self._csv_writers.clear()
            for fh in list(self._jsonl_files.values()):
                try: fh.close()
                except Exception: pass
            self._jsonl_files.clear()
        logger.info("GpsLogger closed: records=%s", dict(self._record_count))

    def get_stats(self) -> dict:
        with self._lock:
            return {
                "record_count": dict(self._record_count),
                "auto_classified": dict(self._auto_classified),
                "base_ids": list(self.base_system_ids),
                "rover_ids": list(self.rover_system_ids),
            }

    # -- classification ----------------------------------------------------

    def _classify_system(self, system_id: int) -> str:
        if system_id in self.base_system_ids:
            return "base"
        if system_id in self.rover_system_ids:
            return "rover"
        if system_id in self._auto_classified:
            return self._auto_classified[system_id]
        classification = "rover"
        self._auto_classified[system_id] = classification
        logger.info("GpsLogger: auto-classified sysid=%d as '%s'",
                     system_id, classification)
        return classification

    # -- record building ---------------------------------------------------

    def _build_record(self, system_id: int, source: str,
                      msg_type: str, msg) -> dict:
        now = time.time()
        rec = {
            "timestamp_utc": datetime.fromtimestamp(
                now, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "timestamp_unix": f"{now:.6f}",
            "source": source, "system_id": system_id, "msg_type": msg_type,
            "fix_type": -1, "fix_name": "N/A",
            "lat": "", "lon": "", "alt_msl_mm": "",
            "hdop_cm": "", "vdop_cm": "", "satellites_visible": "",
            "vel_cm_s": "", "cog_cdeg": "", "yaw_deg": "",
            "rtk_receiver_id": "", "rtk_health": "",
            "rtk_rate_hz": "", "rtk_nsats": "",
            "baseline_a_mm": "", "baseline_b_mm": "",
            "baseline_c_mm": "", "accuracy_mm": "",
            "iar_num_hypotheses": "",
            "origin_lat": "", "origin_lon": "", "origin_alt_mm": "",
        }
        try:
            if msg_type == "GPS_RAW_INT":
                rec.update(self._extract_gps_raw_int(msg))
            elif msg_type == "GPS_GLOBAL_ORIGIN":
                rec["origin_lat"] = getattr(msg, "latitude", 0)
                rec["origin_lon"] = getattr(msg, "longitude", 0)
                rec["origin_alt_mm"] = getattr(msg, "altitude", 0)
            elif msg_type in ("GPS_RTK", "GPS2_RTK"):
                rec.update(self._extract_gps_rtk(msg))
            elif msg_type == "GLOBAL_POSITION_INT":
                rec["lat"] = getattr(msg, "lat", 0)
                rec["lon"] = getattr(msg, "lon", 0)
                rec["alt_msl_mm"] = getattr(msg, "alt", 0)
        except Exception as e:
            logger.debug("GpsLogger build error %s: %s", msg_type, e)
        return rec

    @staticmethod
    def _extract_gps_raw_int(msg) -> dict:
        ft = getattr(msg, "fix_type", -1)
        return {
            "fix_type": ft,
            "fix_name": FIX_TYPE_NAMES.get(ft, f"UNKNOWN({ft})"),
            "lat": getattr(msg, "lat", 0),
            "lon": getattr(msg, "lon", 0),
            "alt_msl_mm": getattr(msg, "alt", 0),
            "hdop_cm": _safe(getattr(msg, "eph", None)),
            "vdop_cm": _safe(getattr(msg, "epv", None)),
            "satellites_visible": _safe(
                getattr(msg, "satellites_visible", None)),
            "vel_cm_s": _safe(getattr(msg, "vel", None)),
            "cog_cdeg": _safe(getattr(msg, "cog", None)),
            "yaw_deg": _safe(getattr(msg, "yaw", None)),
        }

    @staticmethod
    def _extract_gps_rtk(msg) -> dict:
        return {
            "rtk_receiver_id": _safe(getattr(msg, "rtk_receiver_id", None)),
            "rtk_health": _safe(getattr(msg, "rtk_health", None)),
            "rtk_rate_hz": _safe(getattr(msg, "rtk_rate", None)),
            "rtk_nsats": _safe(getattr(msg, "nsats", None)),
            "baseline_a_mm": _safe(getattr(msg, "baseline_a_mm", None)),
            "baseline_b_mm": _safe(getattr(msg, "baseline_b_mm", None)),
            "baseline_c_mm": _safe(getattr(msg, "baseline_c_mm", None)),
            "accuracy_mm": _safe(getattr(msg, "accuracy", None)),
            "iar_num_hypotheses": _safe(
                getattr(msg, "iar_num_hypotheses", None)),
        }

    # -- file I/O ----------------------------------------------------------

    def _write_record(self, source: str, record: dict) -> None:
        today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        with self._lock:
            self._rotate_if_needed(source, today_str)
            if self.csv_enabled:
                self._write_csv(source, record)
            if self.jsonl_enabled:
                self._write_jsonl(source, record)
            self._record_count[source] = self._record_count.get(source, 0) + 1
            now = time.monotonic()
            if now - self._last_flush.get(source, 0) >= self.flush_interval:
                self._flush_source(source)

    def _rotate_if_needed(self, source: str, today_str: str) -> None:
        if self._current_date.get(source) == today_str:
            return
        self._close_source(source)
        self._current_date[source] = today_str
        logger.info("GpsLogger: rotated %s -> %s", source, today_str)

    def _get_path(self, source: str, ext: str) -> str:
        date_str = self._current_date.get(
            source, datetime.now(timezone.utc).strftime("%Y%m%d"))
        return os.path.join(self.log_dir, f"gps_{source}_{date_str}.{ext}")

    def _write_csv(self, source: str, record: dict) -> None:
        if source not in self._csv_files:
            path = self._get_path(source, "csv")
            is_new = not os.path.exists(path) or os.path.getsize(path) == 0
            fh = open(path, "a", newline="")
            writer = csv.writer(fh)
            if is_new:
                writer.writerow(CSV_HEADER)
                fh.flush()
            self._csv_files[source] = fh
            self._csv_writers[source] = writer
            logger.info("GpsLogger: CSV -> %s", path)
        self._csv_writers[source].writerow(
            [record.get(col, "") for col in CSV_HEADER])

    def _write_jsonl(self, source: str, record: dict) -> None:
        if source not in self._jsonl_files:
            path = self._get_path(source, "jsonl")
            fh = open(path, "a")
            self._jsonl_files[source] = fh
            logger.info("GpsLogger: JSONL -> %s", path)
        self._jsonl_files[source].write(
            json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def _flush_source(self, source: str) -> None:
        if source in self._csv_files:
            try: self._csv_files[source].flush()
            except Exception: pass
        if source in self._jsonl_files:
            try: self._jsonl_files[source].flush()
            except Exception: pass
        self._last_flush[source] = time.monotonic()

    def _close_source(self, source: str) -> None:
        if source in self._csv_files:
            try: self._csv_files[source].close()
            except Exception: pass
            del self._csv_files[source]
        if source in self._csv_writers:
            del self._csv_writers[source]
        if source in self._jsonl_files:
            try: self._jsonl_files[source].close()
            except Exception: pass
            del self._jsonl_files[source]


def _safe(value) -> str:
    if value is None:
        return ""
    try:
        v = int(value)
        if v >= 65535:
            return ""
        return str(v)
    except (ValueError, TypeError):
        return ""
