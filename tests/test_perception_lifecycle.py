"""Exercise actual FastSAM lifecycle methods without importing/loading its model."""
import ast
from pathlib import Path
import threading
import unittest

class PerceptionLifecycleTests(unittest.TestCase):
    def test_background_worker_stops_and_propagates_model_failure(self):
        path=Path(__file__).resolve().parents[1]/'software/navigation/ground_obstacle_detection.py'
        tree=ast.parse(path.read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='RGBDepthFusion')
        methods=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in ('_worker','close','submit_frame','get_latest_masks')]
        module=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),
                               ast.ClassDef(name='Fusion',bases=[],keywords=[],body=methods,decorator_list=[])],type_ignores=[])
        ns={}; exec(compile(ast.fix_missing_locations(module),str(path),'exec'),ns)
        obj=ns['Fusion'](); obj._closing=threading.Event(); obj._lock=threading.Lock()
        obj.error=None; obj._pending_frame=None; obj._latest_masks=[]
        obj._thread=threading.Thread(target=obj._worker); obj._thread.start(); obj.close()
        self.assertFalse(obj._thread.is_alive())
        obj._closing.clear(); obj._pending_frame=object()
        def fail(frame): raise ValueError('inference failed')
        obj._run_fastsam_sync=fail; obj._thread=threading.Thread(target=obj._worker)
        obj._thread.start(); obj._thread.join(1)
        self.assertIsInstance(obj.error,ValueError)
        with self.assertRaises(RuntimeError): obj.get_latest_masks()
        obj.close()
