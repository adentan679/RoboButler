import unittest
from software.integration.core import Coordinator, Mode, GestureFilter
from software.integration.hardware import ArduinoLink
from software.integration.simulation import SimSerial, SimDrive

class Clock:
    def __init__(self): self.now = 100.0
    def __call__(self): return self.now
    def advance(self, seconds=0.05): self.now += seconds

class Workers:
    def __init__(self): self.calls = []
    def start(self, kind, session): self.calls.append(('start', kind, session))
    def request_stop(self, session): self.calls.append(('stop', session))

class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock(); self.drive = SimDrive(self.clock); self.workers = Workers()
        self.serial = SimSerial(self.clock, duration=0.1)
        self.link = ArduinoLink(self.serial, self.clock)
        self.link.write('HELLO'); self.link.poll(handshaking=True)
        self.bot = Coordinator(self.drive, self.workers, self.link, self.clock, log=lambda *a: None)
        self.seq = 0
    def poll(self):
        for event in self.link.poll(): self.bot.actuator_event(event)
    def complete(self):
        self.poll(); self.clock.advance(0.11); self.poll()
    def ready(self):
        self.bot.worker_event({'type':'ready','session':self.bot.session}); self.seq=0
    def navigation(self):
        self.assertFalse(self.bot.action('start'))
        self.assertTrue(self.bot.action('stowed')); self.complete()
        self.assertTrue(self.bot.action('start')); self.ready()
    def nav(self, distance=1.5, **fields):
        self.clock.advance(); self.seq+=1
        e=dict(type='nav', session=self.bot.session, seq=self.seq, captured=self.clock(),
               distance=distance, target_id=0, accel=0.5, steer=0.1, blocked=False)
        e.update(fields); self.bot.worker_event(e); return e
    def release(self, reverse=False):
        e={'session':self.bot.session}
        events=[dict(e,type='released'),dict(e,type='exit',code=0)]
        for event in reversed(events) if reverse else events: self.bot.worker_event(event)
    def gesture_mode(self):
        self.navigation()
        for _ in range(3): self.nav(0.4)
        self.assertEqual(self.bot.mode,Mode.STOPPING)
        self.assertTrue(self.bot.action('stopped')); self.release(); self.ready()
        self.assertEqual(self.bot.mode,Mode.GESTURE)
    def gesture(self,label,count=5):
        for _ in range(count):
            self.clock.advance(); self.seq+=1
            self.bot.worker_event(dict(type='gesture',session=self.bot.session,seq=self.seq,
                                       captured=self.clock(),label=label))

    def test_complete_round_trip_and_fresh_target_required(self):
        self.gesture_mode(); self.assertEqual(self.drive.actual(),(0,0))
        self.gesture('POINT'); self.assertEqual(self.bot.lift,'EXTENDING')
        self.assertFalse(self.bot.action('resume')); self.complete()
        self.assertEqual(self.bot.lift,'EXTENDED'); self.gesture('FIST'); self.complete()
        self.assertEqual(self.bot.lift,'RETRACTED_UNVERIFIED')
        self.assertFalse(self.bot.action('resume'))
        self.bot.action('stowed'); self.complete(); self.gesture('THUMBS_UP', count=42)
        self.assertEqual(self.bot.mode,Mode.RELEASING_GESTURE)
        self.release(); self.ready(); self.assertEqual(self.bot.mode,Mode.NAVIGATION)
        self.assertEqual(self.drive.actual(),(0,0)); self.nav(distance=None,target_id=None)
        self.assertEqual(self.drive.actual(),(0,0)); self.nav(1.5)
        self.assertGreater(self.drive.actual()[0],0)
        self.assertEqual([x[1] for x in self.workers.calls if x[0]=='start'],
                         ['navigation','gesture','navigation'])
    def test_stop_confirmation_required_and_arrival_latched(self):
        self.navigation()
        for _ in range(3): self.nav(0.4)
        self.assertEqual(self.bot.mode,Mode.STOPPING); self.assertEqual(len(self.workers.calls),1)
        self.nav(1.5); self.assertEqual(self.bot.mode,Mode.STOPPING)
        self.assertEqual(self.drive.actual(),(0,0))
    def test_both_release_and_exit_required(self):
        self.navigation()
        for _ in range(3): self.nav(0.4)
        self.bot.action('stopped')
        self.bot.worker_event(dict(type='released',session=self.bot.session))
        self.assertEqual(self.bot.mode,Mode.RELEASING_NAV)
        self.assertEqual(len([x for x in self.workers.calls if x[0]=='start']),1)
        self.bot.worker_event(dict(type='exit',session=self.bot.session,code=0))
        self.assertEqual(self.bot.mode,Mode.STARTING_GESTURE)
    def test_exit_before_release_order(self):
        self.navigation()
        for _ in range(3): self.nav(0.4)
        self.bot.action('stopped'); self.release(reverse=True)
        self.assertEqual(self.bot.mode,Mode.STARTING_GESTURE)
    def test_release_timeout_does_not_start_second_camera(self):
        self.navigation()
        for _ in range(3): self.nav(0.4)
        self.bot.action('stopped'); self.clock.advance(6); self.bot.tick()
        self.assertEqual(self.bot.mode,Mode.FAULT)
        self.assertEqual(len([x for x in self.workers.calls if x[0]=='start']),1)
    def test_startup_timeout(self):
        self.bot.action('stowed'); self.complete(); self.bot.action('start')
        self.clock.advance(61); self.bot.tick(); self.assertEqual(self.bot.mode,Mode.FAULT)
    def test_target_loss_and_obstacle_withdraw_drive(self):
        self.navigation(); self.nav(); self.assertGreater(self.drive.actual()[0],0)
        self.nav(distance=None,target_id=None); self.assertEqual(self.drive.actual(),(0,0))
        self.nav(); self.nav(blocked=True); self.assertEqual(self.drive.actual(),(0,0))
        self.assertEqual(self.bot.mode,Mode.NAVIGATION)
    def test_different_target_cannot_drive(self):
        self.navigation(); self.nav(target_id=99); self.assertEqual(self.drive.actual(),(0,0))
    def test_stale_frame_faults(self):
        self.navigation(); self.nav(captured=self.clock()-3); self.assertEqual(self.bot.mode,Mode.FAULT)
    def test_no_new_frames_expire_drive_and_fault(self):
        self.navigation(); self.nav(); self.clock.advance(1.1)
        self.assertEqual(self.drive.actual(),(0,0)); self.bot.tick()
        self.assertEqual(self.bot.mode,Mode.FAULT)
    def test_duplicate_frames_neither_count_nor_extend_lease(self):
        self.navigation(); event=self.nav(0.4)
        for _ in range(5): self.bot.worker_event(event)
        self.assertEqual(self.bot.arrival_count,1)
        self.clock.advance(1.1); self.bot.tick(); self.assertEqual(self.bot.mode,Mode.FAULT)
    def test_old_session_cannot_drive_in_gesture(self):
        self.gesture_mode()
        self.bot.worker_event(dict(type='nav',session=1,seq=99,captured=self.clock(),
                                   distance=1.5,target_id=0,blocked=False,accel=1,steer=0))
        self.assertEqual(self.bot.mode,Mode.GESTURE); self.assertEqual(self.drive.actual(),(0,0))
    def test_busy_lift_ignores_additional_selections(self):
        self.gesture_mode(); self.gesture('POINT'); self.gesture('PEACE')
        self.assertEqual(len([x for x in self.serial.history if 'Command_' in x]),1)
    def test_all_compartment_commands_match_protocol(self):
        for label,command in [('POINT','Command_1'),('PEACE','Command_2'),('FOUR','Command_3'),('OPEN_PALM','Command_4')]:
            with self.subTest(label=label):
                self.setUp(); self.gesture_mode(); self.gesture(label)
                self.assertTrue(self.serial.history[-1].endswith(command))
                self.complete(); self.assertEqual(self.bot.lift,'EXTENDED')
    def test_held_selection_does_not_repeat(self):
        self.gesture_mode(); self.gesture('POINT'); self.complete(); self.gesture('POINT',20)
        self.assertEqual(len([x for x in self.serial.history if 'Command_' in x]),1)
    def test_missing_done_faults_without_retry(self):
        self.gesture_mode(); self.serial.drop_done=True; self.gesture('POINT'); self.poll()
        self.clock.advance(9); self.bot.tick(); self.assertEqual(self.bot.mode,Mode.FAULT)
        self.assertEqual(self.bot.lift,'UNKNOWN')
        self.assertEqual(len([x for x in self.serial.history if 'Command_' in x]),1)
    def test_wrong_completion_id_faults(self):
        self.gesture_mode(); self.gesture('POINT')
        self.bot.actuator_event(dict(type='done',id=999,state='EXTENDED'))
        self.assertEqual(self.bot.mode,Mode.FAULT)
    def test_arduino_reset_invalidates_position(self):
        self.navigation(); self.serial._reply('BOOT ROBOBUTLER1'); self.poll()
        self.assertEqual(self.bot.mode,Mode.FAULT); self.assertEqual(self.bot.lift,'UNKNOWN')
    def test_worker_crash_faults(self):
        self.navigation(); self.nav()
        self.bot.worker_event(dict(type='exit',session=self.bot.session,code=1))
        self.assertEqual(self.bot.mode,Mode.FAULT); self.assertEqual(self.drive.actual(),(0,0))
    def test_nonfinite_command_faults(self):
        self.navigation(); self.nav(accel=float('nan')); self.assertEqual(self.bot.mode,Mode.FAULT)
    def test_near_tag_on_resume_remains_parked(self):
        self.gesture_mode(); self.gesture('THUMBS_UP',count=42); self.release(); self.ready()
        for _ in range(3): self.nav(0.4)
        self.assertEqual(self.bot.mode,Mode.STOPPING); self.assertEqual(self.drive.actual(),(0,0))
    def test_shutdown_cancels_pending_motion(self):
        self.gesture_mode(); self.gesture('POINT'); self.bot.shutdown()
        self.assertEqual(self.bot.mode,Mode.SHUTDOWN); self.assertIsNone(self.serial.pending)
        self.assertEqual(self.drive.actual(),(0,0)); self.assertFalse(self.bot.action('resume'))

class FilterTests(unittest.TestCase):
    def test_no_hand_breaks_stability(self):
        f=GestureFilter()
        for _ in range(4): self.assertIsNone(f.observe('POINT'))
        self.assertIsNone(f.observe('NO_HAND')); self.assertIsNone(f.observe('POINT'))
    def test_different_gesture_and_neutral_rearm(self):
        f=GestureFilter(2)
        self.assertIsNone(f.observe('POINT')); self.assertEqual(f.observe('POINT'),'Command_1')
        self.assertIsNone(f.observe('POINT')); self.assertIsNone(f.observe('FIST'))
        self.assertEqual(f.observe('FIST'),'RETURN')
        for _ in range(3): f.observe('NO_HAND')
        self.assertIsNone(f.observe('FIST')); self.assertEqual(f.observe('FIST'),'RETURN')

if __name__ == '__main__': unittest.main()
