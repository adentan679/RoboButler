from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

class FirmwareTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('g++'),'Optional native firmware test requires g++')
    def test_actual_firmware_with_fake_arduino(self):
        folder=Path(__file__).resolve().parent/'firmware_mock'
        with tempfile.TemporaryDirectory() as temp:
            binary=Path(temp)/'firmware-test'
            build=subprocess.run(['g++','-std=c++11','-Wall','-Wextra','-Werror','-I',str(folder),
                                  str(folder/'harness.cpp'),'-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(build.returncode,0,build.stderr)
            run=subprocess.run([str(binary)],capture_output=True,text=True,timeout=5)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            self.assertIn('PASS native firmware',run.stdout)
