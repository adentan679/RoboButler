#!/usr/bin/env python3
"""Default: a complete simulated round trip. Hardware is explicitly opt-in."""
import argparse
import json
from pathlib import Path
import queue
import sys
import threading
import time

from software.integration.core import Coordinator, Mode, Settings
from software.integration.processes import ProcessWorkers
from software.integration.hardware import ArduinoLink
from software.integration.simulation import SimDrive, SimSerial

ROOT = Path(__file__).resolve().parent


def keyboard(commands):
    for line in sys.stdin:
        commands.put(line.strip().lower())
    commands.put('quit')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--demo', action='store_true', help='Simulated round trip (default)')
    mode.add_argument('--hardware', action='store_true', help='Use real devices with supervised confirmations')
    parser.add_argument('--config', default=str(ROOT / 'config.example.json'))
    args = parser.parse_args(argv)
    config_path = Path(args.config).resolve()
    config = json.loads(config_path.read_text())
    settings = Settings(**{k: config[k] for k in Settings.__dataclass_fields__ if k in config})
    drive = actuator = workers = robot = None
    code = 0
    commands = queue.Queue()
    try:
        if args.hardware:
            from software.integration.hardware import DriveGuard, validate_ports
            if config.get('hardware_reviewed') is not True:
                raise ValueError('Read README hardware setup and set hardware_reviewed=true in your own config')
            validate_ports(config['vesc_port'], config['arduino_port'])
            for key in ('navigation_python', 'gesture_python'):
                if not Path(config[key]).is_absolute() or not Path(config[key]).is_file():
                    raise ValueError(f'Configure an existing absolute interpreter path: {key}')
            if not (ROOT / config['fastsam_model']).is_file():
                raise FileNotFoundError('Place original team FastSAM-s.pt at configured fastsam_model path')
            if not 0 < config['tag_size_m'] < 1:
                raise ValueError('Set measured tag_size_m')
            import serial
            sys.path.insert(0, str(ROOT / 'software/navigation'))
            from vesc_bridge import VESCBridge
            drive = DriveGuard(VESCBridge(port=config['vesc_port']))
            actuator = ArduinoLink(serial.Serial(config['arduino_port'], 9600, timeout=0, write_timeout=0.2))
            actuator.handshake()
            interpreters = {'navigation': config['navigation_python'], 'gesture': config['gesture_python']}
            print('Commands: stowed, start, stopped, status, quit')
            print('stowed = physically verified lift retracted and compartment safe for vehicle movement.')
            print('To resume after confirmed stow: hold an upright thumbs-up for two seconds.')
            print('stopped = physically verified vehicle at rest and held stationary.')
            threading.Thread(target=keyboard, args=(commands,), daemon=True).start()
        else:
            drive = SimDrive()
            actuator = ArduinoLink(SimSerial())
            actuator.write('HELLO')
            actuator.poll(handshaking=True)
            interpreters = {'navigation': sys.executable, 'gesture': sys.executable}
            print('SIMULATION ONLY: no camera, serial port, or motor opened.')
        workers = ProcessWorkers(ROOT, config_path, interpreters, simulate=not args.hardware)
        robot = Coordinator(drive, workers, actuator, time.monotonic, settings)
        started = time.monotonic()
        resumed_frames = 0
        while True:
            for event in workers.poll():
                robot.worker_event(event)
            for event in actuator.poll():
                robot.actuator_event(event)
            robot.tick()
            if robot.mode == Mode.FAULT:
                code = 1
                break
            if not args.hardware:
                if time.monotonic() - started > 15:
                    raise TimeoutError('Demo timed out')
                if robot.mode == Mode.BOOT:
                    if robot.lift == 'UNKNOWN' and not robot.pending:
                        robot.action('stowed')
                    elif robot.lift == 'STOWED' and not robot.pending:
                        robot.action('start')
                elif robot.mode == Mode.STOPPING:
                    print('SIMULATED confirmation: vehicle stopped')
                    robot.action('stopped')
                elif robot.mode == Mode.GESTURE and robot.lift == 'RETRACTED_UNVERIFIED' and not robot.pending:
                    print('SIMULATED confirmation: mechanism stowed')
                    robot.action('stowed')
                elif robot.mode == Mode.NAVIGATION and robot.session > 1 and drive.actual()[0] > 0:
                    resumed_frames += 1
                    if resumed_frames >= 5:
                        print('PASS: navigation -> gesture -> extend -> retract -> confirmed stow -> thumbs-up -> navigation')
                        break
            else:
                quit_requested = False
                while not commands.empty():
                    command = commands.get_nowait()
                    if command == 'quit':
                        quit_requested = True
                        break
                    if command == 'status':
                        print(robot.mode.value, robot.lift, 'pending=', robot.pending)
                    elif not robot.action(command):
                        print('Rejected: command not allowed in current mode/position.')
                if quit_requested:
                    break
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        if robot:
            robot.fault(str(exc))
        else:
            print(f'ERROR: {exc}', file=sys.stderr)
        code = 1
    finally:
        if robot:
            robot.shutdown()
        for resource in (drive, actuator, workers):
            if resource:
                try:
                    resource.close()
                except Exception as exc:
                    print(f'Cleanup error: {exc}', file=sys.stderr)
                    code = 1
    return code


if __name__ == '__main__':
    raise SystemExit(main())
