/*
  SmartNest v2 - Arduino UNO R4 WiFi
  8-channel relay (active LOW) on pins 2..9

  Relay map (index -> pin):
    0 -> D8  Fan            (manual only)
    1 -> D9  Bulb 1         (manual)
    2 -> D6  Bulb 2         (manual)
    3 -> D7  Bulb 3         (manual)
    4 -> D5  Bulb 4         (manual)
    5 -> D4  Smoke light    (Auto / Manual)
    6 -> D3  Temp light     (Auto / Manual)
    7 -> D2  Light-sensor bulb (Auto / Manual)

  Sensors:
    MQ-2 module  AO  -> A0
    DHT22        DATA-> D11
    BH1750       SDA -> SDA (A4), SCL -> SCL (A5)

  Humidity is display only (no bulb, no threshold).

  v3: works on the local network (HTTP) AND through the cloud (MQTT) so you can
      control it from any internet. Passwords are in the second tab arduino_secrets.h
*/

#include <WiFiS3.h>
#include <Wire.h>
#include <BH1750.h>
#include <DHT.h>
#include <ArduinoMqttClient.h>
#include "arduino_secrets.h"      // WiFi + MQTT passwords live in this second tab (never overwritten)

// ---------- WiFi (values come from arduino_secrets.h) ----------
const char WIFI_SSID[] = SECRET_SSID;
const char WIFI_PASS[] = SECRET_PASS;

// ---------- Cloud (MQTT) - leave SECRET_MQTT_USER empty to use the local network only ----------
const char MQTT_HOST[] = SECRET_MQTT_HOST;
const int  MQTT_PORT   = SECRET_MQTT_PORT;
const bool MQTT_ENABLED = (sizeof(SECRET_MQTT_USER) > 1);

// ---------- Pins ----------
const uint8_t RELAY_PIN[8] = {8, 9, 6, 7, 5, 4, 3, 2};   // index 0..7 -> pin
const uint8_t NUM_RELAYS = 8;
const uint8_t IDX_SMOKE = 5;   // change these 3 numbers to re-map sensor bulbs
const uint8_t IDX_TEMP  = 6;
const uint8_t IDX_LIGHT = 7;

#define MQ2_AO_PIN A0
#define DHT_PIN 11
#define DHT_TYPE DHT22

// ---------- Thresholds (editable from dashboard) ----------
float tLux = 100.0;     // light bulb ON when lux is BELOW this (dark)
float tTemp = 30.0;     // temp bulb ON when temp is ABOVE this (C)
int   tSmoke = 512;     // smoke bulb ON when reading is ABOVE this (0-1023)

const unsigned long MQ2_WARMUP_MS = 60000UL;

// ---------- State ----------
bool relayState[8] = {false, false, false, false, false, false, false, false};
bool autoMode[3] = {false, false, false};   // smoke, temp, light. Start MANUAL so every button works at once and everything is OFF; turn Auto on from the dashboard when you want it

float lux = 0, temp = 0, hum = 0;
int smoke = 0;
bool luxOk = false, dhtOk = false, mq2Ready = false, bhOk = false;

BH1750 lightMeter;
DHT dht(DHT_PIN, DHT_TYPE);
WiFiServer server(80);
WiFiSSLClient sslClient;
MqttClient mqtt(sslClient);

unsigned long tFast = 0, tDht = 0;
unsigned long statusSeq = 0;
bool statusDirty = true, mqttUp = false;
unsigned long tMqttTry = 0, lastPub = 0;
bool helloAsked = false;      // dashboard / agent just connected: answer quickly
// ---------- Relays ----------
void applyRelay(uint8_t i, bool on) {
  if (i >= NUM_RELAYS) return;
  relayState[i] = on;
  statusDirty = true;                     // tell the cloud
  digitalWrite(RELAY_PIN[i], on ? LOW : HIGH);   // active LOW
}

// ---------- Sensors ----------
void readSensors() {
  unsigned long now = millis();

  if (now - tFast >= 500) {
    tFast = now;
    static unsigned long tBhRetry = 0;
    if (!bhOk && now - tBhRetry >= 5000) { tBhRetry = now; bhOk = lightMeter.begin(); }
    float l = bhOk ? lightMeter.readLightLevel() : -1;
    if (l >= 0) { lux = l; luxOk = true; } else { luxOk = false; if (l == -2) bhOk = false; }
    if (!mq2Ready && now >= MQ2_WARMUP_MS) mq2Ready = true;   // latch once
    smoke = mq2Ready ? analogRead(MQ2_AO_PIN) : 0;
  }

  if (now - tDht >= 2500) {          // DHT22 needs >= 2 s between reads
    tDht = now;
    float t = dht.readTemperature();
    float h = dht.readHumidity();
    if (isnan(t) || isnan(h)) {
      dhtOk = false;
    } else {
      temp = t; hum = h; dhtOk = true;
    }
  }
}

