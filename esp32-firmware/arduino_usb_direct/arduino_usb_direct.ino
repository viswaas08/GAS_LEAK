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

// ================= PIN CONFIGURATION =================
const int PIN_MQ2           = A0; // MQ-2 Analog Out (A0)
const int PIN_FLAME         = 2;  // Flame Sensor Digital Out (D0) -> Digital Pin 2
const int PIN_SERVO         = 9;  // Servo Motor Signal (Orange/Yellow) -> Digital Pin 9
const int PIN_BUZZER        = 8;  // Buzzer / Alert LED (+) -> Digital Pin 8
const int PIN_MANUAL_SWITCH = 4;  // Manual Push Button / Switch (Pin 4 to GND with internal pullup)

// ================= SENSOR CALIBRATION =================
// Baseline clean-air ADC reading for MQ-2 (typically 80-130 in clean ambient air)
const int CLEAN_AIR_BASELINE = 90; 

// Threshold for Hazardous Gas Leak (PPM equivalent above baseline)
const float GAS_THRESHOLD = 100.0;

const int VALVE_OPEN_ANGLE   = 0;
const int VALVE_CLOSED_ANGLE = 180;

Servo valveServo;
bool isValveClosed = false;
bool manualShutoffHold = false;
unsigned long lastSend = 0;

// Manual switch state & debounce
int lastSwitchReading = HIGH;
int switchStableState = HIGH;
unsigned long lastSwitchDebounceTime = 0;
const unsigned long DEBOUNCE_DELAY_MS = 50;

void setup() {
  // 9600 baud rate matching python bridge
  Serial.begin(9600);

  // Digital Pin 2 with internal pull-up (most flame modules pull LOW on flame detection)
  pinMode(PIN_FLAME, INPUT_PULLUP);
  pinMode(PIN_BUZZER, OUTPUT);
  digitalWrite(PIN_BUZZER, LOW);

  // Manual hardware switch pin (active LOW when button pressed / switch to GND)
  pinMode(PIN_MANUAL_SWITCH, INPUT_PULLUP);

  valveServo.attach(PIN_SERVO);
  valveServo.write(VALVE_OPEN_ANGLE);
  isValveClosed = false;
  manualShutoffHold = false;
}

void loop() {
  // 1. Read Manual Switch with Debouncing (Pin 4 to GND)
  int switchReading = digitalRead(PIN_MANUAL_SWITCH);
  if (switchReading != lastSwitchReading) {
    lastSwitchDebounceTime = millis();
  }

  if ((millis() - lastSwitchDebounceTime) > DEBOUNCE_DELAY_MS) {
    if (switchReading != switchStableState) {
      switchStableState = switchReading;
      // Trigger toggle when switch transition to active (LOW = pressed/on)
      if (switchStableState == LOW) {
        if (isValveClosed) {
          // Manual Switch turned ON -> Open valve (0°)
          manualShutoffHold = false;
          valveServo.write(VALVE_OPEN_ANGLE);
          isValveClosed = false;
          digitalWrite(PIN_BUZZER, LOW);
          Serial.println(F("[MANUAL SWITCH] Toggled -> Valve 0° (OPEN)"));
        } else {
          // Manual Switch turned OFF -> Shut off valve (180°)
          manualShutoffHold = true;
          valveServo.write(VALVE_CLOSED_ANGLE);
          isValveClosed = true;
          digitalWrite(PIN_BUZZER, HIGH);
          Serial.println(F("[MANUAL SWITCH] Toggled -> Valve 180° (CLOSED)"));
        }
      }
    }
  }
  lastSwitchReading = switchReading;

  // 2. Read MQ-2 Sensor with 8x Oversampling for stable, noise-free readings
  long adcSum = 0;
  for (int i = 0; i < 8; i++) {
    adcSum += analogRead(PIN_MQ2);
    delayMicroseconds(200);
  }
  float rawGas = (float)adcSum / 8.0;

  // Calibrate gas reading: map clean-air baseline (90 ADC) to 0, and high gas (900 ADC) to 1000 PPM
  float gasLevel = 0.0;
  if (rawGas > CLEAN_AIR_BASELINE) {
    gasLevel = (rawGas - CLEAN_AIR_BASELINE) * (1000.0 / (1023.0 - CLEAN_AIR_BASELINE));
  } else {
    // Slight ambient trace in clean air (0 - 15 PPM)
    gasLevel = (rawGas / (float)CLEAN_AIR_BASELINE) * 12.0;
  }

  // 3. Read Flame Sensor (D0 on Pin 2)
  // Standard IR flame sensor modules output LOW when flame IR is sensed (Active LOW)
  int flamePinState = digitalRead(PIN_FLAME);
  bool flameDetected = (flamePinState == LOW);

  // 4. Local Safety Logic: Gas > 300 PPM or Flame detected -> 180° Emergency Shutoff
  // Warmup guard: Ignore readings during first 3 seconds of boot to avoid startup sensor spikes
  bool localHazard = (millis() > 3000) && ((gasLevel >= GAS_THRESHOLD) || flameDetected);

  if (localHazard) {
    digitalWrite(PIN_BUZZER, HIGH);
    if (!isValveClosed) {
      valveServo.write(VALVE_CLOSED_ANGLE);
      isValveClosed = true;
      Serial.println(F("[HAZARD DETECTED] Gas/Flame hazard! Valve rotated to 180° (CLOSED)"));
    }
  } else {
    // SAFE MODE: Turn off buzzer and keep / restore valve to 0° (OPEN)
    digitalWrite(PIN_BUZZER, LOW);
    if (isValveClosed && !manualShutoffHold) {
      valveServo.write(VALVE_OPEN_ANGLE);
      isValveClosed = false;
      Serial.println(F("[SAFE MODE] Environment safe. Restoring valve to 0° (OPEN)."));
    }
  }

  // 5. Remote / Bridge Control Commands via USB Serial from Website Operator
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd == "SHUTOFF" || cmd == "OFF" || cmd == "CLOSE") {
      manualShutoffHold = true;
      valveServo.write(VALVE_CLOSED_ANGLE);
      isValveClosed = true;
      digitalWrite(PIN_BUZZER, HIGH);
    } else if (cmd == "OPEN" || cmd == "ON") {
      manualShutoffHold = false;
      valveServo.write(VALVE_OPEN_ANGLE);
      isValveClosed = false;
      digitalWrite(PIN_BUZZER, LOW);
    } else if (cmd == "TOGGLE") {
      isValveClosed = !isValveClosed;
      manualShutoffHold = isValveClosed;
      valveServo.write(isValveClosed ? VALVE_CLOSED_ANGLE : VALVE_OPEN_ANGLE);
      digitalWrite(PIN_BUZZER, isValveClosed ? HIGH : LOW);
    }
  }

  // 6. Stream Structured Telemetry JSON to PC every 0.1 seconds (100ms = 10Hz)
  if (millis() - lastSend >= 100) {
    lastSend = millis();

    Serial.print("{\"mq2\":");
    Serial.print(gasLevel, 1);
    Serial.print(",\"raw_gas\":");
    Serial.print((int)rawGas);
    Serial.print(",\"flame\":");
    Serial.print(flameDetected ? "true" : "false");
    Serial.print(",\"flame_pin\":");
    Serial.print(flamePinState);
    Serial.print(",\"valve_closed\":");
    Serial.print(isValveClosed ? "true" : "false");
    Serial.print(",\"manual_switch\":");
    Serial.print(switchReading == LOW ? "true" : "false");
    Serial.println("}");
  }

  delay(10);
}
