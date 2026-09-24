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
const int PIN_MQ2     = A0;  // MQ-2 Analog Input
const int PIN_FLAME   = 13;   // Flame Sensor Digital Input (LOW = Flame Detected)
const int PIN_SERVO   = 9;   // Servo Signal Pin
const int PIN_BUZZER  = 8;   // Optional Buzzer / Indicator LED
const int PIN_SW_RX   = 10;  // SoftwareSerial RX (from ESP32 TX)
const int PIN_SW_TX   = 11;  // SoftwareSerial TX (to ESP32 RX)

// ---------- THRESHOLDS ----------
const float GAS_THRESHOLD = 300.0; // Gas level above 300 indicates leakage

// ---------- SERVO POSITIONS ----------
const int VALVE_OPEN_ANGLE   = 0;    // Normal operating condition
const int VALVE_CLOSED_ANGLE = 180;  // Emergency shutoff rotation

Servo valveServo;
SoftwareSerial espSerial(PIN_SW_RX, PIN_SW_TX); // RX, TX

bool isValveClosed = false;
unsigned long lastTelemetryTime = 0;
const unsigned long TELEMETRY_INTERVAL = 2000; // Send telemetry every 2 seconds

void setup() {
  // Hardware Serial for USB Serial Monitor debugging
  Serial.begin(9600);
  
  // Software Serial to communicate with ESP32
  espSerial.begin(9600);

  // Pin Configurations
  pinMode(PIN_FLAME, INPUT_PULLUP);
  pinMode(PIN_BUZZER, OUTPUT);
  digitalWrite(PIN_BUZZER, LOW);

  // Initialize Servo
  valveServo.attach(PIN_SERVO);
  valveServo.write(VALVE_OPEN_ANGLE); // Start in OPEN position
  isValveClosed = false;

  Serial.println(F("=================================================="));
  Serial.println(F(" PipelineGuard: Arduino Gas & Flame Controller   "));
  Serial.println(F(" Valve Servo: 0 deg (OPEN) -> 180 deg (CLOSED)   "));
  Serial.println(F("=================================================="));
  delay(1500); // Allow sensor heater to stabilize
}

void loop() {
  // 1. Read MQ-2 Sensor (0 - 1023 on Arduino ADC)
  int rawGas = analogRead(PIN_MQ2);
  // Scale 0-1023 to 0-1000 index
  float gasLevel = (float)rawGas * (1000.0 / 1023.0);

  // 2. Read Flame Sensor (Typical modules output LOW when flame detected)
  bool flameDetected = (digitalRead(PIN_FLAME) == LOW);

  // 3. Logic: Check for Gas Leakage (> 300) OR Flame Event
  bool hazardDetected = (gasLevel > GAS_THRESHOLD) || flameDetected;

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
    // Normal operation: keep valve open
    digitalWrite(PIN_BUZZER, LOW);
    if (isValveClosed) {
      Serial.println(F("[STATUS] Environment safe. Resetting valve to 0° (OPEN)."));
      valveServo.write(VALVE_OPEN_ANGLE);
      isValveClosed = false;
    }
  }

  // 4. Send Periodic Telemetry to ESP32
  if (millis() - lastTelemetryTime >= TELEMETRY_INTERVAL) {
    lastTelemetryTime = millis();

    // Print to PC Serial Monitor
    Serial.print(F("Gas Level: "));
    Serial.print(gasLevel, 1);
    Serial.print(F(" | Flame: "));
    Serial.print(flameDetected ? F("YES") : F("NO"));
    Serial.print(F(" | Valve Angle: "));
    Serial.println(isValveClosed ? 180 : 0);

    // Send formatted line to ESP32 over SoftwareSerial
    // Format: GAS,FLAME,VALVE_CLOSED (e.g. "320.5,1,1\n")
    espSerial.print(gasLevel, 1);
    espSerial.print(F(","));
    espSerial.print(flameDetected ? 1 : 0);
    espSerial.print(F(","));
    espSerial.println(isValveClosed ? 1 : 0);
  }

  delay(100);
}