// ---------- Auto logic (with hysteresis so relays do not chatter) ----------
void runAuto() {
  if (autoMode[0]) {
    bool cur = relayState[IDX_SMOKE], want = cur;
    if (!mq2Ready) want = false;
    else if (smoke > tSmoke) want = true;
    else if (smoke < tSmoke * 0.9) want = false;
    if (want != cur) applyRelay(IDX_SMOKE, want);
  }
  if (autoMode[1]) {
    bool cur = relayState[IDX_TEMP], want = cur;
    if (!dhtOk) want = false;
    else if (temp > tTemp) want = true;
    else if (temp < tTemp - 1.0) want = false;
    if (want != cur) applyRelay(IDX_TEMP, want);
  }
  if (autoMode[2]) {
    bool cur = relayState[IDX_LIGHT], want = cur;
    if (!luxOk) want = false;
    else if (lux < tLux) want = true;                 // dark -> ON
    else if (lux > tLux * 1.1 + 5) want = false;      // bright -> OFF
    if (want != cur) applyRelay(IDX_LIGHT, want);
  }
}

// ---------- HTTP helpers ----------
String getParam(const String &req, const char *key) {
  String k = String(key) + "=";
  int p = req.indexOf("?" + k);
  if (p < 0) p = req.indexOf("&" + k);
  if (p < 0) return "";
  p += k.length() + 1;
  int e = p;
  while (e < (int)req.length() && req[e] != '&' && req[e] != ' ') e++;
  return req.substring(p, e);
}

void sendJson(WiFiClient &c, int code, const String &body) {
  c.print("HTTP/1.1 ");
  c.print(code);
  c.println(code == 200 ? " OK" : " Error");
  c.println("Content-Type: application/json");
  c.println("Access-Control-Allow-Origin: *");
  c.println("Connection: close");
  c.print("Content-Length: ");
  c.println(body.length());
  c.println();
  c.print(body);
}

String statusJson() {
  String s = "{";
  s += "\"lux\":" + String(luxOk ? lux : 0, 1);
  s += ",\"luxOk\":" + String(luxOk ? "true" : "false");
  s += ",\"smoke\":" + String(smoke);
  s += ",\"mq2Ready\":" + String(mq2Ready ? "true" : "false");
  s += ",\"temp\":" + String(dhtOk ? temp : 0, 1);
  s += ",\"hum\":" + String(dhtOk ? hum : 0, 1);
  s += ",\"dhtOk\":" + String(dhtOk ? "true" : "false");
  s += ",\"tLux\":" + String(tLux, 0);
  s += ",\"tTemp\":" + String(tTemp, 1);
  s += ",\"tSmoke\":" + String(tSmoke);
  s += ",\"relays\":[";
  for (uint8_t i = 0; i < NUM_RELAYS; i++) { s += relayState[i] ? "1" : "0"; if (i < NUM_RELAYS - 1) s += ","; }
  s += "],\"auto\":[";
  for (uint8_t i = 0; i < 3; i++) { s += autoMode[i] ? "1" : "0"; if (i < 2) s += ","; }
  s += "],\"seq\":" + String(statusSeq);
  s += "}";
  return s;
}

void handleClient() {
  WiFiClient client = server.available();
  if (!client) return;

  String req = "";
  unsigned long start = millis();
  bool gotLine = false;
  while (client.connected() && millis() - start < 1000) {
    if (client.available()) {
      char c = client.read();
      if (!gotLine) {
        if (c == '\n') gotLine = true; else req += c;
      }
      if (c == '\n' && gotLine) {
        // read and drop rest of headers
        String line = "";
        unsigned long t2 = millis();
        while (client.connected() && millis() - t2 < 300) {
          if (client.available()) {
            char d = client.read();
            if (d == '\n') { if (line.length() <= 1) break; line = ""; }
            else line += d;
          }
        }
        break;
      }
    }
  }

  if (req.startsWith("GET /status")) {
    sendJson(client, 200, statusJson());

  } else if (req.startsWith("GET /relay")) {
    int id = getParam(req, "id").toInt();
    String st = getParam(req, "state");
    if (st == "" || id < 0 || id >= NUM_RELAYS) {
      sendJson(client, 400, "{\"error\":\"bad id or state\"}");
    } else if (id >= IDX_SMOKE && autoMode[id - IDX_SMOKE]) {
      sendJson(client, 409, "{\"error\":\"bulb is in auto mode\"}");
    } else {
      applyRelay(id, st.toInt() == 1);
      sendJson(client, 200, statusJson());
    }

  } else if (req.startsWith("GET /mode")) {
    int id = getParam(req, "id").toInt();       // 5, 6 or 7
    String a = getParam(req, "auto");
    if (a == "" || id < IDX_SMOKE || id > IDX_LIGHT) {
      sendJson(client, 400, "{\"error\":\"bad id or auto\"}");
    } else {
      autoMode[id - IDX_SMOKE] = (a.toInt() == 1);
      sendJson(client, 200, statusJson());
    }

  } else if (req.startsWith("GET /threshold")) {
    String v;
    v = getParam(req, "lux");   if (v != "") { float f = v.toFloat(); if (isfinite(f)) tLux = f; }
    v = getParam(req, "temp");  if (v != "") { float f = v.toFloat(); if (isfinite(f)) tTemp = f; }
    v = getParam(req, "smoke"); if (v != "") tSmoke = constrain((int)v.toInt(), 0, 1023);
    sendJson(client, 200, statusJson());

  } else {
    sendJson(client, 404, "{\"error\":\"not found\"}");
  }

  delay(1);
  client.stop();
}

