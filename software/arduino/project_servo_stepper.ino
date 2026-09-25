#include <Servo.h>

// -------------------- Pin Definitions --------------------
const int SERVO_PIN = 5;

const int DIR_PIN = 2;
const int STEP_PIN = 3;

// Optional enable pin
const int ENABLE_PIN = 8;
const bool USE_ENABLE_PIN = false;

// -------------------- Servo --------------------
Servo myServo;

// For 270-degree servo
const int SERVO_MIN_US = 500;
const int SERVO_MAX_US = 2500;
const int SERVO_MAX_DEG = 270;

// -------------------- Stepper Settings --------------------
int stepDelayMicros = 1000;

// Change this until one full stepper rotation is correct
const int STEPS_PER_ROTATION = 300;

bool liftExtended = false;

void setup() {
  Serial.begin(9600);

  pinMode(DIR_PIN, OUTPUT);
  pinMode(STEP_PIN, OUTPUT);

  if (USE_ENABLE_PIN) {
    pinMode(ENABLE_PIN, OUTPUT);
    digitalWrite(ENABLE_PIN, LOW);
  }

  myServo.attach(SERVO_PIN);
  moveServoDegrees(0);

  Serial.println("Arduino ready.");
  Serial.println("Commands:");
  Serial.println("Command_1");
  Serial.println("Command_2");
  Serial.println("Command_3");
  Serial.println("Command_4");
  Serial.println("RETURN");
  Serial.println("TEST");

  delay(1000);
}

void loop() {
  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    command.trim();

    Serial.print("Received: ");
    Serial.println(command);

    if (command == "Command_1" && liftExtended == false) {
      moveServoDegrees(0);
      delay(800);
      moveStepper(true, STEPS_PER_ROTATION);
      liftExtended = true;
      Serial.println("Command_1 complete: servo 0, stepper extended");
    }

    else if (command == "Command_2" && liftExtended == false) {
      moveServoDegrees(90);
      delay(800);
      moveStepper(true, STEPS_PER_ROTATION);
      liftExtended = true;
      Serial.println("Command_2 complete: servo 90, stepper extended");
    }

    else if (command == "Command_3" && liftExtended == false) {
      moveServoDegrees(180);
      delay(800);
      moveStepper(true, STEPS_PER_ROTATION);
      liftExtended = true;
      Serial.println("Command_3 complete: servo 180, stepper extended");
    }

    else if (command == "Command_4" && liftExtended == false) {
      moveServoDegrees(270);
      delay(800);
      moveStepper(true, STEPS_PER_ROTATION);
      liftExtended = true;
      Serial.println("Command_4 complete: servo 270, stepper extended");
    }

    else if (command == "RETURN" && liftExtended == true) {
      moveStepper(false, STEPS_PER_ROTATION);
      liftExtended = false;
      Serial.println("Returned to rest");
    }

    else if (command == "TEST") {
      runMotorTest();
    }

    else {
      Serial.print("Ignored or unknown command: ");
      Serial.println(command);
    }
  }
}

void moveServoDegrees(int degrees) {
  degrees = constrain(degrees, 0, SERVO_MAX_DEG);

  int pulseWidth = map(degrees, 0, SERVO_MAX_DEG, SERVO_MIN_US, SERVO_MAX_US);

  myServo.writeMicroseconds(pulseWidth);
}

void moveStepper(bool clockwise, int steps) {
  digitalWrite(DIR_PIN, clockwise ? HIGH : LOW);
  delayMicroseconds(50);

  for (int i = 0; i < steps; i++) {
    digitalWrite(STEP_PIN, HIGH);
    delayMicroseconds(stepDelayMicros);

    digitalWrite(STEP_PIN, LOW);
    delayMicroseconds(stepDelayMicros);
  }
}

void runMotorTest() {
  Serial.println("Running motor test...");

  moveServoDegrees(0);
  delay(1000);

  moveServoDegrees(90);
  delay(1000);

  moveServoDegrees(180);
  delay(1000);

  moveServoDegrees(270);
  delay(1000);

  moveServoDegrees(0);
  delay(1000);

  moveStepper(true, STEPS_PER_ROTATION);
  delay(1000);

  moveStepper(false, STEPS_PER_ROTATION);
  delay(1000);

  Serial.println("Motor test complete.");
}