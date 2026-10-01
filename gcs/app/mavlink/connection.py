# MavlinkConnection: UDP/Serial入出力用（SSHトンネル再接続対応）
from __future__ import annotations

import socket
import threading
import logging
import yaml
import serial
import os
import time
import struct
import random

class MavlinkConnection:
    """
    MAVLink communication over UDP or Serial with connection stabilization.

    Features:
    - Packet loss detection and reporting
    - Automatic serial connection recovery with exponential backoff + jitter
    - UDP reconnection support (socket rebind on prolonged disconnect)
    - SSH tunnel auto-reconnect (via external process management)
    - Connection state tracking with structured event logging
    - Connection health monitoring (heartbeat-based)
    - Error event callbacks
    """
    # ── Reconnection defaults ─────────────────────────────────────────
    INITIAL_BACKOFF    = 1.0    # seconds
    MAX_BACKOFF        = 60.0   # seconds
    BACKOFF_MULTIPLIER = 1.5
    JITTER_FACTOR      = 0.1    # +/-10% random jitter
    RECONNECT_RESET_AFTER = 120.0  # reset backoff after this many seconds of stable connection

    def __init__(self, config_path):
        from pymavlink import mavutil
        self.logger = logging.getLogger(__name__)
        self.config = self._load_config(config_path)
        
        # Connection type (UDP or Serial)
        self.connection_type = self.config.get('connection_type', 'udp')
        
        # Connection state and error tracking
        self.is_connected = False
        self.connection_error = None
        self.packet_loss_count = 0
        self.packet_received_count = 0
        self.error_callbacks = []
        self._conn_state_callbacks = []  # (callback) for state transitions

        # Backoff state
        self._backoff_delay = self.INITIAL_BACKOFF
        self._last_connected_at = 0.0
        self._consecutive_failures = 0
        self._last_state_change = time.monotonic()
        self._connection_history: list[dict] = []  # max 100 entries

        # SSH tunnel management (for UDP-over-SSH setups)
        self._ssh_tunnel_proc = None
        self._ssh_tunnel_config = self.config.get('ssh_tunnel', {})

        if self.connection_type == 'serial':
            self._init_serial()
        else:
            self._init_udp()
        
        # MAVLink encode/decode object
        self.mav = mavutil.mavlink.MAVLink(bytearray())
        
        self.running = False
        self.recv_thread = None
        self.recv_callback = None
        self._tx_seq = 0
        self._health_check_interval = 10.0  # seconds between health log entries
        self._last_health_log = 0.0

    def _load_config(self, path):
        with open(path, 'r') as f:
            return yaml.safe_load(f)

    def register_error_callback(self, callback):
        """Register callback for connection errors. Signature: callback(error_type, message)"""
        self.error_callbacks.append(callback)

    def get_connection_status(self) -> dict:
        """Get current connection status and statistics"""
        return {
            'is_connected': self.is_connected,
            'connection_type': self.connection_type,
            'packet_received': self.packet_received_count,
            'packet_loss': self.packet_loss_count,
            'last_error': self.connection_error,
        }

    def _trigger_error_callback(self, error_type: str, message: str):
        """Trigger all registered error callbacks"""
        self.connection_error = message
        for callback in self.error_callbacks:
            try:
                callback(error_type, message)
            except Exception as e:
                self.logger.error(f"Error callback error: {e}")


    def start(self, recv_callback):
        self.running = True
        self.recv_callback = recv_callback
        self.recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self.recv_thread.start()
        
        if self.connection_type == 'serial':
            self.logger.info(f"Serial受信を開始: {self.serial_port}")
        else:
            self.logger.info(f"UDP受信を開始: 0.0.0.0:{self.udp_port}")

    # ── Connection state helpers ───────────────────────────────────────

    def _init_serial(self):
        self.serial_port = self.config.get('serial_port', '/dev/ttyACM0')
        self.serial_baudrate = self.config.get('serial_baudrate', 115200)
        self.serial_conn = None
        self.serial_error_count = 0
        self.serial_max_errors = self.config.get('serial_max_errors', 5)

    def _init_udp(self):
        self.udp_port = self.config.get('udp_listen_port', 14550)
        self.drones = self.config.get('drones', {})
        self._udp_timeout = self.config.get('udp_timeout', 5.0)
        self._max_timeouts = self.config.get('max_consecutive_timeouts', 30)
        self._bind_udp()

    def _bind_udp(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind(("0.0.0.0", self.udp_port))
            self.sock.settimeout(self._udp_timeout)
        except OSError as e:
            self.logger.error(f"UDP bind failed: {e}")
            raise

    def _change_state(self, connected: bool, reason: str = ""):
        prev = self.is_connected
        if prev == connected:
            return
        self.is_connected = connected
        self._last_state_change = time.monotonic()
        event = {"ts": time.time(), "from": prev, "to": connected,
                 "reason": reason, "bo": round(self._backoff_delay, 2)}
        self._connection_history.append(event)
        if len(self._connection_history) > 100:
            self._connection_history = self._connection_history[-100:]
        self.logger.log(
            logging.INFO if connected else logging.WARNING,
            "Conn: %s->%s (%s, bo=%.1fs, fail=%d)",
            "up" if prev else "down", "up" if connected else "down",
            reason, self._backoff_delay, self._consecutive_failures)
        for cb in self._conn_state_callbacks:
            try: cb(connected, reason)
            except Exception: pass

    def _next_backoff(self) -> float:
        self._consecutive_failures += 1
        delay = self.INITIAL_BACKOFF * (
            self.BACKOFF_MULTIPLIER ** (self._consecutive_failures - 1))
        delay = min(delay, self.MAX_BACKOFF)
        jitter = delay * self.JITTER_FACTOR * random.uniform(-1, 1)
        self._backoff_delay = max(0.1, delay + jitter)
        return self._backoff_delay

    def _reset_backoff(self):
        if self._backoff_delay > self.INITIAL_BACKOFF:
            self.logger.info("Backoff: %.1fs -> %.1fs",
                             self._backoff_delay, self.INITIAL_BACKOFF)
        self._backoff_delay = self.INITIAL_BACKOFF
        self._consecutive_failures = 0

    def _log_health(self):
        now = time.monotonic()
        if now - self._last_health_log < self._health_check_interval:
            return
        self._last_health_log = now
        self.logger.debug("Health: %s %s rx=%d loss=%d bo=%.1fs",
            "UP" if self.is_connected else "DOWN", self.connection_type,
            self.packet_received_count, self.packet_loss_count,
            self._backoff_delay)

    # ── SSH tunnel ────────────────────────────────────────────────────

    def _setup_ssh_tunnel(self) -> bool:
        cfg = self._ssh_tunnel_config
        if not cfg.get('enabled'):
            return True
        ssh_host = cfg.get('host', 'raspi')
        lport = cfg.get('local_port', 14551)
        rport = cfg.get('remote_port', 14550)
        self._teardown_ssh_tunnel()
        import subprocess
        try:
            self.logger.info("SSH tunnel: L%d:%d -> %s", lport, rport, ssh_host)
            self._ssh_tunnel_proc = subprocess.Popen(
                ["ssh", "-N", "-L", f"{lport}:localhost:{rport}",
                 "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15",
                 "-o", "ServerAliveCountMax=3",
                 "-o", "ExitOnForwardFailure=yes", ssh_host],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2.0)
            if self._ssh_tunnel_proc.poll() is not None:
                self.logger.error("SSH tunnel exit early rc=%d",
                                  self._ssh_tunnel_proc.returncode)
                return False
            self.logger.info("SSH tunnel OK")
            return True
        except FileNotFoundError:
            self.logger.error("ssh not found")
            return False
        except Exception as e:
            self.logger.error(f"SSH tunnel error: {e}")
            return False

    def _teardown_ssh_tunnel(self):
        if self._ssh_tunnel_proc:
            try: self._ssh_tunnel_proc.terminate()
            except Exception:
                try: self._ssh_tunnel_proc.kill()
                except Exception: pass
            self._ssh_tunnel_proc = None

    def _check_ssh_tunnel_alive(self) -> bool:
        if self._ssh_tunnel_proc is None:
            return not self._ssh_tunnel_config.get('enabled', False)
        return self._ssh_tunnel_proc.poll() is None

    # ── Receive loops ────────────────────────────────────────────────────

    def stop(self):
        self.running = False
        if self.recv_thread:
            self.recv_thread.join(timeout=3.0)
        self._teardown_ssh_tunnel()
        if self.connection_type == 'serial':
            if self.serial_conn:
                try: self.serial_conn.close()
                except Exception: pass
            self.logger.info("Serial stopped")
        else:
            try: self.sock.close()
            except Exception: pass
            self.logger.info("UDP stopped")

    def _recv_loop(self):
        if self.connection_type == 'serial':
            self._recv_loop_serial()
        else:
            self._recv_loop_udp()
    
    def _recv_loop_serial(self):
        """Serial receive with exponential backoff + jitter, state tracking."""
        last_attempt = 0.0
        while self.running:
            try:
                if not self.serial_conn or not self.serial_conn.is_open:
                    now = time.monotonic()
                    if now - last_attempt < self._backoff_delay:
                        threading.Event().wait(0.1)
                        continue
                    last_attempt = now
                    try:
                        self.serial_conn = serial.Serial(
                            self.serial_port, self.serial_baudrate, timeout=1)
                        self._change_state(True, "serial opened")
                        self.serial_error_count = 0
                        self._reset_backoff()
                        self.logger.info(f"Serial opened: {self.serial_port}")
                    except serial.SerialException as e:
                        self._change_state(False, f"open fail: {e}")
                        self._trigger_error_callback('SERIAL_OPEN_FAILED', str(e))
                        self._next_backoff()
                        continue

                if self.serial_conn.in_waiting > 0:
                    try:
                        data = self.serial_conn.read(self.serial_conn.in_waiting)
                        if data and self.recv_callback:
                            self.recv_callback(data, (self.serial_port, 0))
                            self.packet_received_count += 1
                            self._log_health()
                    except Exception as e:
                        self.logger.debug(f"Serial read error: {e}")
                else:
                    threading.Event().wait(0.01)
                    self._log_health()

            except serial.SerialException as e:
                self.serial_error_count += 1
                self.logger.warning(f"Serial error #{self.serial_error_count}: {e}")
                if self.serial_error_count >= self.serial_max_errors:
                    self._change_state(False, "serial critical")
                    self._trigger_error_callback(
                        'SERIAL_CRITICAL',
                        f"Serial failures: {self.serial_error_count}")
                self._close_serial()
                self._next_backoff()
            except Exception as e:
                self.logger.error(f"Serial unexpected: {e}")
                threading.Event().wait(0.05)

    def _close_serial(self):
        if self.serial_conn:
            try: self.serial_conn.close()
            except Exception: pass
        self.serial_conn = None

    
    def _recv_loop_udp(self):
        """UDP receive with SSH tunnel recovery and backoff."""
        timeout_count = 0
        last_tunnel_check = 0.0
        max_to = self._max_timeouts

        while self.running:
            try:
                data, addr = self.sock.recvfrom(4096)
                if self.recv_callback:
                    self.recv_callback(data, addr)
                self.packet_received_count += 1
                timeout_count = 0
                if not self.is_connected:
                    self._change_state(True, "data received")
                    self._reset_backoff()
                self._log_health()

            except socket.timeout:
                timeout_count += 1
                if timeout_count >= max_to:
                    was_up = self.is_connected
                    self._change_state(False, f"timeout x{timeout_count}")
                    self.packet_loss_count += 1
                    if was_up:
                        self.logger.warning("UDP timeout #%d", self.packet_loss_count)
                        self._trigger_error_callback(
                            'UDP_TIMEOUT',
                            f"UDP timeout #{self.packet_loss_count}")
                    # SSH tunnel check every 30s
                    now = time.monotonic()
                    if (now - last_tunnel_check > 30.0 and
                            self._ssh_tunnel_config.get('enabled')):
                        last_tunnel_check = now
                        if not self._check_ssh_tunnel_alive():
                            self.logger.warning("SSH tunnel dead; restarting")
                            self._setup_ssh_tunnel()
                    self._next_backoff()
                    threading.Event().wait(min(self._backoff_delay, 5.0))
                    timeout_count = 0

            except (ConnectionResetError, ConnectionRefusedError) as e:
                self._change_state(False, str(e))
                self.packet_loss_count += 1
                self.logger.warning(f"UDP disconnected: {e}")
                self._trigger_error_callback('UDP_DISCONNECTED', str(e))
                self._next_backoff()
                threading.Event().wait(min(self._backoff_delay, 3.0))

            except OSError as e:
                self.logger.error(f"UDP socket error: {e}")
                self._change_state(False, f"socket: {e}")
                self._trigger_error_callback('UDP_SOCKET_ERROR', str(e))
                try: self.sock.close()
                except Exception: pass
                try:
                    self._bind_udp()
                    self.logger.info("UDP socket rebound")
                except OSError:
                    self.logger.error("UDP rebind failed; backoff")
                    self._next_backoff()
                    threading.Event().wait(min(self._backoff_delay, 10.0))

            except Exception as e:
                self.logger.error(f"UDP error: {e}")
                self._change_state(False, f"error: {e}")
                self._trigger_error_callback('UDP_ERROR', str(e))
                threading.Event().wait(0.1)


    def send(self, system_id, data):
        """Send MAVLink data to the appropriate destination.
        
        Returns:
            bool: True if data was sent successfully, False otherwise.
        """
        if self.connection_type == 'serial':
            # For serial mode, send back to Pixhawk
            if not self.serial_conn or not self.serial_conn.is_open:
                self.logger.error(
                    f"Serial送信失敗: シリアルポートが開いていません (system_id={system_id}, "
                    f"port={self.serial_port}). Pixhawkが接続されているか確認してください。"
                )
                self._trigger_error_callback(
                    'SERIAL_SEND_FAILED',
                    f'Serial port {self.serial_port} is not open. Is Pixhawk connected?'
                )
                return False
            try:
                self.serial_conn.write(data)
                self.logger.debug(f"Serial送信: {len(data)} bytes")
                return True
            except Exception as e:
                self.logger.error(f"Serial送信エラー: {e}")
                self._trigger_error_callback('SERIAL_SEND_ERROR', str(e))
                return False
        else:
            # UDP mode: send to configured endpoint
            sent = False
            for drone_name, drone_info in self.drones.items():
                if drone_info.get('system_id') == system_id:
                    endpoint = drone_info.get('endpoint')
                    if endpoint:
                        ip, port = endpoint.split(":")
                        self.sock.sendto(data, (ip, int(port)))
                        self.logger.debug(f"送信: {ip}:{port} (system_id={system_id})")
                        sent = True
                    break
            if not sent:
                self.logger.error(
                    f"UDP送信失敗: system_id={system_id} に一致するドローンが設定ファイルにありません。"
                    f" 設定済みドローン: {list(self.drones.keys())}"
                )
            return sent

    def send_to_system(self, system_id, data):
        """
        Send MAVLink data to a specific system.
        Alias for send() for clarity.
        """
        self.send(system_id, data)

    def _next_seq(self):
        seq = self._tx_seq & 0xFF
        self._tx_seq = (self._tx_seq + 1) & 0xFF
        return seq

    def _crc16(self, data):
        """CRC-16 CCITT calculation used by the existing command sender."""
        crc = 0xFFFF
        for byte in data:
            crc ^= byte << 8
            for _ in range(8):
                crc <<= 1
                if crc & 0x10000:
                    crc ^= 0x1021
            crc &= 0xFFFF
        return crc

    def _build_mavlink_v2_frame(self, msgid: int, payload: bytes) -> bytes:
        frame = bytearray()
        frame.append(0xFD)
        frame.append(len(payload))
        frame.append(0x00)
        frame.append(0x00)
        frame.append(self._next_seq())
        frame.append(255)
        frame.append(0)
        frame.append(msgid & 0xFF)
        frame.append((msgid >> 8) & 0xFF)
        frame.append((msgid >> 16) & 0xFF)
        frame.extend(payload)
        crc = self._crc16(frame[1:])
        frame.append(crc & 0xFF)
        frame.append((crc >> 8) & 0xFF)
        return bytes(frame)

    def send_rc_channels_override(self, system_id, chan1_raw=1500, chan2_raw=1500,
                                    chan3_raw=1100, chan4_raw=1500,
                                    chan5_raw=0, chan6_raw=0, chan7_raw=0, chan8_raw=0):
        """Send RC_CHANNELS_OVERRIDE (msgid=70) to simulate RC input.
        
        Channel values: 1000-2000 (PWM), 0=ignore, UINT16_MAX=release.
        Defaults set all to center except throttle at minimum.
        """
        payload = struct.pack(
            '<HHHHHHHHHHHHHHHH',
            0,  # target_system (0=all)
            0,  # target_component (0=all)
            int(chan1_raw), int(chan2_raw), int(chan3_raw), int(chan4_raw),
            int(chan5_raw), int(chan6_raw), int(chan7_raw), int(chan8_raw),
            0, 0, 0, 0, 0, 0  # chan9-16 = 0
        )
        frame = self._build_mavlink_v2_frame(70, payload)
        self.send(system_id, frame)
        self.logger.debug(
            f"RC_CHANNELS_OVERRIDE sent: system_id={system_id}, "
            f"ch1={chan1_raw}, ch2={chan2_raw}, ch3={chan3_raw}, ch4={chan4_raw}"
        )

    def _send_encoded_frame(self, system_id, frame: bytes):
        self.send(system_id, frame)

    def send_command_long(self, system_id, component_id, command, confirmation=0, **params):
        """Send COMMAND_LONG using pymavlink's standard encoder (correct CRC)."""
        msg = self.mav.command_long_encode(
            target_system=system_id,
            target_component=component_id,
            command=command,
            confirmation=confirmation,
            param1=float(params.get('param1', 0.0)),
            param2=float(params.get('param2', 0.0)),
            param3=float(params.get('param3', 0.0)),
            param4=float(params.get('param4', 0.0)),
            param5=float(params.get('param5', 0.0)),
            param6=float(params.get('param6', 0.0)),
            param7=float(params.get('param7', 0.0)),
        )
        frame = msg.pack(self.mav)
        self._send_encoded_frame(system_id, frame)
        self.logger.debug(
            f"COMMAND_LONG sent: system_id={system_id}, component_id={component_id}, command={command}, params=[{params}], confirmation={confirmation}"
        )

    def send_set_position_target_local_ned(self, system_id, component_id, x, y, z, vx=0, vy=0, vz=0, yaw=0, yaw_rate=0, coordinate_frame=1, type_mask=None):
        """Send SET_POSITION_TARGET_LOCAL_NED as a MAVLink v2 frame."""
        if type_mask is None:
            # Use position targets by default and ignore velocity/acceleration/yaw-rate fields.
            type_mask = 0b0000111111000111

        payload = struct.pack(
            '<IBBBHfffffffffff',
            int(time.time() * 1000) & 0xFFFFFFFF,
            int(system_id),
            int(component_id),
            int(coordinate_frame),
            int(type_mask),
            float(x), float(y), float(z),
            float(vx), float(vy), float(vz),
            0.0, 0.0, 0.0,
            float(yaw),
            float(yaw_rate),
        )
        frame = self._build_mavlink_v2_frame(84, payload)
        self._send_encoded_frame(system_id, frame)
        self.logger.debug(
            f"SET_POSITION_TARGET_LOCAL_NED sent: system_id={system_id}, component_id={component_id}, pos=({x},{y},{z}), vel=({vx},{vy},{vz}), yaw={yaw}, yaw_rate={yaw_rate}"
        )

    def send_to_systems(self, system_ids, frame_builder):
        """Send a built frame to multiple systems."""
        for system_id in system_ids:
            frame = frame_builder(system_id)
            self._send_encoded_frame(system_id, frame)
