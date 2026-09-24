/*
  PipelineGuard — ESP32 firmware (reference implementation)
  ===========================================================
  This is REFERENCE CODE for a prototype/academic demo. It is written for
  the Arduino framework on ESP32 and is NOT compiled or run by this backend
  — the backend's /simulator/esp32_simulator.py exercises the same API
  surface in software so the full system can be demoed without hardware.

  SAFETY SCOPE (read before wiring anything):
  - This firmware assumes MQ-2 / MQ-135 hobby gas sensors, a hobby pressure
    sensor, a flame sensor, and a SAFE, NON-HAZARDOUS demonstration
    actuator (e.g. a relay driving an LED, a small servo on a model valve,
    or a relay switching a low-voltage indicator circuit).
  - Do NOT wire this to a live gas installation. Hobby MQ-series sensors
    and non-certified actuators are not rated for that and doing so is
    dangerous. Real pipeline shutoff requires certified industrial safety
    equipment (SIL-rated instrumentation, certified solenoid valves,
    intrinsically safe wiring) installed by qualified professionals.

  DATA FLOW (production):
    ESP32 --[MQTT/TLS]--> broker --[MQTT subscriber service]--> POST /api/sensors
    ESP32 <--[MQTT/TLS]-- broker <--[backend publishes command]-- POST /api/actuator/shutoff
    ESP32 --[MQTT/TLS]--> broker --[subscriber]--> POST /api/actuator/ack

  Topics (suggested):
    pipeline/<device_code>/sensors      (ESP32 publishes, retained=false, QoS 1)
    pipeline/<device_code>/actuator/cmd (ESP32 subscribes)
    pipeline/<device_code>/actuator/ack (ESP32 publishes)
    pipeline/<device_code>/heartbeat    (ESP32 publishes every 5-10s)
*/

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// ---- Fill in for your network / broker ----
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* MQTT_HOST     = "your-mqtt-broker.example.com";
const int   MQTT_PORT     = 8883;             // TLS
const char* DEVICE_CODE   = "ESP32-01";        // must match a Device in the backend

// ---- Pins (adjust to your wiring) ----
const int PIN_MQ2       = 34;   // analog
const int PIN_MQ135     = 35;   // analog
const int PIN_PRESSURE  = 32;   // analog (or use an I2C pressure sensor)
const int PIN_FLAME     = 27;   // digital, LOW = flame detected (typical modules)
const int PIN_ACTUATOR  = 26;   // relay/servo/LED — SAFE demo actuator only

WiFiClientSecure netClient;
PubSubClient mqtt(netClient);

unsigned long lastSensorPublish = 0;
const unsigned long SENSOR_INTERVAL_MS = 2000;
bool actuatorClosed = false;

void connectWiFi() {
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) { delay(400); }
}

void mqttCallback(char* topic, byte* payload, unsigned int length) {
  String msg; for (unsigned int i = 0; i < length; i++) msg += (char)payload[i];
  StaticJsonDocument<256> doc;
  if (deserializeJson(doc, msg)) return;

  String t(topic);
  if (t.endsWith("/actuator/cmd")) {
    String commandId = doc["command_id"].as<String>();
    // --- Drive the SAFE demo actuator ---
    digitalWrite(PIN_ACTUATOR, HIGH);   // e.g. energize relay / move servo to CLOSED
    delay(1500);                        // simulate actuator travel time
    actuatorClosed = true;

    StaticJsonDocument<128> ack;
    ack["device_code"] = DEVICE_CODE;
    ack["command_id"] = commandId;
    ack["result"] = "closed";           // or "failed" if the actuator reports a fault
    char buf[128];
    size_t n = serializeJson(ack, buf);
    String ackTopic = String("pipeline/") + DEVICE_CODE + "/actuator/ack";
    mqtt.publish(ackTopic.c_str(), buf, n);
  }
}

void connectMQTT() {
  netClient.setInsecure(); // DEV ONLY — use setCACert() with your broker's CA in production
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setCallback(mqttCallback);
  while (!mqtt.connected()) {
    if (mqtt.connect(DEVICE_CODE)) {
      String cmdTopic = String("pipeline/") + DEVICE_CODE + "/actuator/cmd";
      mqtt.subscribe(cmdTopic.c_str());
    } else {
      delay(1000);
    }
  }
}

void setup() {
  pinMode(PIN_FLAME, INPUT);
  pinMode(PIN_ACTUATOR, OUTPUT);
  digitalWrite(PIN_ACTUATOR, LOW); // valve open / relay off at boot
  connectWiFi();
  connectMQTT();
}

void publishSensors() {
  float mq2Raw      = analogRead(PIN_MQ2);       // 0-4095 on ESP32 ADC
  float mq135Raw     = analogRead(PIN_MQ135);
  float pressureRaw  = analogRead(PIN_PRESSURE);
  bool  flame        = digitalRead(PIN_FLAME) == LOW;

  // Calibrate these mappings against your specific sensor modules.
  float mq2      = mq2Raw * (1000.0 / 4095.0);
  float mq135    = mq135Raw * (1000.0 / 4095.0);
  float pressure = 0.5 + (pressureRaw / 4095.0) * 1.5; // fake linear map -> ~0.5-2.0 bar

  StaticJsonDocument<256> doc;
  doc["device_code"] = DEVICE_CODE;
  doc["mq2"] = mq2;
  doc["mq135"] = mq135;
  doc["pressure"] = pressure;
  doc["flame_detected"] = flame;
  char buf[256];
  size_t n = serializeJson(doc, buf);

  String topic = String("pipeline/") + DEVICE_CODE + "/sensors";
  mqtt.publish(topic.c_str(), buf, n);
}

void loop() {
  if (!mqtt.connected()) connectMQTT();
  mqtt.loop();

  if (millis() - lastSensorPublish > SENSOR_INTERVAL_MS) {
    publishSensors();
    lastSensorPublish = millis();
  }
}
