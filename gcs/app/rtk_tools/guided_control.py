import logging
from gcs.app.mavlink.connection import MavlinkConnection

class GuidedControl:
    def __init__(self, connection: MavlinkConnection):
        self.connection = connection
        self.logger = logging.getLogger("GuidedControl")

    def set_position_target_local_ned(self, system_id: int, component_id: int, x: float, y: float, z: float, vx=0, vy=0, vz=0, yaw=0):
        self.logger.info(f"Sending SET_POSITION_TARGET_LOCAL_NED to system_id={system_id}, component_id={component_id}, x={x}, y={y}, z={z}, vx={vx}, vy={vy}, vz={vz}, yaw={yaw}")
        self.connection.send_set_position_target_local_ned(system_id, component_id, x, y, z, vx, vy, vz, yaw)
        print(f"[LOG] SET_POSITION_TARGET_LOCAL_NED sent: system_id={system_id}, component_id={component_id}, pos=({x},{y},{z}), vel=({vx},{vy},{vz}), yaw={yaw}")

    def set_velocity_target_local_ned(self, system_id: int, component_id: int, vx: float, vy: float, vz: float, yaw=0):
        self.logger.info(f"Sending velocity target to system_id={system_id}, component_id={component_id}, vx={vx}, vy={vy}, vz={vz}, yaw={yaw}")
        self.connection.send_set_position_target_local_ned(system_id, component_id, 0, 0, 0, vx, vy, vz, yaw=yaw, type_mask=0b0000110111000111)
        print(f"[LOG] Velocity target sent: system_id={system_id}, component_id={component_id}, vel=({vx},{vy},{vz}), yaw={yaw}")

    def indoor_takeoff(self, system_id: int, component_id: int, throttle_pct: float = 65):
        """Indoor takeoff via RC_CHANNELS_OVERRIDE throttle (STABILIZE mode).
        
        Sends centered roll/pitch/yaw with throttle at throttle_pct%.
        Drone will climb. Send indoor_land() or disarm to stop.
        """
        throttle_raw = int(1100 + (throttle_pct / 100.0) * 800)  # 1100-1900
        self.connection.send_rc_channels_override(
            system_id, chan3_raw=throttle_raw,
            chan1_raw=1500, chan2_raw=1500, chan4_raw=1500
        )
        self.logger.info(f"Indoor takeoff: throttle={throttle_pct}% ({throttle_raw})")
        print(f"[Indoor] Takeoff: throttle {throttle_pct}%")

    def indoor_land(self, system_id: int, component_id: int):
        """Indoor landing via RC_CHANNELS_OVERRIDE throttle min (STABILIZE mode).
        
        Sets throttle to minimum (1100). Drone will descend. Disarm after landing.
        """
        self.connection.send_rc_channels_override(
            system_id, chan3_raw=1100,
            chan1_raw=1500, chan2_raw=1500, chan4_raw=1500
        )
        self.logger.info(f"Indoor land: throttle=min")
        print(f"[Indoor] Land: throttle min")

    def indoor_test_sequence(self, system_id: int, component_id: int):
        """Automated indoor test: takeoff → 1m → hover 5s → land.
        
        Uses timed RC_CHANNELS_OVERRIDE in STABILIZE mode.
        No GPS or altitude sensor needed — approximate timing.
        """
        import threading
        self.logger.info(f"Starting indoor test sequence for system_id={system_id}")
        print(f"[Indoor Test] Sequence started for drone {system_id}")
        
        # Phase 1: climb at 65% throttle for 1.5s → ~1m
        def _phase2_hover():
            self.connection.send_rc_channels_override(
                system_id, chan3_raw=1550,  # ~50% hover
                chan1_raw=1500, chan2_raw=1500, chan4_raw=1500
            )
            self.logger.info(f"Indoor test: hovering at ~50% throttle")
            print(f"[Indoor Test] Hovering...")
            
            # Phase 3: land after 5s hover
            def _phase3_land():
                self.connection.send_rc_channels_override(
                    system_id, chan3_raw=1100,  # min throttle
                    chan1_raw=1500, chan2_raw=1500, chan4_raw=1500
                )
                self.logger.info(f"Indoor test: landing (throttle min)")
                print(f"[Indoor Test] Landing... DISARM after touchdown!")
            
            threading.Timer(5.0, _phase3_land).start()
        
        # Start phase 1 now
        self.connection.send_rc_channels_override(
            system_id, chan3_raw=int(1100 + 0.65 * 800),  # 65% throttle
            chan1_raw=1500, chan2_raw=1500, chan4_raw=1500
        )
        self.logger.info(f"Indoor test: climbing at 65% throttle")
        print(f"[Indoor Test] Climbing to ~1m...")
        threading.Timer(1.5, _phase2_hover).start()

    def handle_response(self, response):
        self.logger.info(f"GuidedControl response: {response}")
        if response is None:
            self.logger.warning("No response received.")
            print("[LOG] No response received.")
        elif isinstance(response, dict) and response.get("success"):
            self.logger.info("GuidedControl command executed successfully.")
            print("[LOG] GuidedControl command executed successfully.")
        else:
            self.logger.error(f"GuidedControl command failed: {response}")
            print(f"[LOG] GuidedControl command failed: {response}")
