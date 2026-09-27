"""Execute production vision-worker loops with mocked camera/ML APIs."""
import threading
import time
import types
import unittest
from unittest.mock import patch
from pathlib import Path
from software.integration.vision_worker import gesture, navigation

class IO:
    def __init__(self): self.stopping=threading.Event(); self.events=[]; self.frames=[]
    def emit(self,kind,**fields): self.events.append(kind)
    def frame(self,kind,seq,captured,**fields): self.frames.append((kind,seq,fields))
    def wait(self,*a): pass

class VisionWorkerTests(unittest.TestCase):
    def test_gesture_processes_fresh_frames_without_browser_and_closes(self):
        io=IO(); calls=[]
        class Packet:
            def __init__(self,seq): self.seq=seq
            def getSequenceNum(self): return self.seq
            def getTimestamp(self): return types.SimpleNamespace(total_seconds=time.monotonic)
            def getCvFrame(self): return object()
        packets=[Packet(1),Packet(1),Packet(2)]
        class Output:
            def createOutputQueue(self,**kwargs): return self
            def tryGet(self):
                if packets: return packets.pop(0)
                io.stopping.set(); return None
        class Camera:
            def build(self): return self
            def requestOutput(self,**kwargs): return Output()
        class Pipeline:
            def __enter__(self): calls.append('camera_open'); return self
            def __exit__(self,*args): calls.append('camera_close')
            def create(self,*args): return Camera()
            def start(self): pass
            def isRunning(self): return True
        class Hands:
            def __init__(self,**kwargs): pass
            def __enter__(self): return self
            def __exit__(self,*args): calls.append('hands_close')
            def process(self,frame): calls.append('inference'); return types.SimpleNamespace(multi_hand_landmarks=None)
        dai=types.SimpleNamespace(Pipeline=Pipeline,node=types.SimpleNamespace(Camera=Camera),
                                 ImgFrame=types.SimpleNamespace(Type=types.SimpleNamespace(BGR888p=1)),
                                 ImgResizeMode=types.SimpleNamespace(CROP=1))
        cv2=types.SimpleNamespace(cvtColor=lambda x,c:x,COLOR_BGR2RGB=1)
        mp=types.SimpleNamespace(solutions=types.SimpleNamespace(hands=types.SimpleNamespace(Hands=Hands)))
        with patch.dict('sys.modules',{'depthai':dai,'cv2':cv2,'mediapipe':mp}):
            gesture(io,{'preview_port':0},Path('.'))
        self.assertEqual(calls.count('inference'),2)
        self.assertEqual([f[1] for f in io.frames],[1,2])
        self.assertEqual([f[2]['label'] for f in io.frames],['NO_HAND','NO_HAND'])
        self.assertIn('camera_close',calls); self.assertIn('hands_close',calls)
        self.assertEqual(io.events,['ready','released'])

    def run_navigation(self,fail=False):
        io=IO(); calls=[]
        class Navigator:
            def __init__(self,**kwargs):
                calls.append(kwargs)
                self.tag_detector=types.SimpleNamespace(tag_size=None)
                self.navigation_state=types.SimpleNamespace(value='navigating')
                self.last_ground=object(); self.frame_sequence=1
                self.frame_timestamp=time.monotonic(); self.target_distance=.8
            def start(self): calls.append('start')
            def process_frame(self):
                if fail: raise RuntimeError('camera lost')
                io.stopping.set()
                return types.SimpleNamespace(acceleration=.3,steering_rate=.1)
            def stop(self): calls.append('close')
        config={'target_id':7,'fastsam_model':'model.pt','tag_size_m':.15,'arrival_m':.5}
        with patch.dict('sys.modules',{'main_navigation':types.SimpleNamespace(AutonomousNavigator=Navigator)}):
            if fail:
                with self.assertRaises(RuntimeError): navigation(io,config,Path('.'))
            else: navigation(io,config,Path('.'))
        return io,calls
    def test_navigation_worker_is_camera_only_and_emits_commands(self):
        io,calls=self.run_navigation()
        self.assertTrue(calls[0]['camera_only'])
        self.assertEqual(calls[0]['arrival_distance'],.5)
        self.assertEqual(io.frames[0][2]['target_id'],7)
        self.assertEqual(io.frames[0][2]['accel'],.3)
        self.assertEqual(io.events,['ready','released']); self.assertEqual(calls[-1],'close')
    def test_navigation_camera_error_closes_without_release_success(self):
        io,calls=self.run_navigation(fail=True)
        self.assertEqual(calls[-1],'close'); self.assertNotIn('released',io.events)

if __name__=='__main__': unittest.main()
