"""Deterministic fake serial/drive adapters, no hardware packages imported."""
import time


class SimDrive:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.error = None
        self.request = (0, 0, 0)
        self.history = []
    def command(self, accel, steer, expires):
        self.request = (accel, steer, expires)
        self.history.append(('drive', accel, steer))
    def inhibit(self):
        self.request = (0, 0, 0)
        self.history.append(('inhibit', 0, 0))
    def actual(self):
        return self.request[:2] if self.clock() < self.request[2] else (0, 0)
    def close(self):
        self.inhibit()


class SimSerial:
    """Protocol emulator. Native firmware harness separately checks actual .ino."""
    def __init__(self, clock=time.monotonic, duration=0.15):
        self.clock, self.duration = clock, duration
        self.rx = bytearray()
        self.history = []
        self.position = 'UNKNOWN'
        self.pending = None
        self.last_id = 0
        self.closed = False
        self.fail = False
        self.drop_done = False
    def _reply(self, text):
        self.rx.extend((text + '\n').encode())
    def _advance(self):
        if self.pending and self.clock() >= self.pending[2]:
            command_id, state, _ = self.pending
            self.position = state
            self.pending = None
            if not self.drop_done:
                self._reply(f'DONE {command_id} {state}')
    @property
    def in_waiting(self):
        self._advance()
        return len(self.rx)
    def read(self, size):
        if self.fail:
            raise IOError('Simulated serial disconnect')
        data = bytes(self.rx[:size])
        del self.rx[:size]
        return data
    def write(self, data):
        if self.fail:
            raise IOError('Simulated serial disconnect')
        line = data.decode().strip()
        self.history.append(line)
        if line == 'HELLO':
            self._reply('READY ROBOBUTLER1')
        elif line == 'PING':
            self._reply('PONG')
        elif line == 'STOP':
            self.pending = None
            self.position = 'UNKNOWN'
            self._reply('FAULT STOPPED')
        else:
            raw_id, command = line.split()
            command_id = int(raw_id)
            if command_id <= self.last_id or self.pending:
                self._reply('FAULT BUSY_OR_BAD_ID')
                return len(data)
            self.last_id = command_id
            expected = None
            if command == 'STOW' and self.position in ('UNKNOWN', 'RETRACTED_UNVERIFIED', 'STOWED'):
                expected = 'STOWED'
            elif command.startswith('Command_') and self.position == 'STOWED':
                expected = 'EXTENDED'
            elif command == 'RETURN' and self.position == 'EXTENDED':
                expected = 'RETRACTED_UNVERIFIED'
            if expected:
                self._reply(f'ACK {command_id}')
                self.pending = (command_id, expected, self.clock() + self.duration)
            else:
                self._reply('FAULT INVALID_STATE_OR_COMMAND')
        return len(data)
    def close(self):
        self.closed = True
