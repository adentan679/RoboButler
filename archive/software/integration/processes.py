"""One subprocess at a time; JSON lines are isolated from library diagnostics."""
import json
import queue
import subprocess
import threading
from pathlib import Path


class ProcessWorkers:
    def __init__(self, root, config_path, interpreters, simulate=False):
        self.root, self.config_path = Path(root), str(config_path)
        self.interpreters, self.simulate = interpreters, simulate
        self.process = None
        self.events = queue.Queue(maxsize=256)
        self.reader = None
        self.log_file = None
        self.session = None
        self.error = None

    def start(self, kind, session):
        if self.process is not None:
            if self.process.poll() is None or self.reader.is_alive():
                raise RuntimeError('Previous camera worker has not fully exited')
            self.process.stdin.close()
            self.process.stdout.close()
            self.log_file.close()
        self.session = session
        log_dir = self.root / 'logs'
        log_dir.mkdir(exist_ok=True)
        self.log_file = (log_dir / f'{session:03d}_{kind}.log').open('w', encoding='utf-8')
        module = 'software.integration.sim_worker' if self.simulate else 'software.integration.vision_worker'
        args = [self.interpreters[kind], '-u', '-m', module, '--kind', kind,
                '--session', str(session), '--config', self.config_path]
        self.process = subprocess.Popen(args, cwd=self.root, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=self.log_file,
                                        text=True, encoding='utf-8', bufsize=1)
        self.reader = threading.Thread(target=self._read, args=(self.process, session), daemon=True)
        self.reader.start()

    def _put(self, event):
        try:
            self.events.put_nowait(event)
        except queue.Full:
            self.error = 'Worker event queue overflow'

    def _read(self, process, session):
        try:
            while True:
                line = process.stdout.readline(65537)
                if not line:
                    break
                if len(line) > 65536 or not line.endswith('\n'):
                    raise ValueError('Oversized/truncated worker message')
                message = json.loads(line)
                if not isinstance(message, dict) or message.get('session') != session:
                    raise ValueError('Invalid worker session')
                self._put(message)
            code = process.wait()
            self._put({'type': 'exit', 'session': session, 'code': code})
        except Exception as exc:
            self._put({'type': 'fault', 'session': session, 'error': str(exc)})

    def poll(self):
        result = []
        # An exit event may be queued just before the reader thread returns.
        # Join that finished read loop before allowing a new process to start.
        for _ in range(256):
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            if event['type'] == 'exit':
                self.reader.join(timeout=0.1)
            result.append(event)
        if self.error:
            result.append({'type': 'fault', 'session': self.session, 'error': self.error})
            self.error = None
        return result

    def request_stop(self, session):
        if self.process is not None and self.process.poll() is None and session == self.session:
            self.process.stdin.write('STOP\n')
            self.process.stdin.flush()

    def close(self):
        if self.process is None:
            return
        try:
            self.request_stop(self.session)
        except (OSError, ValueError):
            pass
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=1)
        self.reader.join(timeout=1)
        self.process.stdin.close()
        self.process.stdout.close()
        self.log_file.close()
