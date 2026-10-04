# Source attribution and implementation notes

Original team repository:
https://github.com/UCSD-Silberman-Classes-and-Projects/spring-2026-final-project-team-17/tree/5b2ddda989908b18566bfb2381e0f541582ae974

Navigation modules and FastSAM-s.pt originate in that revision's VisCarPath folder. Gesture landmark rules originate in hand_gesture/gesture_servo_stepper.py. Existing pin assignments, servo mapping and pulse-count settings originate in hand_gesture/project_servo_stepper.ino. Preserve the team's attribution and upstream dependency/model licenses if redistributing this project; this package does not assert a new license over those materials.

Current repository integration layer: supervisor, worker protocol/lifecycle, persistent serial adapters, default simulator, tests and protocol firmware. Adapted for the unified application: camera-only navigation mode, freshness checks, near-endpoint following, FastSAM thread shutdown/failure propagation and VESC stop/port behavior. The original FastSAM weights are copied unchanged; no model inference/training was performed here.

Official API references consulted:

- Luxonis DepthAI v2/v3 migration: https://docs.luxonis.com/software-v3/depthai/tutorials/v2-vs-v3
- Luxonis v3 camera context and output queues: https://docs.luxonis.com/software-v3/depthai/examples/camera/camera_output
- Luxonis host-synchronized monotonic timestamps: https://docs.luxonis.com/software-v3/depthai/depthai-components/device

Hardware mode targets the Raspberry Pi's Linux host. getTimestamp() is the DepthAI host-synchronized monotonic time; getTimestampDevice() is not used for supervisor message age. Pi-side camera/API and installed-wheel compatibility still require validation on that platform.

Gesture-resume update: added a scale-relative upright-thumb rule, timed hold with stow/motion gates, and simulated coverage. The existing selection rules and integrated Arduino firmware are retained.

The active `software/` tree is the current unified implementation. `archive/software/` preserves the original course subsystem snapshot so the source lineage and later coordination changes remain traceable.
