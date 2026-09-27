"""Original team landmark rules, with the four-finger label corrected.
Includes an upright thumbs-up resume gesture. No hardware initialization on import.
"""

from math import hypot

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
    # Resume: four fingers folded and thumb extended predominantly upward.
    # Scale margins to palm size; unlike the original thumb heuristic this also
    # recognizes a vertical thumb with little horizontal tip/IP separation.
    wrist = hand_landmarks.landmark[0]
    middle_mcp = hand_landmarks.landmark[9]
    thumb_mcp = hand_landmarks.landmark[2]
    palm_size = hypot(middle_mcp.x - wrist.x, middle_mcp.y - wrist.y)
    up = thumb_ip.y - thumb_tip.y
    if (index == middle == ring == pinky == 0 and palm_size > 1e-6
            and up > 0.15 * palm_size
            and up > abs(thumb_tip.x - thumb_ip.x)
            and thumb_mcp.y - thumb_tip.y > 0.35 * palm_size):
        return "THUMBS_UP"

    # Fist: no fingers extended
    if total == 0:
        return "FIST"

    # Point: index only
    if index == 1 and middle == 0 and ring == 0 and pinky == 0:
        return "POINT"

    # Peace: index and middle
    if index == 1 and middle == 1 and ring == 0 and pinky == 0:
        return "PEACE"

    # Four fingers: thumb, index, middle, ring extended and pinky folded
    # This retains the team's original four-finger selection rule.
    if thumb == 1 and index == 1 and middle == 1 and ring == 1 and pinky == 0:
        return "FOUR"

    # Open palm: most or all fingers extended
    if total >= 4:
        return "OPEN_PALM"

    return "UNKNOWN"
