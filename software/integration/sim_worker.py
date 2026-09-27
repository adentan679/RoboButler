"""Synthetic camera process exercising the real subprocess handoff interface."""
import argparse
import json
import socket
from pathlib import Path
import time
from .worker_io import WorkerIO


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--kind', required=True)
    parser.add_argument('--session', type=int, required=True)
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    io = WorkerIO(args.session)
    config = json.loads(Path(args.config).read_text())
    root = Path(__file__).resolve().parents[2]
    camera_lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
        camera_lock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        # A loopback port stands in for exclusive camera ownership. The OS
        # releases it even if the simulated worker crashes or is killed.
        camera_lock.bind(('127.0.0.1', config.get('simulation_camera_port', 47831)))
        io.emit('ready')
        started = time.monotonic()
        seq = 0
        while not io.stopping.is_set():
            elapsed = time.monotonic() - started
            seq += 1
            captured = time.monotonic()
            if args.kind == 'navigation':
                # First approach ends near tag. Resumed navigation sees a new,
                # farther-away observation of the SAME selected tag.
                distance = 1.5 if args.session > 1 or elapsed < 0.3 else 0.8 if elapsed < 0.6 else 0.4
                io.frame('nav', seq, captured, target_id=config['target_id'],
                         distance=distance, accel=0.4, steer=0.0, blocked=False)
            else:
                label = ('POINT' if elapsed < 0.6 else 'NO_HAND' if elapsed < 0.8
                         else 'FIST' if elapsed < 1.5 else 'NO_HAND' if elapsed < 1.8 else 'THUMBS_UP')
                io.frame('gesture', seq, captured, label=label)
            io.wait(0.05)
        camera_lock.close()
        io.emit('released')
    except Exception as exc:
        io.emit('fault', error=str(exc))
        raise
    finally:
        camera_lock.close()


if __name__ == '__main__':
    main()
