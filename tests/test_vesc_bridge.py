"""Packet-level regression tests; no robot or third-party packages required."""
import importlib.util
from pathlib import Path
import struct
import sys
import types
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    'bridge_under_test', Path(__file__).resolve().parents[1] / 'software/navigation/vesc_bridge.py')
bridge = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {'serial': types.SimpleNamespace(Serial=None)}):
    spec.loader.exec_module(bridge)

class FakeSerial:
    def __init__(self, *args, **kwargs):
        self.packets = []
        self.closed = False
        self.fail = False
        self.short = False
    def write(self, data):
        if self.fail:
            raise IOError('disconnected')
        self.packets.append(data)
        return len(data) - int(self.short)
    def close(self):
        self.closed = True

class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.device = FakeSerial()
        self.factory = patch.object(bridge.serial, 'Serial', return_value=self.device)
        self.exists = patch.object(bridge.os.path, 'exists', return_value=True)
        self.factory.start()
        self.exists.start()
        self.addCleanup(self.factory.stop)
        self.addCleanup(self.exists.stop)
        self.driver = bridge.VESCBridge(port='/dev/serial/by-id/verified-vesc')

    def duties(self):
        return [struct.unpack('>i', p[3:7])[0] for p in self.device.packets if p[2] == 5]

    def test_first_zero_after_driving_is_zero(self):
        self.driver.send_command(1.0, 0.3)
        self.driver.send_command(0.0, 0.0)
        self.assertEqual(self.duties(), [7000, 0])
        self.assertEqual(self.device.packets[2][2], 5)

    def test_negative_never_repeats_forward_command(self):
        self.driver.send_command(1.0, 0.0)
        self.driver.send_command(-1.0, 0.0)
        self.assertEqual(self.duties(), [7000, 0])

    def test_missing_verified_device_does_not_fallback(self):
        with patch.object(bridge.os.path, 'exists', return_value=False):
            with self.assertRaises(FileNotFoundError):
                bridge.VESCBridge(port='/dev/serial/by-id/missing')

    def test_numbered_or_unspecified_port_rejected(self):
        for port in [None, '/dev/ttyACM0', '/dev/ttyACM1']:
            with self.subTest(port=port), self.assertRaises(ValueError):
                bridge.VESCBridge(port=port)

    def test_connection_error_propagates(self):
        with patch.object(bridge.serial, 'Serial', side_effect=IOError('missing')):
            with self.assertRaises(IOError):
                bridge.VESCBridge(port='/dev/serial/by-id/verified-vesc')

    def test_serial_error_propagates_without_reconnection(self):
        self.device.fail = True
        with self.assertRaises(IOError):
            self.driver.send_command(1.0, 0.0)
        self.assertEqual(bridge.serial.Serial.call_count, 1)

    def test_close_releases_port_when_stop_fails(self):
        self.device.fail = True
        with self.assertRaises(IOError):
            self.driver.close()
        self.assertTrue(self.device.closed)

    def test_short_write_is_error(self):
        self.device.short = True
        with self.assertRaises(IOError):
            self.driver.send_command(1.0, 0.0)

    def test_nonfinite_command_requests_zero_and_raises(self):
        for value in [float('nan'), float('inf')]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.driver.send_command(value, 0.0)
        self.assertEqual(self.duties(), [0, 0])

if __name__ == '__main__':
    unittest.main()
