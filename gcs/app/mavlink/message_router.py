# MessageRouter: 受信ループとディスパッチ
import threading
import logging
from pymavlink import mavutil

from gcs.app.display import fix_name  # noqa: E402

class MessageRouter:
    def __init__(self, mavlink_conn, telemetry_store,
                 command_dispatcher=None, gps_logger=None):
        self.logger = logging.getLogger(__name__)
        self.mavlink_conn = mavlink_conn
        self.telemetry_store = telemetry_store
        self.command_dispatcher = command_dispatcher
        self.gps_logger = gps_logger
        self.running = False
        self.thread = None
        # 受信ループ開始前に MAVLink デコーダを用意しておく（開始との競合を回避）
        self.mav = mavutil.mavlink.MAVLink(None)

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self.logger.info("MessageRouter受信ループ開始")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join()
        self.logger.info("MessageRouter受信ループ停止")

    def _run(self):
        def callback(data, addr):
            # Parse MAVLink message
            try:
                self._parse_mavlink_message(data, addr)
            except Exception as e:
                self.logger.error(f"Error parsing MAVLink message: {e}")
        
        self.mavlink_conn.start(callback)
        
        # Periodically check for command timeouts
        while self.running:
            if self.command_dispatcher:
                try:
                    self.command_dispatcher.check_timeouts()
                except Exception as e:
                    self.logger.error(f"Error checking command timeouts: {e}")
            threading.Event().wait(0.5)  # Check timeouts every 500ms

    def _parse_mavlink_message(self, data, addr):
        """Parse incoming MAVLink message and route to appropriate handler."""
        try:

            mav = mavutil.mavlink.MAVLink(None)
            
            # Attempt to unpack message using correct API
            msgs = None
            try:
                # Try newer API first (parse_buffer for bytes)
                msgs = self.mav.parse_buffer(data)
            except (AttributeError, TypeError):
                try:
                    # Fallback to parse_char_array
                    msgs = mav.parse_char_array(data)
                except (AttributeError, TypeError):
                    # Last resort: try unpacking with struct
                    if len(data) < 8:
                        return
                    # Parse as raw MAVLink 1.0 frame
                    try:
                        msgs = mav.decode(data)
                    except:
                        return
            
            if not msgs:
                return
            
            # Handle both single message and list of messages
            if not isinstance(msgs, list):
                msgs = [msgs]
            
            for msg in msgs:
                if not msg:
                    continue
                
                # Route message based on type
                msg_type = msg.get_type()
                system_id = msg.get_srcSystem()
                
                # Enhanced logging for GPS_RAW_INT with fix_type
                if msg_type == 'GPS_RAW_INT':
                    fix_type = getattr(msg, 'fix_type', -1)
                    fix_name = self._gps_fix_type_name(fix_type)
                    num_sats = getattr(msg, 'satellites_visible', 0)
                    lat = getattr(msg, 'lat', 0) / 1e7
                    lon = getattr(msg, 'lon', 0) / 1e7
                    alt = getattr(msg, 'alt', 0) / 1000.0
                    hdop = getattr(msg, 'eph', 0) / 100.0  # HDOP in cm -> m
                    self.logger.info(
                        f"GPS_RAW from sys={system_id}: fix={fix_type}({fix_name}), "
                        f"sats={num_sats}, lat={lat:.6f}, lon={lon:.6f}, "
                        f"alt={alt:.2f}m, hdop={hdop:.2f}"
                    )
                elif msg_type in ('GPS_RTK', 'GPS2_RTK'):
                    rtk_id = getattr(msg, 'rtk_receiver_id', 0)
                    rtk_health = getattr(msg, 'rtk_health', 0xff)
                    rtk_rate = getattr(msg, 'rtk_rate', 0)
                    nsats = getattr(msg, 'nsats', 0)
                    baseline_a = getattr(msg, 'baseline_a_mm', 0)
                    baseline_b = getattr(msg, 'baseline_b_mm', 0)
                    baseline_c = getattr(msg, 'baseline_c_mm', 0)
                    accuracy = getattr(msg, 'accuracy', 0)
                    iar_num = getattr(msg, 'iar_num_hypotheses', 0)
                    self.logger.info(
                        f"{msg_type} from sys={system_id}: "
                        f"rtk_id={rtk_id}, health={rtk_health}, rate={rtk_rate}Hz, "
                        f"nsats={nsats}, baseline=({baseline_a},{baseline_b},{baseline_c})mm, "
                        f"accuracy={accuracy}mm, iar_hyp={iar_num}"
                    )
                elif msg_type == 'STATUSTEXT':
                    text = getattr(msg, 'text', '').rstrip('\x00')
                    severity = getattr(msg, 'severity', 0)
                    sev_names = {0:'EMERGENCY',1:'ALERT',2:'CRITICAL',3:'ERROR',
                                 4:'WARNING',5:'NOTICE',6:'INFO',7:'DEBUG'}
                    sev = sev_names.get(severity, str(severity))
                    self.logger.info(f"STATUSTEXT from sys={system_id} [{sev}]: {text}")
                elif msg_type == 'PARAM_VALUE':
                    param_id = getattr(msg, 'param_id', b'').decode('utf-8', errors='replace').rstrip('\x00')
                    param_value = getattr(msg, 'param_value', 0.0)
                    self.logger.info(f"PARAM_VALUE from sys={system_id}: {param_id} = {param_value}")
                elif msg_type == 'HEARTBEAT':
                    pass  # too verbose, skip
                else:
                    self.logger.debug(f"Received {msg_type} from system {system_id}")
                
                # Handle COMMAND_ACK
                if msg_type == 'COMMAND_ACK':
                    self._handle_command_ack(system_id, msg)

                # Handle STATUSTEXT -> ring buffer in telemetry store
                if msg_type == 'STATUSTEXT':
                    self._handle_status_text(system_id, msg)

                # Store telemetry data (skip STATUSTEXT as it's stored separately in ring buffer)
                if msg_type != 'STATUSTEXT':
                    self.telemetry_store.update(system_id=system_id, message_type=msg_type, payload=msg)

                # ── GPS Logger integration ──────────────────────────
                if self.gps_logger is not None:
                    try:
                        if msg_type == 'HEARTBEAT':
                            self.gps_logger.on_heartbeat(system_id, msg)
                        elif msg_type in ('GPS_RAW_INT', 'GPS_GLOBAL_ORIGIN',
                                          'GPS_RTK', 'GPS2_RTK',
                                          'GLOBAL_POSITION_INT'):
                            self.gps_logger.on_gps_message(system_id, msg)
                    except Exception as e:
                        self.logger.debug(f"GPS logger error: {e}")
            
        except Exception as e:
            self.logger.debug(f"MAVLink parse error: {e}")

    def _handle_command_ack(self, system_id: int, msg):
        """Handle COMMAND_ACK message."""
        if not self.command_dispatcher:
            return
        
        try:
            command_id = msg.command
            result = msg.result
            progress = getattr(msg, 'progress', 0)
            result_param2 = getattr(msg, 'result_param2', 0)
            
            self.command_dispatcher.handle_command_ack(
                system_id=system_id,
                command_id=command_id,
                result=result,
                progress=progress,
                result_param2=result_param2
            )
            self.logger.info(f"COMMAND_ACK processed: system_id={system_id}, cmd={command_id}, result={result}")
        except Exception as e:
            self.logger.error(f"Error handling COMMAND_ACK: {e}")

    def _handle_status_text(self, system_id: int, msg):
        """Handle STATUSTEXT message: push to ring buffer in telemetry store."""
        try:
            text = getattr(msg, 'text', '')
            if isinstance(text, bytes):
                text = text.decode('utf-8', errors='ignore').rstrip('\x00')
            text = str(text)
            severity = getattr(msg, 'severity', 7)  # default DEBUG
            name = getattr(msg, 'name', '')
            if isinstance(name, bytes):
                name = name.decode('utf-8', errors='ignore').rstrip('\x00')
            name = str(name)

            self.telemetry_store.add_status_text(system_id, text, severity, name)
            self.logger.debug(
                f"STATUSTEXT from sys={system_id}: sev={severity}, text={text!r}"
            )
        except Exception as e:
            self.logger.error(f"Error handling STATUSTEXT: {e}")

    @staticmethod
    def _gps_fix_type_name(fix_type: int) -> str:
        """Convert MAVLink GPS_FIX_TYPE to human-readable string."""
        return fix_name(fix_type)