// ---------- WiFi ----------
bool hasIp() {
  return WiFi.status() == WL_CONNECTED && WiFi.localIP() != IPAddress(0, 0, 0, 0);
}

bool waitForIp(unsigned long ms) {
  unsigned long t0 = millis();
  while (millis() - t0 < ms) {
    if (hasIp()) return true;
    delay(500);
    Serial.print(".");
  }
  return false;
}

// Call WiFi.begin() only ONCE per connect, then wait for the phone to give an IP.
void connectWifi() {
  if (WiFi.status() == WL_NO_MODULE) {
    Serial.println("WiFi module not found!");
    return;
  }
  Serial.print("WiFi module firmware: ");
  Serial.println(WiFi.firmwareVersion());

  WiFi.disconnect();          // clean start
  delay(1000);
  WiFi.setTimeout(20000);     // begin() waits up to 20 s

  Serial.print("Joining '");
  Serial.print(WIFI_SSID);
  Serial.println("' ...");
  int st = WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("begin() status: ");
  Serial.println(st);         // 3 = joined, 4 = failed (check name/password/2.4 GHz)

  if (waitForIp(20000)) {     // phone hotspot can be slow to give an IP
    Serial.println();
    Serial.print("Connected. Open the dashboard and enter this IP: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println();
    Serial.print("No IP yet. Status: ");
    Serial.println(WiFi.status());
  }
}


// ---------- Cloud (MQTT) ----------
// Messages are small JSON texts.
//   Arduino -> cloud (status feed):  the same JSON as /status
//   cloud -> Arduino (command feed): {"c":"relay","id":3,"s":1}  {"c":"mode","id":5,"a":0}
//                                    {"c":"limits","smoke":600,"temp":32,"lux":120}  {"c":"hello"}
long jInt(const String &s, const char *key, long def) {
  int p = s.indexOf(String("\"") + key + "\"");
  if (p < 0) return def;
  p = s.indexOf(':', p);
  if (p < 0) return def;
  return s.substring(p + 1).toInt();
}

float jFloat(const String &s, const char *key, float def) {
  int p = s.indexOf(String("\"") + key + "\"");
  if (p < 0) return def;
  p = s.indexOf(':', p);
  if (p < 0) return def;
  return s.substring(p + 1).toFloat();
}

String jStr(const String &s, const char *key) {
  int p = s.indexOf(String("\"") + key + "\"");
  if (p < 0) return "";
  p = s.indexOf(':', p);
  if (p < 0) return "";
  int a = s.indexOf('"', p);
  if (a < 0) return "";
  int b = s.indexOf('"', a + 1);
  if (b < 0) return "";
  return s.substring(a + 1, b);
}

void handleCommand(const String &m) {
  String c = jStr(m, "c");
  if (c == "relay") {
    int id = (int)jInt(m, "id", -1);
    int st = (int)jInt(m, "s", 0);
    if (id >= 0 && id < NUM_RELAYS && !(id >= IDX_SMOKE && autoMode[id - IDX_SMOKE])) applyRelay(id, st == 1);
  } else if (c == "all") {                       // {"c":"all","s":1}: fan + bulbs 1-4 + (manual) sensor bulbs all ON or OFF in ONE message
    bool on = (jInt(m, "s", 0) == 1);
    for (uint8_t i = 0; i < NUM_RELAYS; i++) {
      if (i >= IDX_SMOKE && autoMode[i - IDX_SMOKE]) continue;
      applyRelay(i, on);
    }
  } else if (c == "hello") {
    helloAsked = true;
  } else if (c == "mode") {
    int id = (int)jInt(m, "id", -1);
    if (id >= IDX_SMOKE && id <= IDX_LIGHT) autoMode[id - IDX_SMOKE] = (jInt(m, "a", 1) == 1);
  } else if (c == "limits") {
    if (m.indexOf("\"smoke\"") >= 0) tSmoke = constrain((int)jInt(m, "smoke", tSmoke), 0, 1023);
    if (m.indexOf("\"temp\"") >= 0) { float f = jFloat(m, "temp", tTemp); if (isfinite(f)) tTemp = f; }
    if (m.indexOf("\"lux\"") >= 0) { float f = jFloat(m, "lux", tLux); if (isfinite(f)) tLux = f; }
  }
  statusDirty = true;                    // "hello" and every command -> send fresh status
}

void onMqttMessage(int size) {
  String m;
  while (mqtt.available()) {
    char ch = (char)mqtt.read();
    if (m.length() < 300) m += ch;
  }
  Serial.print("MQTT command: ");
  Serial.println(m);
  handleCommand(m);
}

void publishStatus() {
  statusSeq++;
  String j = statusJson();
  if (mqtt.beginMessage(SECRET_MQTT_TOPIC_STATUS, (unsigned long)j.length(), false, 0)) {
    mqtt.print(j);
    mqtt.endMessage();
  }
  statusDirty = false;
  lastPub = millis();
}

void mqttConnect() {
  Serial.print("MQTT connecting... ");
  mqtt.setId("home-uno-r4");
  mqtt.setUsernamePassword(SECRET_MQTT_USER, SECRET_MQTT_KEY);
  mqtt.setKeepAliveInterval(45 * 1000UL);
  if (!mqtt.connect(MQTT_HOST, MQTT_PORT)) {
    Serial.print("failed, error ");
    Serial.println(mqtt.connectError());
    return;
  }
  mqtt.onMessage(onMqttMessage);
  mqtt.subscribe(SECRET_MQTT_TOPIC_CMD);
  mqttUp = true;
  statusDirty = true;
  Serial.println("connected");
}

// Publishes at most once every 5 s (free cloud plans limit messages per minute).
void mqttLoop() {
  if (!MQTT_ENABLED) return;
  unsigned long now = millis();
  if (mqtt.connected()) {
    mqtt.poll();
  } else {
    if (mqttUp) { mqttUp = false; Serial.println("MQTT disconnected"); }
    if (hasIp() && now - tMqttTry >= 20000UL) { tMqttTry = now; mqttConnect(); }
    return;
  }

  // alarms: send quickly when smoke / temperature cross their limits
  static bool lastSmokeHigh = false, lastTempHigh = false;
  bool sh = mq2Ready && smoke > tSmoke;
  bool th = dhtOk && temp > tTemp;
  if (sh != lastSmokeHigh || th != lastTempHigh) { lastSmokeHigh = sh; lastTempHigh = th; statusDirty = true; }

  // normal: at most once per 5 s. A fresh "hello" (someone just opened the dashboard) is answered after 1.5 s.
  unsigned long minGap = helloAsked ? 1500UL : 5000UL;
  if (now - lastPub >= minGap && (statusDirty || now - lastPub >= 20000UL)) { publishStatus(); helloAsked = false; }
}

// ---------- Setup / loop ----------
void setup() {
  Serial.begin(115200);
  delay(1500);
  Serial.println("=== SmartNest v3.0 ===");

  // Relays OFF first (HIGH) so nothing flickers at boot
  for (uint8_t i = 0; i < NUM_RELAYS; i++) {
    digitalWrite(RELAY_PIN[i], HIGH);
    pinMode(RELAY_PIN[i], OUTPUT);
  }

  analogReadResolution(10);          // 0-1023, same scale as the dashboard
  Wire.begin();
  bhOk = lightMeter.begin();
  if (!bhOk) Serial.println("BH1750 not found (check wiring)");
  dht.begin();

  connectWifi();
  server.begin();
}

void loop() {
  unsigned long now = millis();

  // Check WiFi every 5 s; reconnect only if it stays down for 30 s
  static unsigned long tCheck = 0, downSince = 0, tIp = 0;
  if (now - tCheck >= 5000) {
    tCheck = now;
    if (hasIp()) {
      downSince = 0;
    } else if (downSince == 0) {
      downSince = now;
    } else if (now - downSince >= 30000) {
      Serial.println("WiFi down 30 s, reconnecting...");
      connectWifi();
      downSince = 0;
    }
  }

  // Print the IP every 10 s so you can read it any time
  if (now - tIp >= 10000) {
    tIp = now;
    Serial.print("IP: ");
    Serial.println(WiFi.localIP());
  }

  readSensors();
  runAuto();
  handleClient();
  mqttLoop();
  delay(1);                          // short loop = fast button response
}
