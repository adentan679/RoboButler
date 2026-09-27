// RoboButler integration firmware, protocol ROBOBUTLER1.
// Existing pins, pulse limits, pulse count and speed retained; NOT calibrated.
// STOW is a physical operator confirmation, not a position sensor.
#include <Servo.h>
#include <stdlib.h>
#include <string.h>

const int SERVO_PIN = 5, DIR_PIN = 2, STEP_PIN = 3;
const int ENABLE_PIN = 8;
const bool USE_ENABLE_PIN = false;
const int SERVO_MIN_US = 500, SERVO_MAX_US = 2500, SERVO_MAX_DEG = 270;
const int STEPS_PER_TRAVEL = 300;  // Pulse count, NOT verified revolutions/travel.
const unsigned long STEP_HALF_US = 1000;
const unsigned long LINK_TIMEOUT_MS = 2000;

Servo myServo;
enum Position { UNKNOWN, STOWED, EXTENDED, RETRACTED_UNVERIFIED };
enum Motion { IDLE, SERVO_WAIT, STEPPING };
Position position = UNKNOWN;
Motion motion = IDLE;
unsigned long activeId = 0, lastId = 0, servoStart = 0, lastEdge = 0;
unsigned long lastHost = 0;
bool linked = false, extending = false, stepHigh = false;
int completedPulses = 0;
char lineBuffer[64];
unsigned int lineLength = 0;
bool droppingLine = false;

void response(const char* kind, unsigned long id) {
  Serial.print(kind); Serial.print(' '); Serial.println(id);
}
void complete(const char* state) {
  Serial.print("DONE "); Serial.print(activeId); Serial.print(' '); Serial.println(state);
}
void halt(const char* reason) {
  motion = IDLE;
  position = UNKNOWN;
  stepHigh = false;
  digitalWrite(STEP_PIN, LOW);
  // Do not drop holding torque or detach servo automatically under a load.
  Serial.print("FAULT "); Serial.println(reason);
}
void beginSteps(bool forward) {
  extending = forward;
  digitalWrite(DIR_PIN, forward ? HIGH : LOW);
  digitalWrite(STEP_PIN, LOW);
  completedPulses = 0;
  stepHigh = false;
  lastEdge = micros();  // Full low interval also satisfies direction setup delay.
  motion = STEPPING;
}
void processLine(char* text) {
  if (!strcmp(text, "STOP")) { halt("STOPPED"); return; }
  if (!strcmp(text, "HELLO")) {
    linked = true; lastHost = millis();
    Serial.println("READY ROBOBUTLER1"); return;
  }
  if (!strcmp(text, "PING")) {
    if (linked) { lastHost = millis(); Serial.println("PONG"); }
    return;
  }
  if (!linked) { halt("NOT_LINKED"); return; }
  if (text[0] < '1' || text[0] > '9') { halt("BAD_ID"); return; }
  char* end;
  unsigned long id = strtoul(text, &end, 10);
  if (end == text || *end != ' ' || id == 0 || id <= lastId) {
    halt("BAD_ID"); return;
  }
  const char* command = end + 1;
  if (motion != IDLE) { halt("BUSY"); return; }
  bool selection = !strcmp(command, "Command_1") || !strcmp(command, "Command_2") ||
                   !strcmp(command, "Command_3") || !strcmp(command, "Command_4");
  if (!strcmp(command, "STOW")) {
    if (position == EXTENDED) { halt("NOT_RETRACTED"); return; }
    lastId = activeId = id;
    position = STOWED;
    response("ACK", id); complete("STOWED");
  } else if (selection && position == STOWED) {
    lastId = activeId = id;
    response("ACK", id);
    int degrees = (command[8] - '1') * 90;
    if (!myServo.attached()) myServo.attach(SERVO_PIN, SERVO_MIN_US, SERVO_MAX_US);
    myServo.writeMicroseconds(map(degrees, 0, SERVO_MAX_DEG, SERVO_MIN_US, SERVO_MAX_US));
    position = UNKNOWN;
    servoStart = millis();
    motion = SERVO_WAIT;
  } else if (!strcmp(command, "RETURN") && position == EXTENDED) {
    lastId = activeId = id;
    response("ACK", id);
    position = UNKNOWN;
    beginSteps(false);
  } else {
    halt("INVALID_STATE_OR_COMMAND");
  }
}
void setup() {
  Serial.begin(9600);
  pinMode(DIR_PIN, OUTPUT); pinMode(STEP_PIN, OUTPUT);
  digitalWrite(STEP_PIN, LOW);
  if (USE_ENABLE_PIN) { pinMode(ENABLE_PIN, OUTPUT); digitalWrite(ENABLE_PIN, LOW); }
  // No servo movement and no assumed lift home position at startup.
  Serial.println("BOOT ROBOBUTLER1");
}
void loop() {
  // Bounded serial work so motor timing is not starved by excessive input.
  for (int n = 0; n < 32 && Serial.available(); ++n) {
    char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      if (!droppingLine) { lineBuffer[lineLength] = '\0'; processLine(lineBuffer); }
      lineLength = 0; droppingLine = false;
    } else if (!droppingLine) {
      if (lineLength < sizeof(lineBuffer) - 1) lineBuffer[lineLength++] = c;
      else { droppingLine = true; halt("LINE_TOO_LONG"); }
    }
  }
  if (linked && (unsigned long)(millis() - lastHost) > LINK_TIMEOUT_MS) {
    linked = false; halt("LINK_TIMEOUT");
  }
  if (motion == SERVO_WAIT && (unsigned long)(millis() - servoStart) >= 800) {
    beginSteps(true);
  }
  if (motion == STEPPING && (unsigned long)(micros() - lastEdge) >= STEP_HALF_US) {
    lastEdge = micros();
    stepHigh = !stepHigh;
    digitalWrite(STEP_PIN, stepHigh ? HIGH : LOW);
    if (!stepHigh && ++completedPulses >= STEPS_PER_TRAVEL) {
      motion = IDLE;
      position = extending ? EXTENDED : RETRACTED_UNVERIFIED;
      complete(extending ? "EXTENDED" : "RETRACTED_UNVERIFIED");
    }
  }
}
