/*
  PipelineGuard — Arduino Controller (MQ-2, Flame Sensor & 180° Valve Servo)
  ==========================================================================
  Microcontroller: Arduino Uno / Nano
  Role: 
    - Reads MQ-2 Gas Sensor on Analog Pin A0.
    - Reads Flame Sensor on Digital Pin 2 (Active LOW).
    - Controls Servo Motor on Pin 9:
        * 0 degrees   = Valve OPEN  (Normal operation)
        * 180 degrees = Valve CLOSED (Gas > 300 OR Flame detected)
    - Sends structured telemetry to ESP32 over SoftwareSerial (Pins 10 RX, 11 TX).

  WIRING CONNECTIONS (ARDUINO UNO):
  ---------------------------------
  1. MQ-2 Gas Sensor:
     - VCC  --> 5V
     - GND  --> GND
     - A0   --> Analog A0
     - D0   --> Not connected

  2. Flame Sensor Module:
     - VCC  --> 5V
     - GND  --> GND
     - DO   --> Digital Pin 2 (Outputs LOW when flame is detected)

  3. Servo Motor (SG90 / MG995 / MG996R):
     - VCC (Red)    --> 5V (or external 5V power supply)
     - GND (Brown)  --> GND (must share common GND with Arduino)
     - Signal (Orange/Yellow) --> Digital Pin 9

  4. Serial Connection to ESP32:
     - Arduino Pin 11 (TX) --> ESP32 GPIO 16 (RX2) [Use 1k/2k resistor voltage divider for 3.3V safety]
     - Arduino Pin 10 (RX) --> ESP32 GPIO 17 (TX2)
     - Arduino GND         --> ESP32 GND (MANDATORY common ground!)
*/

#include <Servo.h>
#include <SoftwareSerial.h>

// ---------- PIN DEFINITIONS ----------
const int PIN_MQ2           = A0;  // MQ-2 Analog Input
const int PIN_FLAME         = 13;  // Flame Sensor Digital Input (LOW = Flame Detected)
const int PIN_SERVO         = 9;   // Servo Signal Pin
const int PIN_BUZZER        = 8;   // Optional Buzzer / Indicator LED
const int PIN_MANUAL_SWITCH = 4;   // Manual Push Button / Switch (Pin 4 to GND)
const int PIN_SW_RX         = 10;  // SoftwareSerial RX (from ESP32 TX)
const int PIN_SW_TX         = 11;  // SoftwareSerial TX (to ESP32 RX)

// ---------- THRESHOLDS ----------
const float GAS_THRESHOLD = 300.0; // Gas level above 300 indicates leakage

// ---------- SERVO POSITIONS ----------
const int VALVE_OPEN_ANGLE   = 0;    // Normal operating condition
const int VALVE_CLOSED_ANGLE = 180;  // Emergency shutoff rotation

Servo valveServo;
SoftwareSerial espSerial(PIN_SW_RX, PIN_SW_TX); // RX, TX

bool isValveClosed = false;
bool manualShutoffHold = false;
unsigned long lastTelemetryTime = 0;
const unsigned long TELEMETRY_INTERVAL = 2000; // Send telemetry every 2 seconds

// Manual switch debounce state
int lastSwitchReading = HIGH;
int switchStableState = HIGH;
unsigned long lastSwitchDebounceTime = 0;
const unsigned long DEBOUNCE_DELAY_MS = 50;

void setup() {
  // Hardware Serial for USB Serial Monitor debugging
  Serial.begin(9600);
  
  // Software Serial to communicate with ESP32
  espSerial.begin(9600);

  // Pin Configurations
  pinMode(PIN_FLAME, INPUT_PULLUP);
  pinMode(PIN_BUZZER, OUTPUT);
  digitalWrite(PIN_BUZZER, LOW);

  // Manual switch pin with internal pullup
  pinMode(PIN_MANUAL_SWITCH, INPUT_PULLUP);

  // Initialize Servo
  valveServo.attach(PIN_SERVO);
  valveServo.write(VALVE_OPEN_ANGLE); // Start in OPEN position
  isValveClosed = false;
  manualShutoffHold = false;

  Serial.println(F("=================================================="));
  Serial.println(F(" PipelineGuard: Arduino Gas & Flame Controller   "));
  Serial.println(F(" Valve Servo: 0 deg (OPEN) -> 180 deg (CLOSED)   "));
  Serial.println(F(" Manual Switch: Pin 4 to GND (Active LOW)        "));
  Serial.println(F("=================================================="));
  delay(1500); // Allow sensor heater to stabilize
}

