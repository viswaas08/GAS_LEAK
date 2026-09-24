/*
  PipelineGuard — ESP32 Wi-Fi Gateway
  ===================================
  Microcontroller: ESP32 WROOM-32
  Role:
    - Receives sensor & servo telemetry from Arduino Uno over Serial2 (GPIO 16 RX2, GPIO 17 TX2).
    - Connects to local Wi-Fi router.
    - Sends HTTP POST requests with JSON payload to the PipelineGuard website backend.

  WIRING CONNECTIONS (ESP32 WROOM-32 <--> ARDUINO UNO):
  ------------------------------------------------------
  1. Serial Communication:
     - ESP32 GPIO 16 (RX2) <-- Arduino Pin 11 (TX) [Recommended: 1k/2k ohm divider to step 5V down to 3.3V]
     - ESP32 GPIO 17 (TX2) --> Arduino Pin 10 (RX)
     - ESP32 GND           <--> Arduino GND        [MANDATORY COMMON GROUND!]

  2. Power:
     - ESP32 Micro-USB / 5V VIN power.
*/

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// ---------- 1. WI-FI CONFIGURATION ----------
const char* WIFI_SSID     = "Giganet";
const char* WIFI_PASSWORD = "22222222";

// ---------- 2. WEBSITE BACKEND URL ----------
// Use your deployed Vercel URL (e.g. "https://gas-leak-production.vercel.app/api/sensors")
// Or your local PC IP (e.g. "http://192.168.1.100:8000/api/sensors")
const char* SERVER_URL    = "https://gasleak-git-main-viswaas08s-projects.vercel.app/";

// ---------- 3. HARDWARE IDENTIFIER ----------
const char* DEVICE_CODE   = "ESP32-01"; // Identifies this pipeline zone on the website

// Serial2 pins on ESP32 (Hardware UART 2)
#define RX2_PIN 16
#define TX2_PIN 17

void connectWiFi() {
  Serial.print("[WiFi] Connecting to: ");
  Serial.println(WIFI_SSID);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 25) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n[WiFi] Connected successfully!");
    Serial.print("[WiFi] ESP32 IP: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\n[WiFi] Connection failed. Will retry automatically.");
  }
}

void setup() {
  // USB Serial Monitor for ESP32
  Serial.begin(115200);
  delay(1000);

  // Hardware UART 2 for listening to Arduino Uno (9600 baud)
  Serial2.begin(9600, SERIAL_8N1, RX2_PIN, TX2_PIN);

  Serial.println("==================================================");
  Serial.println(" PipelineGuard: ESP32 Wi-Fi Gateway Started       ");
  Serial.println(" Listening to Arduino on GPIO 16 (RX2) at 9600 baud");
  Serial.println("==================================================");

  connectWiFi();
}

void sendTelemetryToWebsite(float gasLevel, bool flameDetected, bool valveClosed) {
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
    return;
  }

  HTTPClient http;
  http.begin(SERVER_URL);
  http.addHeader("Content-Type", "application/json");

  // Construct JSON payload conforming to SensorIngest schema
  StaticJsonDocument<256> doc;
  doc["device_code"]    = DEVICE_CODE;
  doc["mq2"]            = gasLevel;
  doc["mq135"]          = gasLevel * 0.8;      // Estimated air quality index
  doc["pressure"]       = valveClosed ? 0.2 : 1.0; // Drops to ~0.2 bar when valve is shut
  doc["flame_detected"] = flameDetected;

  String jsonPayload;
  serializeJson(doc, jsonPayload);

  Serial.print("[HTTP POST] Sending: ");
  Serial.println(jsonPayload);

  int httpCode = http.POST(jsonPayload);

  if (httpCode > 0) {
    Serial.printf("[HTTP] Success! Server Response Code: %d\n", httpCode);
  } else {
    Serial.printf("[HTTP] POST Failed. Error: %s\n", http.errorToString(httpCode).c_str());
  }

  http.end();
}

void loop() {
  // Ensure Wi-Fi stays connected
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
  }

  // Check if Arduino sent a telemetry packet over Serial2
  if (Serial2.available() > 0) {
    String incomingLine = Serial2.readStringUntil('\n');
    incomingLine.trim();

    if (incomingLine.length() > 0) {
      Serial.print("[UART] Received from Arduino: ");
      Serial.println(incomingLine);

      // Parse comma-separated line: "GAS,FLAME,VALVE_CLOSED" (e.g. "345.2,1,1")
      int commaIndex1 = incomingLine.indexOf(',');
      int commaIndex2 = incomingLine.indexOf(',', commaIndex1 + 1);

      if (commaIndex1 != -1 && commaIndex2 != -1) {
        float gasLevel      = incomingLine.substring(0, commaIndex1).toFloat();
        bool  flameDetected = (incomingLine.substring(commaIndex1 + 1, commaIndex2).toInt() == 1);
        bool  valveClosed   = (incomingLine.substring(commaIndex2 + 1).toInt() == 1);

        Serial.printf("[PARSED] Gas: %.1f | Flame: %s | Valve: %s\n",
                      gasLevel,
                      flameDetected ? "DETECTED" : "CLEAR",
                      valveClosed ? "SHUT (180°)" : "OPEN (0°)");

        // Transmit reading to the website backend
        sendTelemetryToWebsite(gasLevel, flameDetected, valveClosed);
      }
    }
  }
}
