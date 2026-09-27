"""Hardware-independent coordinator. All callbacks execute on one event-loop thread."""
from dataclasses import dataclass
from enum import Enum
import math


class Mode(str, Enum):
    BOOT = 'BOOT'
    STARTING_NAV = 'STARTING_NAV'
    NAVIGATION = 'NAVIGATION'
    STOPPING = 'STOPPING'
    RELEASING_NAV = 'RELEASING_NAV'
    STARTING_GESTURE = 'STARTING_GESTURE'
    GESTURE = 'GESTURE'
    RELEASING_GESTURE = 'RELEASING_GESTURE'
    FAULT = 'FAULT'
    SHUTDOWN = 'SHUTDOWN'


@dataclass(frozen=True)
class Settings:
    target_id: int = 0
    arrival_m: float = 0.5
    arrival_frames: int = 3
    frame_timeout: float = 1.0
    startup_timeout: float = 60.0
    release_timeout: float = 5.0
    stop_confirm_timeout: float = 60.0
    motion_timeout: float = 8.0
    stable_frames: int = 5
    resume_hold_seconds: float = 2.0
    resume_max_gap_seconds: float = 0.3

    def __post_init__(self):
        for name in ('arrival_m', 'frame_timeout', 'startup_timeout', 'release_timeout',
                     'stop_confirm_timeout', 'motion_timeout', 'resume_hold_seconds', 'resume_max_gap_seconds'):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f'{name} must be finite and positive')
        if self.arrival_frames < 1 or self.stable_frames < 1 or self.target_id < 0:
            raise ValueError('Invalid target ID or frame count')


COMMANDS = {'POINT': 'Command_1', 'PEACE': 'Command_2', 'FOUR': 'Command_3',
            'OPEN_PALM': 'Command_4', 'FIST': 'RETURN'}


class GestureFilter:
    """Consecutive fresh observations; a held gesture fires once.

    A different stable gesture can fire (especially FIST). Three neutral frames
    rearm the same gesture. Frame identity/freshness is enforced by Coordinator.
    """
    def __init__(self, frames=5):
        self.frames = frames
        self.reset()

    def reset(self):
        self.label = None
        self.count = 0
        self.fired = None
        self.neutral = 0

    def observe(self, label):
        if label not in COMMANDS:
            self.label, self.count = None, 0
            self.neutral += 1
            if self.neutral >= 3:
                self.fired = None
            return None
        self.neutral = 0
        self.count = self.count + 1 if label == self.label else 1
        self.label = label
        if self.count >= self.frames and label != self.fired:
            self.fired = label
            return COMMANDS[label]
        return None


class ResumeHold:
    """A continuous thumbs-up measured using distinct capture timestamps."""
    def __init__(self, seconds, max_gap, min_frames):
        self.seconds, self.max_gap, self.min_frames = seconds, max_gap, min_frames
        self.reset()

    def reset(self):
        self.start = self.last = None
        self.count = 0

    def observe(self, label, captured, eligible):
        if not eligible or label != 'THUMBS_UP':
            self.reset()
            return False
        if self.last is not None and captured <= self.last:
            return False
        if self.last is None or captured - self.last > self.max_gap:
            self.start, self.count = captured, 0
        self.last = captured
        self.count += 1
        return self.count >= self.min_frames and captured - self.start >= self.seconds


