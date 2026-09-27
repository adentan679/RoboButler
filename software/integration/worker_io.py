import json
import sys
import threading
import time


class WorkerIO:
    def __init__(self, session):
        self.session = session
        self.output = sys.stdout
        # Team perception code prints diagnostics; keep JSON stdout clean.
        sys.stdout = sys.stderr
        self.stopping = threading.Event()
        threading.Thread(target=self._input, daemon=True).start()

    def _input(self):
        for line in sys.stdin:
            if line.strip() == 'STOP':
                self.stopping.set()
                return
        self.stopping.set()  # Parent died or closed its control pipe.

    def emit(self, kind, **fields):
        self.output.write(json.dumps({'type': kind, 'session': self.session, **fields},
                                     allow_nan=False) + '\n')
        self.output.flush()

    def wait(self, seconds=0.005):
        return self.stopping.wait(seconds)

    def frame(self, kind, seq, captured, **fields):
        self.emit(kind, seq=seq, captured=captured, **fields)
