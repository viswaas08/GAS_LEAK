/*
  PipelineGuard — Arduino Uno Direct USB Bridge (No ESP32 Required!)
  ===================================================================
  Microcontroller: Arduino Uno / Nano
  Communication: Directly via USB cable connected to your PC (e.g. COM3)
  Companion script: Run 'python arduino_bridge.py' on your computer.

  HOW IT WORKS:
  1. Arduino reads MQ-2 Gas sensor (A0) and Flame sensor (Pin 2).
  2. If Gas > 300 OR Flame is sensed, Arduino rotates the Servo to 180° (SHUTOFF).
  3. Arduino streams telemetry JSON over USB to your computer.
  4. The Python bridge forwards this telemetry to your website dashboard.
  5. If an operator clicks "Emergency shutoff" on the website, the Python bridge
     sends "SHUTOFF" over USB, and Arduino rotates the servo to 180°!

  WIRING CONNECTIONS (ARDUINO UNO):
  ---------------------------------
  1. MQ-2 Gas Sensor:
     - VCC  --> 5V
     - GND  --> GND
     - A0   --> Analog Pin A0

  2. Flame Sensor:
     - VCC  --> 5V
     - GND  --> GND
     - D0   --> Digital Pin 2 (Outputs LOW when flame is detected)

  3. Servo Motor (SG90 / MG995):
     - VCC (Red)    --> 5V (or external 5V)
     - GND (Brown)  --> GND
     - Signal (Orange/Yellow) --> Digital Pin 9

  4. Alarm Buzzer / LED (Optional):
     - Positive (+) --> Digital Pin 8
     - Negative (-) --> GND
*/

#include <Servo.h>

const int PIN_MQ2    = A0;
const int PIN_FLAME  = 2;
const int PIN_SERVO  = 9;
const int PIN_BUZZER = 8;

const float GAS_THRESHOLD = 300.0;
const int VALVE_OPEN_ANGLE   = 0;
const int VALVE_CLOSED_ANGLE = 180;

Servo valveServo;
bool isValveClosed = false;
unsigned long lastSend = 0;

void setup() {
  // 9600 baud rate matching python bridge
  Serial.begin(9600);

  pinMode(PIN_FLAME, INPUT_PULLUP);
  pinMode(PIN_BUZZER, OUTPUT);
  digitalWrite(PIN_BUZZER, LOW);

  valveServo.attach(PIN_SERVO);
  valveServo.write(VALVE_OPEN_ANGLE);
  isValveClosed = false;
}

void loop() {
  // 1. Read MQ-2 Sensor (0-1023 -> 0-1000 index)
  int rawGas = analogRead(PIN_MQ2);
  float gasLevel = (float)rawGas * (1000.0 / 1023.0);

  // 2. Read Flame Sensor (Active LOW)
  bool flameDetected = (digitalRead(PIN_FLAME) == LOW);

  // 3. Local Safety Logic: Gas > 300 or Flame
  bool localHazard = (gasLevel > GAS_THRESHOLD) || flameDetected;

  if (localHazard) {
    digitalWrite(PIN_BUZZER, HIGH);
    if (!isValveClosed) {
      valveServo.write(VALVE_CLOSED_ANGLE);
      isValveClosed = true;
    }
  } else if (!isValveClosed) {
    digitalWrite(PIN_BUZZER, LOW);
  }

  // 4. Check for Remote Control Commands from Website via USB
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd == "SHUTOFF") {
      valveServo.write(VALVE_CLOSED_ANGLE);
      isValveClosed = true;
      digitalWrite(PIN_BUZZER, HIGH);
    } else if (cmd == "OPEN") {
      valveServo.write(VALVE_OPEN_ANGLE);
      isValveClosed = false;
      digitalWrite(PIN_BUZZER, LOW);
    }
  }

  // 5. Stream Structured Telemetry JSON to PC every 1.5 seconds
  if (millis() - lastSend >= 1500) {
    lastSend = millis();

    // Print single-line JSON format for python bridge to parse cleanly
    Serial.print("{\"mq2\":");
    Serial.print(gasLevel, 1);
    Serial.print(",\"flame\":");
    Serial.print(flameDetected ? "true" : "false");
    Serial.print(",\"valve_closed\":");
    Serial.print(isValveClosed ? "true" : "false");
    Serial.println("}");
  }

  delay(50);
}
