/*
  PipelineGuard — ESP32 WROOM-32 Direct HTTP Ingestion
  ====================================================
  Connects ESP32 directly to the PipelineGuard website backend over Wi-Fi.
  Reads MQ Gas Sensor (e.g. MQ-2 / MQ-135) and sends real-time telemetry.
  
  When Gas Level > 300:
    - Triggers local alert (Built-in LED / Buzzer)
    - Sends data to backend: triggers WARNING/CRITICAL on the dashboard
    - Logs detailed warnings to the Serial Monitor

  PIN CONNECTIONS (ESP32 WROOM-32):
  -------------------------------------------------------------
  MQ Gas Sensor (MQ-2 / MQ-135):
    VCC   --> 5V (VIN / external 5V) [Heater needs 5V]
    GND   --> GND
    A0    --> GPIO 34 (Analog In, ADC1 - safe with Wi-Fi active)
  
  Optional Onboard / External Indicators:
    LED_PIN    --> GPIO 2 (Built-in Blue LED on most ESP32 boards)
    BUZZER_PIN --> GPIO 25 (Active buzzer to GND)
*/

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// ================= USER CONFIGURATION =================
// 1. Wi-Fi Credentials
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// 2. PipelineGuard Backend URL
// Replace with your computer's local IP address (e.g., http://192.168.1.15:8000/api/sensors)
// Run 'ipconfig' in Windows CMD/PowerShell to find your IPv4 Address.
const char* SERVER_URL    = "http://192.168.1.100:8000/api/sensors";

// 3. Hardware Device ID (Must match a device in the backend database: ESP32-01, ESP32-02, or ESP32-03)
const char* DEVICE_CODE   = "ESP32-01";

// 4. Pin Assignments
const int PIN_MQ_SENSOR   = 34;   // Analog input from MQ sensor (GPIO 34)
const int PIN_LED         = 2;    // Built-in LED on ESP32
const int PIN_BUZZER      = 25;   // Optional buzzer pin

// 5. Thresholds & Timing
const float GAS_THRESHOLD = 300.0;          // Threshold specified (> 300 triggers alert)
const unsigned long SEND_INTERVAL_MS = 2000; // Send reading every 2 seconds
// ======================================================

unsigned long lastSendTime = 0;

void connectWiFi() {
  Serial.println();
  Serial.print("Connecting to Wi-Fi: ");
  Serial.println(WIFI_SSID);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 30) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n[WiFi] Connected successfully!");
    Serial.print("[WiFi] ESP32 IP Address: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\n[WiFi] Connection Failed. Will retry in loop.");
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println("=================================================");
  Serial.println(" PipelineGuard — ESP32 WROOM-32 Gas Monitor ");
  Serial.println("=================================================");

  pinMode(PIN_LED, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  digitalWrite(PIN_LED, LOW);
  digitalWrite(PIN_BUZZER, LOW);

  // ADC resolution to 12-bit (0-4095)
  analogReadResolution(12);

  connectWiFi();
}

void sendReadingToWebsite(float gasValue, float airQualityValue, float pressureValue, bool flame) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[HTTP] Wi-Fi disconnected. Reconnecting...");
    connectWiFi();
    return;
  }

  HTTPClient http;
  http.begin(SERVER_URL);
  http.addHeader("Content-Type", "application/json");

  // Create JSON payload matching the backend's SensorIngest schema
  StaticJsonDocument<256> doc;
  doc["device_code"]    = DEVICE_CODE;
  doc["mq2"]            = gasValue;          // Gas level
  doc["mq135"]          = airQualityValue;   // Secondary air quality (or duplicate)
  doc["pressure"]       = pressureValue;     // Normal pipeline pressure (~1.0 bar)
  doc["flame_detected"] = flame;

  String jsonPayload;
  serializeJson(doc, jsonPayload);

  Serial.print("[HTTP POST] Sending payload: ");
  Serial.println(jsonPayload);

  int httpResponseCode = http.POST(jsonPayload);

  if (httpResponseCode > 0) {
    Serial.print("[HTTP] Server Response Code: ");
    Serial.println(httpResponseCode);
    String response = http.getString();
    Serial.print("[HTTP] Response: ");
    Serial.println(response);
  } else {
    Serial.print("[HTTP] Error sending POST: ");
    Serial.println(http.errorToString(httpResponseCode).c_str());
  }

  http.end();
}

void loop() {
  // Ensure Wi-Fi is connected
  if (WiFi.status() != WL_CONNECTED) {
    delay(1000);
    connectWiFi();
    return;
  }

  unsigned long currentMillis = millis();
  if (currentMillis - lastSendTime >= SEND_INTERVAL_MS) {
    lastSendTime = currentMillis;

    // 1. Read Analog Pin (0 - 4095 on ESP32)
    int rawValue = analogRead(PIN_MQ_SENSOR);

    // 2. Scale raw 12-bit ADC (0-4095) to calibrated index (0-1000)
    // You can adjust the formula based on your sensor calibration
    float gasLevel = (float)rawValue * (1000.0 / 4095.0);

    // Simulated secondary readings if only 1 physical sensor is attached
    float airQuality = gasLevel * 0.85; 
    float normalPressure = 1.02; // bar
    bool flameDetected = false;

    // 3. Print Data to Serial Monitor
    Serial.println("-------------------------------------------------");
    Serial.print("Raw ADC: ");
    Serial.print(rawValue);
    Serial.print(" | Gas Level: ");
    Serial.println(gasLevel);

    // 4. Threshold check: Greater than 300
    if (gasLevel > GAS_THRESHOLD) {
      Serial.println(">>> [ALERT] GAS LEVEL > 300 DETECTED! <<<");
      Serial.println(">>> Triggering Alarm & Alerting Dashboard! <<<");

      // Visual/Audible alert
      digitalWrite(PIN_LED, HIGH);
      digitalWrite(PIN_BUZZER, HIGH);
    } else {
      Serial.println("[STATUS] Gas level normal (< 300).");
      digitalWrite(PIN_LED, LOW);
      digitalWrite(PIN_BUZZER, LOW);
    }

    // 5. Send data to website backend
    sendReadingToWebsite(gasLevel, airQuality, normalPressure, flameDetected);
  }
}
