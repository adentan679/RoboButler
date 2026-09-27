import io
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch
from software.integration.hardware import ArduinoLink, DriveGuard, validate_ports
from software.integration.simulation import SimSerial

ROOT=Path(__file__).resolve().parents[1]

class AdapterTests(unittest.TestCase):
    def test_serial_partial_lines_and_command_responses(self):
        serial=SimSerial(duration=0); link=ArduinoLink(serial)
        serial.rx.extend(b'READY ROBO'); self.assertEqual(link.poll(handshaking=True),[])
        self.assertFalse(link.ready); serial.rx.extend(b'BUTLER1\n')
        link.poll(handshaking=True); self.assertTrue(link.ready)
        link.send(1,'STOW'); events=link.poll()
        self.assertEqual(events,[{'type':'ack','id':1},{'type':'done','id':1,'state':'STOWED'}])
    def test_legacy_firmware_rejected(self):
        serial=SimSerial(); link=ArduinoLink(serial)
        serial.rx.extend(b'Arduino ready.\n')
        self.assertEqual(link.poll(handshaking=True)[0]['type'],'fault')
        self.assertFalse(link.ready)
    def test_serial_disconnect_is_not_swallowed(self):
        serial=SimSerial(); link=ArduinoLink(serial); serial.fail=True
        with self.assertRaises(IOError): link.poll()
    def test_same_resolved_ports_rejected(self):
        with patch('os.path.exists',return_value=True), patch('os.path.realpath',return_value='/dev/ttyACM0'):
            with self.assertRaises(ValueError):
                validate_ports('/dev/serial/by-id/vesc','/dev/serial/by-id/arduino')
    def test_unknown_port_rejected(self):
        with self.assertRaises(ValueError): validate_ports('/dev/ttyACM0','/dev/ttyACM1')
    def test_drive_guard_expires_without_parent_updates(self):
        class Bridge:
            def __init__(self): self.events=[]; self.forward=threading.Event(); self.zero=threading.Event(); self.closed=False
            def send_command(self,a,s):
                self.events.append((a,s))
                if a>0: self.forward.set()
                elif self.forward.is_set(): self.zero.set()
            def close(self): self.closed=True
        bridge=Bridge(); guard=DriveGuard(bridge)
        try:
            guard.command(.5,.1,time.monotonic()+.2)
            self.assertTrue(bridge.forward.wait(1))
            self.assertTrue(bridge.zero.wait(1))
            self.assertEqual(bridge.events[-1],(0,0))
        finally: guard.close()
        self.assertTrue(bridge.closed)
    def test_drive_guard_reports_serial_failure(self):
        class Bridge:
            def send_command(self,*a): raise IOError('disconnected')
            def close(self): pass
        guard=DriveGuard(Bridge()); guard.thread.join(1)
        self.assertIn('disconnected',guard.error); guard.close()
    def test_real_subprocess_round_trip_and_exclusive_camera(self):
        result=subprocess.run([sys.executable,'run_robot.py','--demo'],cwd=ROOT,
                              capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('PASS: navigation -> gesture -> extend -> retract -> confirmed stow -> thumbs-up -> navigation',result.stdout)
        import socket
        with socket.socket() as camera:
            camera.bind(('127.0.0.1',47831))
        self.assertEqual(result.stdout.count('MODE NAVIGATION'),2)

class ControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try: import numpy
        except ImportError: raise unittest.SkipTest('Install numpy for actual path-controller tests')
        sys.path.insert(0,str(ROOT/'software/navigation'))
        from mpc_controller import PathFollowingController, ControllerConfig
        cls.Controller=PathFollowingController; cls.Config=ControllerConfig
    def compute(self,path,obstacles=[]):
        from contextlib import redirect_stdout
        with redirect_stdout(io.StringIO()):
            return self.Controller(self.Config()).compute_control(path,obstacles)
    def test_near_endpoint_no_longer_stops_short(self):
        from types import SimpleNamespace
        for distance in [1.3,1.0,.6]:
            with self.subTest(distance=distance):
                self.assertGreater(self.compute([SimpleNamespace(end=[0,0,distance])])[0],0)
    def test_empty_or_behind_path_stops(self):
        self.assertEqual(self.compute([]),(0,0))
        self.assertEqual(self.compute([(0,-1)]),(0,0))
    def test_near_obstacle_stops(self):
        from types import SimpleNamespace
        self.assertEqual(self.compute([(0,2)],[SimpleNamespace(distance=.3)]),(0,0))

if __name__=='__main__': unittest.main()
