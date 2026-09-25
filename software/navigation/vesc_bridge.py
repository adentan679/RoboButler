"""
VESC Bridge - Direct Serial Implementation
No pyvesc dependency - uses raw VESC protocol over pyserial only
"""

import serial
import struct
import glob   # CHANGED (Lalo 6/11): needed for port auto-detection
import time   # CHANGED (Lalo 6/11): needed for reconnect delay

def _crc_ccitt(data: bytes) -> int:
    """VESC uses CRC-CCITT for packet integrity"""
    crc = 0x0000
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
        crc &= 0xFFFF
    return crc

def _build_packet(payload: bytes) -> bytes:
    """Wrap payload in VESC packet format"""
    length = len(payload)
    header = bytes([0x02, length])
    crc    = _crc_ccitt(payload)
    footer = bytes([crc >> 8, crc & 0xFF, 0x03])
    return header + payload + footer

def _pack_rpm(rpm: int) -> bytes:
    """VESC command 8 — Set motor RPM"""
    # CHANGED (Lalo 6/11): no longer used by send_command (we use duty cycle
    # now) — kept here so nothing else that imports it breaks.
    payload = bytes([8]) + struct.pack('>i', int(rpm))
    return _build_packet(payload)

def _pack_servo(position: float) -> bytes:
    """VESC command 12 - Set servo position (0.0 to 1.0)"""
    # CHANGED (Lalo 6/11): was command 23 with float32 - wrong on both counts.
    # VESC firmware: COMM_SET_SERVO_POS = 12, payload = uint16 of position*1000.
    # This is why steering never worked while duty (command 5, correct) did.
    pos = int(max(0.0, min(1.0, float(position))) * 1000)
    payload = bytes([12]) + struct.pack('>H', pos)
    return _build_packet(payload)

def _pack_duty(duty: float) -> bytes:
    """VESC command 5 — Set duty cycle (-1.0 to 1.0)"""
    payload = bytes([5]) + struct.pack('>i', int(duty * 100000))
    return _build_packet(payload)


# CHANGED (Lalo 6/11): new helper — VESC and Arduino can swap ACM0/ACM1
# between boots. This tries the preferred port, then /dev/serial/by-id/
# (stable names), then any ACM port, so we stop talking to the wrong device.
def _find_vesc_port(preferred: str) -> str:
    candidates = [preferred]
    candidates += sorted(glob.glob('/dev/serial/by-id/*'))
    candidates += sorted(glob.glob('/dev/ttyACM*'))
    for p in candidates:
        if p and glob.glob(p):
            return p
    return preferred


