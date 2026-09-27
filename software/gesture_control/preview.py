"""Optional read-only localhost viewer. Never runs inference or sends commands."""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Preview:
    def __init__(self, port=0):
        self.enabled = bool(port)
        self.frame = None
        self.sequence = 0
        self.condition = threading.Condition()
        self.closed = False
        if not self.enabled:
            return
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                if self.path == '/':
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html')
                    self.end_headers()
                    self.wfile.write(b'<title>RoboButler gestures</title><h1>Gesture preview</h1><img src="/stream">')
                    return
                if self.path != '/stream':
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
                self.end_headers()
                self.connection.settimeout(1)
                last = -1
                try:
                    while not owner.closed:
                        with owner.condition:
                            owner.condition.wait_for(lambda: owner.closed or owner.sequence != last, timeout=1)
                            if owner.closed:
                                break
                            if owner.sequence == last or owner.frame is None:
                                continue
                            frame, last = owner.frame, owner.sequence
                        self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
                except OSError:
                    pass
        self.server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def publish(self, frame):
        with self.condition:
            self.frame = frame
            self.sequence += 1
            self.condition.notify_all()

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()
        if self.enabled:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=1)