void loop() {
  // 1. Read Manual Switch with Debouncing
  int switchReading = digitalRead(PIN_MANUAL_SWITCH);
  if (switchReading != lastSwitchReading) {
    lastSwitchDebounceTime = millis();
  }

  if ((millis() - lastSwitchDebounceTime) > DEBOUNCE_DELAY_MS) {
    if (switchReading != switchStableState) {
      switchStableState = switchReading;
      if (switchStableState == LOW) {
        if (isValveClosed) {
          manualShutoffHold = false;
          valveServo.write(VALVE_OPEN_ANGLE);
          isValveClosed = false;
          digitalWrite(PIN_BUZZER, LOW);
          Serial.println(F("[MANUAL SWITCH] Toggled -> Valve 0° (OPEN)"));
        } else {
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

  // 2. Read MQ-2 Sensor (0 - 1023 on Arduino ADC)
  int rawGas = analogRead(PIN_MQ2);
  // Scale 0-1023 to 0-1000 index
  float gasLevel = (float)rawGas * (1000.0 / 1023.0);

  // 3. Read Flame Sensor (Typical modules output LOW when flame detected)
  bool flameDetected = (digitalRead(PIN_FLAME) == LOW);

  // 4. Logic: Check for Gas Leakage (> 300) OR Flame Event (with 3s boot warmup filter)
  bool hazardDetected = (millis() > 3000) && ((gasLevel > GAS_THRESHOLD) || flameDetected);

  if (hazardDetected) {
    // Turn ON Alarm Indicator
    digitalWrite(PIN_BUZZER, HIGH);

    // Rotate Servo 180 degrees to shut off the gas valve
    if (!isValveClosed) {
      Serial.println(F(">>> HAZARD DETECTED! ROTATING SERVO TO 180° TO SHUT OFF VALVE! <<<"));
      valveServo.write(VALVE_CLOSED_ANGLE);
      isValveClosed = true;
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

  // 5. Remote Commands from Hardware Serial or ESP32 SoftwareSerial
  auto handleCmd = [](String cmd) {
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
  };

  if (Serial.available() > 0) {
    handleCmd(Serial.readStringUntil('\n'));
  }
  if (espSerial.available() > 0) {
    handleCmd(espSerial.readStringUntil('\n'));
  }

  // 6. Send Periodic Telemetry to ESP32 and Serial Monitor
  if (millis() - lastTelemetryTime >= TELEMETRY_INTERVAL) {
    lastTelemetryTime = millis();

    // Print to PC Serial Monitor
    Serial.print(F("Gas Level: "));
    Serial.print(gasLevel, 1);
    Serial.print(F(" | Flame: "));
    Serial.print(flameDetected ? F("YES") : F("NO"));
    Serial.print(F(" | Manual Switch: "));
    Serial.print(switchReading == LOW ? F("ON") : F("OFF"));
    Serial.print(F(" | Valve Angle: "));
    Serial.println(isValveClosed ? 180 : 0);

    // Send formatted line to ESP32 over SoftwareSerial
    // Format: GAS,FLAME,VALVE_CLOSED,MANUAL_SWITCH (e.g. "320.5,1,1,0\n")
    espSerial.print(gasLevel, 1);
    espSerial.print(F(","));
    espSerial.print(flameDetected ? 1 : 0);
    espSerial.print(F(","));
    espSerial.print(isValveClosed ? 1 : 0);
    espSerial.print(F(","));
    espSerial.println(switchReading == LOW ? 1 : 0);
  }

  delay(50);
}