class VESCBridge:
    def __init__(self,
                 port: str = '/dev/ttyACM0',
                 baud_rate: int = 115200,
                 max_duty: float = 0.07,       # CHANGED (Lalo 6/11): calibrated on floor - slowest reliable speed, locked as ceiling
                 min_duty: float = 0.07,       # CHANGED (Lalo 6/11): floor == ceiling -> single fixed crawl speed
                 servo_range: float = 0.35,    # CHANGED (Lalo 6/11): was hardcoded 0.3 below — now a parameter, easy to calibrate
                 invert_steering: bool = False):  # CHANGED (Lalo 6/11): new — set True if RIGHT command steers LEFT during testing
        # CHANGED (Lalo 6/11): removed max_accel and max_steer_rate parameters.
        # The controller (mpc_controller.py) ALREADY outputs normalized [-1, 1]
        # commands. The old code divided them again by these values, which
        # crushed steering to ~7% of its range — this is why the car never steered.

        self.max_duty      = max_duty       # CHANGED (Lalo 6/11): was self.max_erpm
        self.min_duty      = min_duty       # CHANGED (Lalo 6/11): new
        self.servo_center  = 0.5
        self.servo_range   = servo_range    # CHANGED (Lalo 6/11): was hardcoded 0.3
        self.steer_sign    = -1.0 if invert_steering else 1.0  # CHANGED (Lalo 6/11): new
        self.port          = _find_vesc_port(port)   # CHANGED (Lalo 6/11): port auto-detection
        self.baud_rate     = baud_rate                # CHANGED (Lalo 6/11): stored for reconnect

        # CHANGED (Lalo 6/11): state for coast-through-blindness smoothing
        self._last_accel   = 0.0
        self._last_steer   = 0.0
        self._coast_count  = 0

        try:
            self.serial = serial.Serial(self.port, self.baud_rate, timeout=0.1)
            print(f"[VESC] Connected on {self.port}")
        except serial.SerialException as e:
            print(f"[VESC] Connection failed: {e}")
            self.serial = None

    # CHANGED (Lalo 6/11): new method — one Errno 5 used to kill all motor
    # commands for the rest of the run. Now we try to reopen the port once.
    def _reconnect(self):
        try:
            if self.serial:
                self.serial.close()
        except Exception:
            pass
        time.sleep(0.2)
        self.port = _find_vesc_port(self.port)
        try:
            self.serial = serial.Serial(self.port, self.baud_rate, timeout=0.1)
            print(f"[VESC] Reconnected on {self.port}")
        except serial.SerialException as e:
            print(f"[VESC] Reconnect failed: {e}")
            self.serial = None

    # CHANGED (Lalo 6/11): removed _normalize_accel and _normalize_steer.
    # They double-normalized already-normalized controller outputs (the
    # steering-killer bug). Inputs to send_command are [-1, 1] and used directly.

    def _cmd_to_duty(self, accel_cmd: float) -> float:
        # CHANGED (Lalo 6/11): replaces _accel_to_erpm — maps [-1, 1] to duty
        accel_cmd = max(-1.0, min(1.0, float(accel_cmd)))
        duty = accel_cmd * self.max_duty
        # CHANGED (Lalo 6/11): forward-only - negative accel meant 'ease off'
        # but became REVERSE duty, causing back-and-forth oscillation. Coast instead.
        if duty <= 0.0:
            return 0.0
        # Friction floor: a nonzero forward command should actually move the car
        if duty < self.min_duty:
            duty = self.min_duty
        return duty

    def _steer_to_servo(self, steer_cmd: float) -> float:
        # CHANGED (Lalo 6/11): input is the controller's [-1, 1] command used
        # directly (no division by 2.0), plus optional sign flip
        steer_cmd = max(-1.0, min(1.0, float(steer_cmd))) * self.steer_sign
        servo = self.servo_center + steer_cmd * self.servo_range
        return float(max(0.0, min(1.0, servo)))

    def send_command(self, accel: float, steer_rate: float):
        # NOTE (Lalo 6/11): parameter names kept identical to the original so
        # main_navigation.py needs NO changes. Both values are the controller's
        # normalized [-1, 1] outputs.
        if self.serial is None:
            self._reconnect()                          # CHANGED (Lalo 6/11): try to recover
            if self.serial is None:
                print("[VESC] No connection — skipping command")
                return

        # CHANGED (Lalo 6/11): coast-through-blindness. The state machine sends
        # accel=0 the instant tag detection blinks (every few frames at 10 FPS),
        # causing stop-start stutter. If we were just driving, hold the last
        # command for up to coast_frames before actually stopping. A real stop
        # (tag lost for ~1s, obstacle, target reached) still stops the car
        # once the grace period expires. NOTE: only safe at crawl speeds -
        # shrink coast_frames before raising max_duty.
        coast_frames = 8   # ~0.8s of grace at 10 FPS
        if accel <= 0.0 and self._last_accel > 0.0 and self._coast_count < coast_frames:
            self._coast_count += 1
            accel = self._last_accel
            steer_rate = self._last_steer
        else:
            if accel > 0.0:
                self._coast_count = 0
            self._last_accel = accel
            self._last_steer = steer_rate

        duty  = self._cmd_to_duty(accel)               # CHANGED (Lalo 6/11): was ERPM path
        servo = self._steer_to_servo(steer_rate)       # CHANGED (Lalo 6/11): no double normalize

        try:
            self.serial.write(_pack_servo(servo))
            self.serial.write(_pack_duty(duty))        # CHANGED (Lalo 6/11): was _pack_rpm(erpm)
            print(f"[VESC] Duty: {duty:+.3f} | Servo: {servo:.3f} "
                  f"(accel={accel:+.2f}, steer={steer_rate:+.2f})")
        except Exception as e:
            print(f"[VESC] Send error: {e} — attempting reconnect")
            self._reconnect()                          # CHANGED (Lalo 6/11): recover instead of dying

    def stop(self):
        """Emergency stop"""
        if self.serial:
            try:
                self.serial.write(_pack_servo(self.servo_center))
                self.serial.write(_pack_duty(0.0))     # CHANGED (Lalo 6/11): was _pack_rpm(0)
                print("[VESC] Emergency stop sent")
            except Exception as e:
                print(f"[VESC] Stop error: {e}")

    def close(self):
        """Clean shutdown"""
        self.stop()
        if self.serial:
            self.serial.close()
            print("[VESC] Connection closed")