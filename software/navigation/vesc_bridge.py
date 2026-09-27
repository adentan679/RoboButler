"""
VESC Bridge - Direct Serial Implementation
No pyvesc dependency - uses raw VESC protocol over pyserial only
"""

import serial
import struct
import os
import math

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


def _find_vesc_port(preferred: str) -> str:
    """Require an operator-verified stable path; never guess another device."""
    if not preferred or not preferred.startswith('/dev/serial/by-id/'):
        raise ValueError("Set --vesc-port to the verified /dev/serial/by-id/ VESC path")
    if not os.path.exists(preferred):
        raise FileNotFoundError(preferred)
    return preferred


class VESCBridge:
    def __init__(self,
                 port: str = None,
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
        self.port          = _find_vesc_port(port)
        self.baud_rate     = baud_rate

        # Connection failures propagate: do not silently run without control.
        self.serial = serial.Serial(self.port, self.baud_rate,
                                    timeout=0.1, write_timeout=0.2)

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
        """Send normalized commands. Zero duty is NOT confirmed braking."""
        if not math.isfinite(accel) or not math.isfinite(steer_rate):
            self.stop()
            raise ValueError("Non-finite drive command")
        duty = self._cmd_to_duty(accel)
        servo = self._steer_to_servo(steer_rate)
        # Send zero duty first so steering failure cannot delay a stop request.
        # Do not retain positive commands when navigation requests zero.
        try:
            self._write(_pack_duty(duty))
            self._write(_pack_servo(servo))
        except Exception:
            try:
                self.stop()
            except Exception:
                pass
            raise  # Supervisor must latch a fault; no automatic reconnect/resume.

    def _write(self, packet: bytes):
        if self.serial.write(packet) != len(packet):
            raise IOError("Incomplete VESC serial write")

    def stop(self):
        """Request zero duty; this does not prove physical standstill."""
        self._write(_pack_duty(0.0))
        self._write(_pack_servo(self.servo_center))

    def close(self):
        """Always release serial even if the stop request fails."""
        try:
            self.stop()
        finally:
            self.serial.close()
