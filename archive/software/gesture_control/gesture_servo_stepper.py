#!/usr/bin/env python3

from flask import Flask, Response
import cv2
import depthai as dai
import mediapipe as mp
import threading
import serial
import time
import socket

# -----------------------------
# Arduino Serial Setup
# -----------------------------
ARDUINO_PORT = "/dev/ttyACM0"   # Change to /dev/ttyACM1 if needed
BAUD_RATE = 9600

arduino = None

try:
    arduino = serial.Serial(ARDUINO_PORT, BAUD_RATE, timeout=1)
    time.sleep(2)  # Wait for Arduino reset
    print(f"Connected to Arduino on {ARDUINO_PORT}")
except Exception as e:
    print("Could not connect to Arduino.")
    print(e)
    print("Gesture detection will still run, but no motor commands will be sent.")

# -----------------------------
# Flask Web Server
# -----------------------------
app = Flask(__name__)

latest_frame = None
frame_lock = threading.Lock()

# Command cooldown prevents repeated commands from being sent too quickly
last_command = None
last_command_time = 0
COMMAND_COOLDOWN = 3.0

# Gesture stability prevents noisy one-frame detections from triggering motors
last_detected_gesture = None
stable_gesture_count = 0
GESTURE_STABLE_FRAMES = 5

# -----------------------------
# MediaPipe Hands Setup
# -----------------------------
mp_hands = mp.solutions.hands
mp_draw = mp.solutions.drawing_utils

hands = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=1,
    min_detection_confidence=0.6,
    min_tracking_confidence=0.6
)

# -----------------------------
# OAK-D Lite DepthAI Setup
# -----------------------------
pipeline = dai.Pipeline()

camera = pipeline.create(dai.node.Camera).build()

output = camera.requestOutput(
    size=(480, 480),
    type=dai.ImgFrame.Type.BGR888p,
    resizeMode=dai.ImgResizeMode.CROP,
    fps=15
)

q_rgb = output.createOutputQueue(maxSize=4, blocking=False)

pipeline.start()


# -----------------------------
# Helper: Get Raspberry Pi IP
# -----------------------------
def get_local_ip():
    try:
        hostname = socket.gethostname()
        return socket.gethostbyname(hostname)
    except Exception:
        return "Raspberry Pi IP not found"


# -----------------------------
# Helper: Send command to Arduino
# -----------------------------
def send_command(command):
    global last_command, last_command_time

    current_time = time.time()

    # Prevent sending the same command too quickly
    if command == last_command and current_time - last_command_time < COMMAND_COOLDOWN:
        return

    last_command = command
    last_command_time = current_time

    print(f"Sending command: {command}")

    if arduino is not None:
        try:
            arduino.write((command + "\n").encode())

            # Optional: read Arduino response if available
            time.sleep(0.05)
            while arduino.in_waiting > 0:
                response = arduino.readline().decode(errors="ignore").strip()
                if response:
                    print(f"Arduino says: {response}")

        except Exception as e:
            print("Serial write error:", e)


# -----------------------------
# Gesture Detection Logic
# -----------------------------
def detect_gesture(hand_landmarks):
    """
    Basic hand gesture detection using MediaPipe landmarks.
    Works best when the palm is facing the camera.

    Finger order:
    thumb, index, middle, ring, pinky
    """

    fingers = []

    # -----------------------------
    # Thumb Detection
    # -----------------------------
    # This is a simple thumb rule based on horizontal distance.
    # It may vary depending on hand orientation.
    thumb_tip = hand_landmarks.landmark[4]
    thumb_ip = hand_landmarks.landmark[3]

    if abs(thumb_tip.x - thumb_ip.x) > 0.04:
        fingers.append(1)
    else:
        fingers.append(0)

    # -----------------------------
    # Other Finger Detection
    # -----------------------------
    # For index, middle, ring, pinky:
    # If fingertip is above the PIP joint, the finger is extended.
    finger_tips = [8, 12, 16, 20]
    finger_pips = [6, 10, 14, 18]

    for tip_id, pip_id in zip(finger_tips, finger_pips):
        tip = hand_landmarks.landmark[tip_id]
        pip = hand_landmarks.landmark[pip_id]

        if tip.y < pip.y:
            fingers.append(1)
        else:
            fingers.append(0)

    thumb, index, middle, ring, pinky = fingers
    total = sum(fingers)

    # -----------------------------
    # Gesture Rules
    # -----------------------------
    # Fist: no fingers extended
    if total == 0:
        return "FIST"

    # Point: index only
    if index == 1 and middle == 0 and ring == 0 and pinky == 0:
        return "POINT"

    # Peace: index and middle
    if index == 1 and middle == 1 and ring == 0 and pinky == 0:
        return "PEACE"

    # Three fingers: thumb, index, middle, ring extended and pinky folded
    # Adjust this if your preferred three-finger gesture is different.
    if thumb == 1 and index == 1 and middle == 1 and ring == 1 and pinky == 0:
        return "THREE"

    # Open palm: most or all fingers extended
    if total >= 4:
        return "OPEN_PALM"

    return "UNKNOWN"


