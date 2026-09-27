"""Hardware adapters. Imported only with explicit --hardware."""
import math
import os
import threading
import time


def validate_ports(vesc, arduino):
    for path in (vesc, arduino):
        if not path.startswith('/dev/serial/by-id/') or not os.path.exists(path):
            raise ValueError('Configure two existing, physically verified /dev/serial/by-id/ paths')
    if os.path.realpath(vesc) == os.path.realpath(arduino):
        raise ValueError('VESC and Arduino resolve to the same USB device')


class DriveGuard:
    """Only this thread writes VESC. Drive permission expires without fresh frames.

    Zero duty is a stop request, NOT a brake/standstill measurement. The VESC's
    own timeout is still required to cover Pi/service death.
    """
    def __init__(self, bridge, clock=time.monotonic):
        self.bridge, self.clock = bridge, clock
        self.lock = threading.Lock()
        self.request = (0.0, 0.0, 0.0)
        self.error = None
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def command(self, accel, steer, expires):
        if not all(math.isfinite(x) for x in (accel, steer, expires)):
            raise ValueError('Invalid drive lease')
        with self.lock:
            self.request = (accel, steer, expires)

    def inhibit(self):
        with self.lock:
            self.request = (0.0, 0.0, 0.0)

    def _run(self):
        try:
            while not self.done.is_set():
                # Lock covers write so inhibit returns after any already-started
                # drive write. No old nonzero write can follow an inhibit return.
                with self.lock:
                    accel, steer, expires = self.request
                    if self.clock() >= expires:
                        accel, steer = 0.0, 0.0
                    self.bridge.send_command(accel, steer)
                self.done.wait(0.05)
        except Exception as exc:
            self.error = str(exc)
        finally:
            try:
                self.bridge.close()
            except Exception as exc:
                self.error = self.error or str(exc)

    def close(self):
        self.inhibit()
        self.done.set()
        self.thread.join(timeout=2)
        if self.thread.is_alive():
            raise RuntimeError('VESC writer did not stop')


class ArduinoLink:
    """Persistent, nonblocking ASCII protocol with command IDs and heartbeat."""
    def __init__(self, serial_port, clock=time.monotonic):
        self.serial, self.clock = serial_port, clock
        self.buffer = b''
        self.ready = False
        self.last_pong = clock()
        self.last_ping = clock()

    def write(self, line):
        payload = (line + '\n').encode('ascii')
        if self.serial.write(payload) != len(payload):
            raise IOError('Partial Arduino write')

    def handshake(self, timeout=8):
        deadline = self.clock() + timeout
        next_hello = self.clock() + 2.0  # Mega USB-open reset allowance; bounded by deadline.
        while self.clock() < deadline:
            if self.clock() >= next_hello:
                self.write('HELLO')
                next_hello = self.clock() + 1.0
            events = self.poll(handshaking=True)
            if any(e['type'] == 'fault' for e in events):
                raise RuntimeError(events)
            if self.ready:
                self.last_pong = self.last_ping = self.clock()
                return
            time.sleep(0.01)
        raise TimeoutError('Arduino did not identify as ROBOBUTLER1 firmware')

    def send(self, command_id, command):
        if not self.ready:
            raise RuntimeError('Arduino not ready')
        self.write(f'{command_id} {command}')

    def stop(self):
        self.write('STOP')

    def poll(self, handshaking=False):
        events = []
        self.buffer += self.serial.read(min(self.serial.in_waiting, 4096))
        if len(self.buffer) > 8192:
            raise RuntimeError('Arduino receive buffer overflow')
        while b'\n' in self.buffer:
            raw, self.buffer = self.buffer.split(b'\n', 1)
            if len(raw) > 128:
                raise ValueError('Oversized Arduino reply')
            parts = raw.decode('ascii').strip().split()
            if not parts:
                continue
            if parts == ['READY', 'ROBOBUTLER1'] and handshaking:
                self.ready = True
            elif parts == ['BOOT', 'ROBOBUTLER1'] and handshaking:
                continue
            elif parts and parts[0] in ('BOOT', 'READY'):
                events.append({'type': 'fault', 'error': 'Arduino reset or unexpected READY'})
            elif len(parts) == 2 and parts[0] == 'ACK':
                events.append({'type': 'ack', 'id': int(parts[1])})
            elif len(parts) == 3 and parts[0] == 'DONE':
                events.append({'type': 'done', 'id': int(parts[1]), 'state': parts[2]})
            elif parts == ['PONG']:
                self.last_pong = self.clock()
            else:
                events.append({'type': 'fault', 'error': 'Arduino: ' + ' '.join(parts)})
        if self.ready and not handshaking:
            if self.clock() - self.last_pong > 2.0:
                events.append({'type': 'fault', 'error': 'Arduino heartbeat timed out'})
            if self.clock() - self.last_ping >= 0.5:
                self.write('PING')
                self.last_ping = self.clock()
        return events

    def close(self):
        try:
            self.stop()
        finally:
            self.serial.close()
