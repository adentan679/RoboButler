import unittest
from types import SimpleNamespace
from test_coordinator import CoordinatorTests as Fixtures
from software.integration.core import Mode, ResumeHold, Settings
from software.gesture_control.classifier import detect_gesture

class ResumeTests(unittest.TestCase):
    setUp=Fixtures.setUp
    poll=Fixtures.poll
    complete=Fixtures.complete
    ready=Fixtures.ready
    navigation=Fixtures.navigation
    nav=Fixtures.nav
    release=Fixtures.release
    gesture_mode=Fixtures.gesture_mode
    gesture=Fixtures.gesture

    def test_short_hold_then_two_second_hold(self):
        self.gesture_mode(); before=list(self.serial.history)
        self.gesture('THUMBS_UP',20); self.assertEqual(self.bot.mode,Mode.GESTURE)
        self.gesture('THUMBS_UP',22); self.assertEqual(self.bot.mode,Mode.RELEASING_GESTURE)
        self.assertEqual(self.serial.history,before)
        self.assertEqual(self.drive.actual(),(0,0))

    def test_no_hand_interrupts_hold(self):
        self.gesture_mode(); self.gesture('THUMBS_UP',30); self.gesture('NO_HAND',1)
        self.gesture('THUMBS_UP',20); self.assertEqual(self.bot.mode,Mode.GESTURE)
        self.gesture('THUMBS_UP',22); self.assertEqual(self.bot.mode,Mode.RELEASING_GESTURE)

    def test_busy_extended_and_unverified_retraction_reject_resume(self):
        def hold():
            for _ in range(42):
                self.gesture('THUMBS_UP',1)
                self.poll()  # Keep the simulated host heartbeat alive during long holds.
        self.gesture_mode(); self.serial.duration=3; self.gesture('POINT')
        hold(); self.assertEqual(self.bot.mode,Mode.GESTURE)
        self.assertIsNotNone(self.bot.pending)
        self.clock.advance(1); self.complete(); self.serial.duration=.1
        self.assertEqual(self.bot.lift,'EXTENDED')
        hold(); self.assertEqual(self.bot.mode,Mode.GESTURE)
        self.gesture('FIST'); self.complete()
        self.assertEqual(self.bot.lift,'RETRACTED_UNVERIFIED')
        hold(); self.assertEqual(self.bot.mode,Mode.GESTURE)
        self.bot.action('stowed'); self.complete()
        for _ in range(20): self.gesture('THUMBS_UP',1); self.poll()
        self.assertEqual(self.bot.mode,Mode.GESTURE)
        for _ in range(22): self.gesture('THUMBS_UP',1); self.poll()
        self.assertEqual(self.bot.mode,Mode.RELEASING_GESTURE)

    def test_typed_resume_no_longer_bypasses_gesture(self):
        self.gesture_mode(); self.assertFalse(self.bot.action('resume'))
        self.assertEqual(self.bot.mode,Mode.GESTURE)

    def test_duplicate_frames_cannot_finish_hold(self):
        self.gesture_mode(); self.gesture('THUMBS_UP',1)
        event=dict(type='gesture',session=self.bot.session,seq=self.seq,captured=self.clock(),label='THUMBS_UP')
        for _ in range(50):
            self.clock.advance(); self.bot.worker_event(event)
        self.assertEqual(self.bot.mode,Mode.GESTURE)
        self.bot.tick(); self.assertEqual(self.bot.mode,Mode.FAULT)

    def test_capture_gap_restarts_hold(self):
        self.gesture_mode(); self.gesture('THUMBS_UP',30); self.clock.advance(.4)
        self.gesture('THUMBS_UP',20); self.assertEqual(self.bot.mode,Mode.GESTURE)
        self.gesture('THUMBS_UP',22); self.assertEqual(self.bot.mode,Mode.RELEASING_GESTURE)

    def test_drive_fault_prevents_resume(self):
        self.gesture_mode(); self.drive.error='disconnected'; self.gesture('THUMBS_UP',42)
        self.assertEqual(self.bot.mode,Mode.FAULT)
        self.assertEqual(len([c for c in self.workers.calls if c[0]=='start']),2)

    def test_pre_confirmation_frames_cannot_start_hold(self):
        self.gesture_mode(); self.bot.action('stowed'); self.complete()
        self.bot.worker_event(dict(type='gesture',session=self.bot.session,seq=self.seq+1,
                                   captured=self.bot.resume_after-.01,label='THUMBS_UP'))
        self.assertIsNone(self.bot.resume_hold.start)

class HoldAndClassifierTests(unittest.TestCase):
    def test_hold_uses_elapsed_time_not_frame_count(self):
        hold=ResumeHold(2,.3,5)
        for i in range(100): self.assertFalse(hold.observe('THUMBS_UP',i*.001,True))
        self.assertFalse(hold.observe('THUMBS_UP',2.1,True))

    def hand(self,thumb_tip=(.4,.28),thumb_ip=(.4,.45), fingers=(0,0,0,0)):
        points=[SimpleNamespace(x=.5,y=.6) for _ in range(21)]
        points[0]=SimpleNamespace(x=.5,y=.85); points[9]=SimpleNamespace(x=.5,y=.55)
        points[2]=SimpleNamespace(x=.4,y=.62)
        points[3]=SimpleNamespace(x=thumb_ip[0],y=thumb_ip[1])
        points[4]=SimpleNamespace(x=thumb_tip[0],y=thumb_tip[1])
        for tip,pip,extended in zip([8,12,16,20],[6,10,14,18],fingers):
            points[pip]=SimpleNamespace(x=.5,y=.55)
            points[tip]=SimpleNamespace(x=.5,y=.3 if extended else .7)
        return SimpleNamespace(landmark=points)

    def test_vertical_thumb_up_on_either_hand(self):
        hand=self.hand(); self.assertEqual(detect_gesture(hand),'THUMBS_UP')
        for p in hand.landmark: p.x=1-p.x
        self.assertEqual(detect_gesture(hand),'THUMBS_UP')

    def test_sideways_down_and_fist_are_not_resume(self):
        for tip in [(.2,.45),(.4,.8),(.4,.47)]:
            with self.subTest(tip=tip):
                self.assertNotEqual(detect_gesture(self.hand(thumb_tip=tip)),'THUMBS_UP')

    def test_existing_selection_gestures_remain_distinct(self):
        for fingers,label in [((1,0,0,0),'POINT'),((1,1,0,0),'PEACE'),((1,1,1,0),'FOUR'),((1,1,1,1),'OPEN_PALM')]:
            with self.subTest(label=label):
                self.assertEqual(detect_gesture(self.hand(thumb_tip=(.2,.45),fingers=fingers)),label)

    def test_bad_hold_settings_rejected(self):
        for value in [0,-1,float('nan')]:
            with self.subTest(value=value),self.assertRaises(ValueError): Settings(resume_hold_seconds=value)

# Avoid rediscovering imported fixture tests in this module.
del Fixtures
