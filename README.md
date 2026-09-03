````md
# Robobutler — Autonomous RC Car with Gesture-Controlled Actuation

Robobutler is an autonomous RC car developed for **UC San Diego ECE/MAE 148**. The project combines computer vision, motor control, embedded systems, and hardware integration.

The robot uses an **OAK-D Lite camera** and **Raspberry Pi** to detect AprilTags and navigate toward a target. A separate gesture-control system uses **MediaPipe Hands** to recognize hand gestures and send commands to an **Arduino Mega**, which controls a servo and stepper motor mechanism.

> **My Role:** Hardware Integration, Motor Control, Power Distribution, Arduino Actuation, and System Debugging

---

## Features

- AprilTag-based autonomous navigation
- OAK-D Lite RGB/depth vision
- Raspberry Pi vision processing
- VESC throttle and steering control
- MediaPipe hand gesture recognition
- Raspberry Pi-to-Arduino serial communication
- Servo and stepper motor actuation
- Custom power distribution for motors and control electronics

---

## System Architecture

### Autonomous Navigation Pipeline

```text
OAK-D Lite Camera
        ↓
AprilTag Detection
        ↓
Depth / Ground Detection
        ↓
EKF State Estimation
        ↓
Path Planning / MPC Controller
        ↓
VESC Motor Control
        ↓
RC Car Movement
````

### Hand Gesture Control Pipeline

```text
OAK-D Lite Camera
        ↓
MediaPipe Hands
        ↓
Raspberry Pi Gesture Classification
        ↓
PySerial USB Communication
        ↓
Arduino Mega
        ↓
Servo + Stepper Motor Actuation
```

---

## Hardware

* Raspberry Pi
* OAK-D Lite
* Arduino Mega
* VESC Motor Controller
* DRV8825 Stepper Driver
* Stepper Motor
* Servo Motor
* LiPo Battery
* DC-DC Converters / UBEC
* RC Car Chassis

---

## Software & Tools

* Python
* C/C++
* Arduino
* DepthAI
* OpenCV
* MediaPipe
* PySerial
* Linux / Raspberry Pi OS
* Git / GitHub

---

## My Contributions

My work focused primarily on the hardware and electromechanical systems of the robot.

* Integrated the Raspberry Pi and Arduino Mega using serial communication
* Developed Arduino control for the servo and stepper motor systems
* Wired and configured the DRV8825 stepper motor driver
* Designed and tested power distribution for the motors and control electronics
* Tuned stepper motor current limits and debugged overheating issues
* Integrated gesture commands with physical actuator movement
* Tested and debugged hardware, motor control, wiring, and communication issues

---

## Repository Structure

```text
Robobutler/
│
├── software/
│   ├── navigation/
│   ├── gesture_control/
│   └── arduino/
│
├── hardware/
│   ├── cad/
│   └── schematics/
│
├── docs/
├── media/
└── README.md
```

---

## Demo

Add photos or GIFs of the completed robot here.

```markdown
![Robobutler](media/robobutler.jpg)
```

---

## Course

**ECE/MAE 148 — Introduction to Autonomous Vehicles**
University of California, San Diego
Spring 2026

This repository is a personal portfolio version of a team project and highlights my individual hardware and system integration contributions.

```
```
