# TelemetryStore: システムIDごとの状態管理
import threading
import time

class TelemetryStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._data = {}
        self._last_seen = {}  # {system_id: timestamp}

    def update(self, system_id, message_type, payload):
        with self._lock:
            if system_id not in self._data:
                self._data[system_id] = {}
            self._data[system_id][message_type] = payload
            self._last_seen[system_id] = time.time()

            if message_type == 'NAMED_VALUE_FLOAT':
                field_name = getattr(payload, 'name', 'unknown')
                if isinstance(field_name, bytes):
                    field_name = field_name.decode('utf-8', errors='ignore')
                field_name = str(field_name)
                value = getattr(payload, 'value', 0.0)
                ts = getattr(payload, 'time_usec', 0)
                if not ts:
                    ts = int(time.time() * 1_000_000)

                nvf_history = self._data[system_id].setdefault('NAMED_VALUE_FLOAT_HISTORY', {})
                field_history = nvf_history.setdefault(field_name, [])
                field_history.append({
                    'value': value,
                    'timestamp': ts,
                    'payload': payload,
                })

                self._data[system_id].setdefault('NAMED_VALUE_FLOAT_BY_NAME', {})[field_name] = payload

    def get_last_seen(self, system_id):
        """Get the last update timestamp for a system_id. Returns None if never seen."""
        with self._lock:
            return self._last_seen.get(system_id)

    def get_last_seen_all(self):
        """Get dict of {system_id: timestamp} for all known drones."""
        with self._lock:
            return dict(self._last_seen)

    def get(self, system_id, message_type=None):
        with self._lock:
            if system_id not in self._data:
                return None
            if message_type:
                return self._data[system_id].get(message_type)
            return self._data[system_id]

    def get_all(self):
        with self._lock:
            return dict(self._data)
    
    def get_all_drone_ids(self):
        """Get list of all active drone system IDs"""
        with self._lock:
            return list(self._data.keys())
    
    def get_heartbeat(self, system_id):
        """Get HEARTBEAT message for a drone"""
        with self._lock:
            if system_id in self._data:
                return self._data[system_id].get('HEARTBEAT')
            return None
    
    def get_sys_status(self, system_id):
        """Get SYS_STATUS message for a drone (battery, GPS, etc.)"""
        with self._lock:
            if system_id in self._data:
                return self._data[system_id].get('SYS_STATUS')
            return None
    
    def get_gps_raw(self, system_id):
        """Get GPS_RAW_INT message for a drone (fix_type, satellites, hdop, etc.)"""
        with self._lock:
            if system_id in self._data:
                return self._data[system_id].get('GPS_RAW_INT')
            return None
    
    def get_global_position(self, system_id):
        """Get GLOBAL_POSITION_INT message for a drone (GPS coordinates)"""
        with self._lock:
            if system_id in self._data:
                return self._data[system_id].get('GLOBAL_POSITION_INT')
            return None

    def get_named_value_float_history(self, system_id):
        """Get NAMED_VALUE_FLOAT history grouped by field name."""
        with self._lock:
            if system_id in self._data:
                history = self._data[system_id].get('NAMED_VALUE_FLOAT_HISTORY', {})
                return {field: list(entries) for field, entries in history.items()}
            return {}

    def get_named_value_float_latest(self, system_id):
        """Get the latest NAMED_VALUE_FLOAT values by field name."""
        with self._lock:
            if system_id in self._data:
                latest = self._data[system_id].get('NAMED_VALUE_FLOAT_BY_NAME', {})
                return dict(latest)
            return {}

    def add_status_text(self, system_id: int, text: str, severity: int, name: str = ""):
        """Store a STATUSTEXT message in a ring buffer (max 20 entries per drone).

        Args:
            system_id: MAVLink system ID of the drone.
            text: The status text message.
            severity: MAVLink severity level (0=EMERGENCY .. 7=DEBUG).
            name: Optional source component name.
        """
        with self._lock:
            if system_id not in self._data:
                self._data[system_id] = {}
            ring = self._data[system_id].setdefault('STATUSTEXT', [])

            entry = {
                'text': text,
                'severity': severity,
                'name': name,
                'time': time.time(),
            }
            ring.append(entry)
            # Ring buffer: keep at most 50
            if len(ring) > 50:
                del ring[0 : len(ring) - 50]

    def get_status_texts(self, system_id: int, count: int = None):
        """Return the most recent STATUSTEXT entries for a drone.

        Args:
            system_id: MAVLink system ID.
            count: Number of latest entries to return (None = all).

        Returns:
            List of dicts [{text, severity, name, time}, ...], newest last.
        """
        with self._lock:
            if system_id not in self._data:
                return []
            ring = self._data[system_id].get('STATUSTEXT', [])
            if not ring:
                return []
            if count is not None and count > 0:
                try:
                    return list(ring)[-count:]
                except Exception:
                    return []
            try:
                return list(ring)
            except Exception:
                return []