# -----------------------------
# Map Gesture to Arduino Command
# -----------------------------
def gesture_to_command(gesture):
    """
    Gesture mapping:

    POINT      -> Command_1 -> Servo 0 degrees + stepper extends
    PEACE      -> Command_2 -> Servo 90 degrees + stepper extends
    THREE      -> Command_3 -> Servo 180 degrees + stepper extends
    OPEN_PALM  -> Command_4 -> Servo 270 degrees + stepper extends
    FIST       -> RETURN    -> Stepper returns to rest
    """

    if gesture == "POINT":
        return "Command_1"

    elif gesture == "PEACE":
        return "Command_2"

    elif gesture == "THREE":
        return "Command_3"

    elif gesture == "OPEN_PALM":
        return "Command_4"

    elif gesture == "FIST":
        return "RETURN"

    else:
        return None


# -----------------------------
# Stable Gesture Filter
# -----------------------------
def get_stable_command(gesture):
    """
    Requires the same gesture to be detected for several frames
    before sending a command to the Arduino.
    """

    global last_detected_gesture, stable_gesture_count

    if gesture == last_detected_gesture:
        stable_gesture_count += 1
    else:
        last_detected_gesture = gesture
        stable_gesture_count = 1

    if stable_gesture_count >= GESTURE_STABLE_FRAMES:
        return gesture_to_command(gesture)

    return None


# -----------------------------
# Camera Thread
# -----------------------------
def camera_loop():
    global latest_frame

    while True:
        in_rgb = q_rgb.get()
        frame = in_rgb.getCvFrame()

        with frame_lock:
            latest_frame = frame.copy()


# -----------------------------
# Video Stream with Detection
# -----------------------------
def generate_frames():
    while True:
        with frame_lock:
            if latest_frame is None:
                continue
            frame = latest_frame.copy()

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = hands.process(rgb_frame)

        gesture_text = "NO HAND"
        command_text = "NO COMMAND"

        if results.multi_hand_landmarks:
            for hand_landmarks in results.multi_hand_landmarks:
                mp_draw.draw_landmarks(
                    frame,
                    hand_landmarks,
                    mp_hands.HAND_CONNECTIONS
                )

                gesture = detect_gesture(hand_landmarks)
                gesture_text = gesture

                command = get_stable_command(gesture)

                if command is not None:
                    command_text = command
                    send_command(command)

        else:
            gesture_text = "NO HAND"
            command_text = "NO COMMAND"

        # Draw text on camera feed
        cv2.putText(
            frame,
            f"Gesture: {gesture_text}",
            (20, 45),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (255, 255, 255),
            2
        )

        cv2.putText(
            frame,
            f"Command: {command_text}",
            (20, 85),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (255, 255, 255),
            2
        )

        ret, buffer = cv2.imencode(".jpg", frame)
        if not ret:
            continue

        frame_bytes = buffer.tobytes()

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
        )


# -----------------------------
# Flask Routes
# -----------------------------
@app.route("/")
def index():
    return """
    <html>
        <head>
            <title>OAK-D Lite Gesture Control</title>
        </head>
        <body style="text-align:center; font-family:Arial;">
            <h1>OAK-D Lite + MediaPipe + Arduino Control</h1>

            <img src="/video_feed" width="640" height="480">

            <h2>Gesture Mapping</h2>

            <table border="1" style="margin-left:auto; margin-right:auto; border-collapse:collapse; font-size:18px;">
                <tr>
                    <th style="padding:8px;">Gesture</th>
                    <th style="padding:8px;">Raspberry Pi Command</th>
                    <th style="padding:8px;">Arduino Action</th>
                </tr>
                <tr>
                    <td style="padding:8px;">Point</td>
                    <td style="padding:8px;">Command_1</td>
                    <td style="padding:8px;">Servo moves to 0 degrees, then stepper extends</td>
                </tr>
                <tr>
                    <td style="padding:8px;">Peace Sign</td>
                    <td style="padding:8px;">Command_2</td>
                    <td style="padding:8px;">Servo moves to 90 degrees, then stepper extends</td>
                </tr>
                <tr>
                    <td style="padding:8px;">Three Fingers</td>
                    <td style="padding:8px;">Command_3</td>
                    <td style="padding:8px;">Servo moves to 180 degrees, then stepper extends</td>
                </tr>
                <tr>
                    <td style="padding:8px;">Open Palm</td>
                    <td style="padding:8px;">Command_4</td>
                    <td style="padding:8px;">Servo moves to 270 degrees, then stepper extends</td>
                </tr>
                <tr>
                    <td style="padding:8px;">Fist</td>
                    <td style="padding:8px;">RETURN</td>
                    <td style="padding:8px;">Stepper reverses back to rest position</td>
                </tr>
            </table>

            <p>Hold a gesture steady for a moment so it can be detected reliably.</p>
        </body>
    </html>
    """


@app.route("/video_feed")
def video_feed():
    return Response(
        generate_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )


# -----------------------------
# Main
# -----------------------------
if __name__ == "__main__":
    camera_thread = threading.Thread(target=camera_loop)
    camera_thread.daemon = True
    camera_thread.start()

    local_ip = get_local_ip()

    print("Open this on your laptop browser:")
    print(f"http://{local_ip}:5000")
    print("or")
    print("http://ucsdrobocar-148-07.local:5000")

    app.run(host="0.0.0.0", port=5000, debug=False)