class Coordinator:
    """ports: drive(command)/inhibit(), workers.start/request_stop, actuator.send/stop.

    Position STOWED is based on explicit operator confirmation plus matching
    firmware acknowledgement. A completed RETURN never sets STOWED itself.
    """
    def __init__(self, drive, workers, actuator, clock, settings=Settings(), log=print):
        self.drive, self.workers, self.actuator = drive, workers, actuator
        self.clock, self.cfg, self.log = clock, settings, log
        self.mode = Mode.BOOT
        self.lift = 'UNKNOWN'
        self.pending = None
        self.command_id = 0
        self.session = 0
        self.last_seq = -1
        self.last_capture = -1.0
        self.last_frame = clock()
        self.deadline = None
        self.released = False
        self.exited = False
        self.arrival_count = 0
        self.gestures = GestureFilter(settings.stable_frames)
        self.resume_hold = ResumeHold(settings.resume_hold_seconds, settings.resume_max_gap_seconds, settings.stable_frames)
        self.resume_after = clock()
        self.error = None
        self.history = [self.mode.value]
        self.drive.inhibit()

    def _mode(self, mode, timeout=None):
        self.mode = mode
        self.resume_hold.reset()
        self.resume_after = self.clock()
        self.deadline = self.clock() + timeout if timeout else None
        self.history.append(mode.value)
        self.log(f'MODE {mode.value} | lift={self.lift}')

    def _start_worker(self, kind):
        self.drive.inhibit()
        self.session += 1
        self.last_seq = -1
        self.last_capture = -1.0
        self.arrival_count = 0
        self.gestures.reset()
        self._mode(Mode.STARTING_NAV if kind == 'navigation' else Mode.STARTING_GESTURE,
                   self.cfg.startup_timeout)
        self.workers.start(kind, self.session)

    def _release(self, kind):
        self.drive.inhibit()
        self.released = self.exited = False
        self._mode(Mode.RELEASING_NAV if kind == 'navigation' else Mode.RELEASING_GESTURE,
                   self.cfg.release_timeout)
        self.workers.request_stop(self.session)

    def _send(self, command):
        self.resume_hold.reset()
        self.resume_after = self.clock()
        self.command_id += 1
        self.pending = (self.command_id, command, self.clock() + self.cfg.motion_timeout)
        if command.startswith('Command_'):
            self.lift = 'EXTENDING'
        elif command == 'RETURN':
            self.lift = 'RETRACTING'
        self.actuator.send(self.command_id, command)

    def action(self, action):
        """Explicit local operator actions. Invalid requests do not change mode."""
        if self.mode in (Mode.FAULT, Mode.SHUTDOWN):
            return False
        try:
            if action == 'stowed' and self.mode in (Mode.BOOT, Mode.GESTURE):
                if self.pending or self.lift not in ('UNKNOWN', 'RETRACTED_UNVERIFIED', 'STOWED'):
                    return False
                self._send('STOW')
            elif action == 'start' and self.mode == Mode.BOOT and self.lift == 'STOWED' and not self.pending:
                self._start_worker('navigation')
            elif action == 'stopped' and self.mode == Mode.STOPPING:
                self._release('navigation')
            else:
                return False
            return True
        except Exception as exc:
            self.fault(str(exc))
            return False

    def worker_event(self, event):
        if self.mode in (Mode.FAULT, Mode.SHUTDOWN) or event.get('session') != self.session:
            return  # Includes delayed events from a previous camera owner.
        try:
            kind = event['type']
            if kind == 'fault':
                raise RuntimeError(event.get('error', 'Worker failure'))
            if kind == 'released':
                if self.mode not in (Mode.RELEASING_NAV, Mode.RELEASING_GESTURE):
                    raise RuntimeError('Unexpected camera release')
                self.released = True
            elif kind == 'exit':
                if self.mode not in (Mode.RELEASING_NAV, Mode.RELEASING_GESTURE) or event['code'] != 0:
                    raise RuntimeError(f'Unexpected worker exit: {event["code"]}')
                self.exited = True
            elif kind == 'ready':
                if self.mode == Mode.STARTING_NAV:
                    self._mode(Mode.NAVIGATION)
                elif self.mode == Mode.STARTING_GESTURE:
                    self._mode(Mode.GESTURE)
                else:
                    raise RuntimeError('Unexpected worker readiness')
                self.last_frame = self.clock()
            elif kind in ('nav', 'gesture'):
                self._observation(event)
            else:
                raise ValueError('Unknown worker event')
            if self.released and self.exited:
                if self.mode == Mode.RELEASING_NAV:
                    self._start_worker('gesture')
                elif self.mode == Mode.RELEASING_GESTURE:
                    self._start_worker('navigation')
                self.released = self.exited = False
        except Exception as exc:
            self.fault(str(exc))

    def _observation(self, event):
        expected = 'nav' if self.mode == Mode.NAVIGATION else 'gesture' if self.mode == Mode.GESTURE else None
        if expected is None:
            return  # Drain old frames during STOPPING/release without acting on them.
        if event['type'] != expected:
            raise ValueError('Wrong observation type for mode')
        seq, captured = event['seq'], event['captured']
        if not isinstance(seq, int) or not isinstance(captured, (float, int)) or not math.isfinite(captured):
            raise ValueError('Invalid frame metadata')
        if seq <= self.last_seq or captured <= self.last_capture:
            return  # Duplicate images neither build stability nor renew a drive lease.
        now = self.clock()
        if captured > now + 0.05 or now - captured > self.cfg.frame_timeout:
            raise ValueError('Stale or future frame')
        self.last_seq, self.last_capture, self.last_frame = seq, captured, captured
        if expected == 'gesture':
            if getattr(self.drive, 'error', None):
                raise RuntimeError(f'Drive connection failed: {self.drive.error}')
            eligible = self.lift == 'STOWED' and self.pending is None and captured > self.resume_after
            if self.resume_hold.observe(event['label'], captured, eligible):
                self.log('THUMBS_UP confirmed: returning to navigation')
                self._release('gesture')
                return
            if self.pending:
                self.gestures.reset()
                return
            command = self.gestures.observe(event['label'])
            if command == 'RETURN' and self.lift == 'EXTENDED':
                self._send(command)
            elif command and command.startswith('Command_') and self.lift == 'STOWED':
                self._send(command)
            return
        if self.lift != 'STOWED' or self.pending:
            raise RuntimeError('Navigation with unstowed actuator')
        distance = event.get('distance')
        if event.get('target_id') != self.cfg.target_id or distance is None:
            self.arrival_count = 0
            self.drive.inhibit()
            return
        if not isinstance(distance, (float, int)) or not math.isfinite(distance) or distance <= 0:
            raise ValueError('Invalid target distance')
        if distance <= self.cfg.arrival_m:
            self.drive.inhibit()
            self.arrival_count += 1
            if self.arrival_count >= self.cfg.arrival_frames:
                self._mode(Mode.STOPPING, self.cfg.stop_confirm_timeout)
            return
        self.arrival_count = 0
        if event.get('blocked') is not False:
            self.drive.inhibit()
            return
        accel, steer = event['accel'], event['steer']
        if not all(isinstance(x, (float, int)) and math.isfinite(x) and -1 <= x <= 1 for x in (accel, steer)):
            raise ValueError('Invalid navigation command')
        self.drive.command(max(0.0, accel), steer, captured + self.cfg.frame_timeout)

    def actuator_event(self, event):
        if self.mode in (Mode.FAULT, Mode.SHUTDOWN):
            return
        try:
            if event['type'] == 'fault':
                raise RuntimeError(event.get('error', 'Actuator failure'))
            if not self.pending or event.get('id') != self.pending[0]:
                raise ValueError('Unexpected actuator response ID')
            if event['type'] == 'ack':
                return
            if event['type'] != 'done':
                raise ValueError('Unexpected actuator response')
            command = self.pending[1]
            expected = 'STOWED' if command == 'STOW' else 'RETRACTED_UNVERIFIED' if command == 'RETURN' else 'EXTENDED'
            if event['state'] != expected:
                raise ValueError('Unexpected actuator completion state')
            self.lift = expected
            self.pending = None
            self.gestures.reset()
            self.resume_hold.reset()
            self.resume_after = self.clock()
            self.log(f'ACTUATOR {expected}')
        except Exception as exc:
            self.fault(str(exc))

    def tick(self):
        if self.mode in (Mode.FAULT, Mode.SHUTDOWN):
            return
        now = self.clock()
        if self.deadline is not None and now >= self.deadline:
            self.fault(f'{self.mode.value} timed out')
        elif self.pending and now >= self.pending[2]:
            self.fault('Actuator response timed out; position unknown')
        elif self.mode in (Mode.NAVIGATION, Mode.GESTURE) and now - self.last_frame >= self.cfg.frame_timeout:
            self.fault('Camera/perception frames timed out')
        elif getattr(self.drive, 'error', None):
            self.fault(f'Drive connection failed: {self.drive.error}')

    def fault(self, reason):
        if self.mode in (Mode.FAULT, Mode.SHUTDOWN):
            return
        self.error = reason
        self.lift = 'UNKNOWN'
        self.pending = None
        self._mode(Mode.FAULT)
        self.log(f'FAULT {reason}')
        self._halt()

    def _halt(self):
        for operation in (self.drive.inhibit, self.actuator.stop,
                          lambda: self.workers.request_stop(self.session)):
            try:
                operation()
            except Exception as exc:
                self.log(f'Cleanup failed: {exc}')

    def shutdown(self):
        self._mode(Mode.SHUTDOWN)
        self.pending = None
        self.lift = 'UNKNOWN'
        self._halt()
