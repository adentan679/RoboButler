"""Camera-only worker; separate interpreters keep DepthAI v2/v3 isolated."""
import argparse
import json
from pathlib import Path
import sys
import time
from .worker_io import WorkerIO


def navigation(io, config, root):
    sys.path.insert(0, str(root / 'software/navigation'))
    from main_navigation import AutonomousNavigator
    navigator = AutonomousNavigator(target_tag_id=config['target_id'],
                                    fastsam_model=str(root / config['fastsam_model']), camera_only=True,
                                    arrival_distance=config['arrival_m'])
    navigator.tag_detector.tag_size = config['tag_size_m']
    try:
        navigator.start()
        io.emit('ready')
        while not io.stopping.is_set():
            command = navigator.process_frame()
            if command is None:
                io.wait()
                continue
            # A frame alone is not permission to drive: require valid ground/path/state.
            allowed = navigator.navigation_state.value == 'navigating' and navigator.last_ground is not None
            io.frame('nav', navigator.frame_sequence, navigator.frame_timestamp,
                     target_id=config['target_id'] if navigator.target_distance is not None else None,
                     distance=navigator.target_distance, blocked=not allowed,
                     accel=float(command.acceleration), steer=float(command.steering_rate))
    finally:
        navigator.stop()
    io.emit('released')


def gesture(io, config, root):
    import cv2
    import depthai as dai
    import mediapipe as mp
    from software.gesture_control.classifier import detect_gesture
    from software.gesture_control.preview import Preview
    preview = Preview(config.get('preview_port', 0))
    try:
        # Context exit closes the pipeline/device before RELEASED is emitted.
        with dai.Pipeline() as pipeline:
            camera = pipeline.create(dai.node.Camera).build()
            output = camera.requestOutput(size=(480, 480), type=dai.ImgFrame.Type.BGR888p,
                                          resizeMode=dai.ImgResizeMode.CROP, fps=15)
            queue = output.createOutputQueue(maxSize=1, blocking=False)
            with mp.solutions.hands.Hands(static_image_mode=False, max_num_hands=1,
                                         min_detection_confidence=0.6, min_tracking_confidence=0.6) as hands:
                pipeline.start()
                io.emit('ready')
                last_seq = -1
                while not io.stopping.is_set():
                    if not pipeline.isRunning():
                        raise RuntimeError('Gesture camera pipeline stopped')
                    packet = queue.tryGet()
                    if packet is None:
                        io.wait()
                        continue
                    seq = packet.getSequenceNum()
                    if seq <= last_seq:
                        continue
                    last_seq = seq
                    captured = packet.getTimestamp().total_seconds()
                    frame = packet.getCvFrame()
                    results = hands.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                    label = detect_gesture(results.multi_hand_landmarks[0]) if results.multi_hand_landmarks else 'NO_HAND'
                    io.frame('gesture', seq, captured, label=label)
                    if preview.enabled:
                        cv2.putText(frame, label, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255,255,255), 2)
                        ok, data = cv2.imencode('.jpg', frame)
                        if ok:
                            preview.publish(data.tobytes())
    finally:
        preview.close()
    io.emit('released')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--kind', choices=['navigation', 'gesture'], required=True)
    parser.add_argument('--session', type=int, required=True)
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    io = WorkerIO(args.session)
    try:
        config = json.loads(Path(args.config).read_text())
        root = Path(__file__).resolve().parents[2]
        (navigation if args.kind == 'navigation' else gesture)(io, config, root)
    except Exception as exc:
        io.emit('fault', error=f'{type(exc).__name__}: {exc}')
        raise


if __name__ == '__main__':
    main()
