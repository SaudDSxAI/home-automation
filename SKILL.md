---
name: smart-home-arduino-whatsapp
description: Step-by-step build guide for an Arduino UNO R4 WiFi smart home (8 relays, MQ-2 smoke, DHT22 temperature, BH1750 light) with a phone dashboard on Cloudflare, Adafruit IO cloud control, and a WhatsApp agent (text + voice + alerts). Give this whole file to any AI assistant and ask it to guide you step by step.
---

# HOW TO USE THIS FILE (instructions for the AI assistant)

You are guiding a person who wants to build this project from zero. Rules for you:
1. Go ONE step at a time. Give a step, wait until the person says it is done, then give the next. Use simple, short English.
2. Ask the person for their own values (WiFi name, passwords, keys). NEVER invent secrets and never ask them to paste secrets into a public place. Every secret is a placeholder like `<YOUR_WIFI_PASSWORD>`.
3. Use the exact code. It is in the repository folders (see "Repository layout" below) and the same code is copied in section 12, so this file also works on its own. Do not rewrite it unless something fails.
4. If something fails, use section 11 (known problems) first.
5. Verify each stage before moving on (serial monitor shows values, relays click, dashboard answers, etc.).
6. Mains electricity can kill. Before the AC wiring step, make sure the person understands the safety note in section 2. If they are unsure, tell them to test with low-voltage lamps or ask a qualified electrician.

Repository layout (github.com/SaudDSxAI/home-automation):

    SKILL.md                         this guide
    README.md                        short overview
    wiring_diagram.png               the full wiring diagram
    arduino/smartnest_v2/            main firmware: smartnest_v2.ino + arduino_secrets.h (placeholders)
    arduino/happy_birthday_lights/   optional fun test sketch
    dashboard/                       the web page (index.html, style.css, app.js, sw.js, manifest, icons)
    whatsapp_agent/                  home_agent.py, requirements.txt, .env.example, README.md

Get it with `git clone https://github.com/SaudDSxAI/home-automation.git` (or "Code > Download ZIP" on GitHub).

# 1. What you will build

A home controller:
- Arduino UNO R4 WiFi reads 3 sensors and switches 8 relays (1 fan + 4 bulbs + 3 "sensor lights").
- Sensor lights can work Auto (smoke light, temperature light, dark light) or Manual.
- A phone/laptop dashboard (a web page you host free on Cloudflare) controls everything from anywhere.
- A WhatsApp agent (Python) lets you type or send a voice note ("turn off bulb 1 and 2"), and sends alerts for smoke and high temperature.
- Works on local WiFi (HTTP) and over the internet (cloud MQTT through Adafruit IO).

How the parts talk:

    Phone dashboard  <--MQTT over WebSocket-->  Adafruit IO  <--MQTT (TLS 8883)-->  Arduino
    WhatsApp (you)  <-->  Python agent on a computer  <--MQTT-->  Adafruit IO  <-->  Arduino
    (local mode: dashboard / agent talk to the Arduino directly by HTTP on the same WiFi)

# 2. Parts list

| Part | Notes |
|---|---|
| Arduino UNO R4 WiFi | WiFi is 2.4 GHz only |
| 8-channel relay module, 5V, active LOW (SRD-05VDC relays) | |
| MQ-2 gas/smoke sensor module (AO pin used) | needs ~60 s warm-up after power on |
| DHT22 (AM2302) temperature + humidity | a bare 4-pin sensor needs a 10k pull-up between VCC and DATA; a 3-pin module already has it |
| BH1750 light sensor (I2C) | on 3.3V in our build |
| 4 bulbs + holders, 1 fan, mains cable/plug, wires | |
| Computer with Arduino IDE, Node.js, Python 3 | |

SAFETY: the relay side carries mains AC (110-240 V). It can kill. Only connect the AC side if you know how, keep it insulated and in a box, unplug before touching, and test first with low-voltage lamps.

# 3. Wiring

Relay map (index -> Arduino pin -> load). The relay inputs IN1..IN8 are wired in this exact order:

| Relay | Arduino pin | Load | Mode |
|---|---|---|---|
| IN1 (index 0) | D8 | Fan | manual |
| IN2 (index 1) | D9 | Bulb 1 | manual |
| IN3 (index 2) | D6 | Bulb 2 | manual |
| IN4 (index 3) | D7 | Bulb 3 | manual |
| IN5 (index 4) | D5 | Bulb 4 | manual |
| IN6 (index 5) | D4 | Smoke light | Auto/Manual |
| IN7 (index 6) | D3 | Temperature light | Auto/Manual |
| IN8 (index 7) | D2 | Dark (light-sensor) light | Auto/Manual |

Low voltage:
- Relay module VCC -> Arduino 5V, relay GND -> Arduino GND.
- MQ-2: VCC -> 5V, GND -> GND, AO -> A0 (DO unused).
- DHT22: VCC -> 5V, GND -> GND, DATA -> D11.
- BH1750: VCC -> 3.3V, GND -> GND, SDA -> A4 (SDA), SCL -> A5 (SCL). ADDR unused.

AC side (mains), same for every channel:
- AC plug has 3 pins but only 2 are used: Live (L) and Neutral (N). Earth (E) is not used here.
- Live (L) goes to the COM terminal of every relay (chain them together).
- Each relay's NO terminal goes to the live terminal of its bulb/fan. (NC is not used.)
- Neutral (N) goes DIRECTLY to the second terminal of every bulb and the fan (one neutral bus).
- Relays are active LOW: the pin LOW = relay ON = load ON. The sketch sets all pins HIGH (OFF) first at boot.

The diagram image for this wiring is `wiring_diagram.png` in the repository.

# 4. Install the Arduino software

1. Install Arduino IDE 2.x. Board manager: install "Arduino UNO R4 Boards". Select board "Arduino UNO R4 WiFi".
2. Library manager, install: `BH1750` (by Christopher Laws), `DHT sensor library` (Adafruit, also accept "Adafruit Unified Sensor"), `ArduinoMqttClient`. (`WiFiS3` and `Wire` come with the board.)
3. Open `arduino/smartnest_v2/smartnest_v2.ino` from the repository. The IDE also opens `arduino_secrets.h` as a second tab. (Without the repository: make a folder `smartnest_v2`, put `smartnest_v2.ino` from section 12.1 in it and add a second tab `arduino_secrets.h` from section 12.2. The folder name must match the .ino name.)

# 5. Cloud: Adafruit IO (free)

1. Create a free account at io.adafruit.com. Note your username and your AIO Key (Profile > "My Key"). Keep the key secret; if it ever leaks, press "Regenerate" and update all places.
2. Create two feeds with these exact keys: `home-status` (Arduino sends data here) and `home-cmd` (dashboard/agent send commands here).
3. Free plan limit: 30 data points per minute. The firmware sends at most once per 5 s; the dashboard limits to 18 commands/min and the agent to 14/min. Do not increase these (accounts get throttled/banned).
4. MQTT: host `io.adafruit.com`, port 8883 (TLS) for Arduino and Python, WebSocket `wss://io.adafruit.com:443` for the browser. Topics: `<YOUR_AIO_USERNAME>/feeds/home-status` and `<YOUR_AIO_USERNAME>/feeds/home-cmd`. Reading `<topic>/get` returns the last value (the dashboard uses it to show state fast).

Message format (small JSON):
- Status (Arduino -> cloud): `{"lux":..,"luxOk":true,"smoke":..,"mq2Ready":true,"temp":..,"hum":..,"dhtOk":true,"tLux":100,"tTemp":30.0,"tSmoke":512,"relays":[0,0,0,0,0,0,0,0],"auto":[0,0,0],"seq":N}`
- Commands (to Arduino): `{"c":"relay","id":1,"s":1}`, `{"c":"all","s":0}`, `{"c":"mode","id":5,"a":1}`, `{"c":"limits","smoke":600,"temp":32,"lux":120}`, `{"c":"hello"}` (ask for fresh status).

# 6. Upload the firmware

1. Fill `arduino_secrets.h` with your 2.4 GHz WiFi name/password (a phone hotspot works), your Adafruit username/key and the two topics (replace every `<...>` placeholder, keep the quotes). For local network only, set `SECRET_MQTT_USER` to "". Never upload your filled file anywhere.
2. Upload. Open Serial Monitor at 115200. You should see "SmartNest v3.0", "Connected" with an IP, and "MQTT connected".
3. Check: all relays OFF at boot; the MQ-2 reads 0 for the first 60 s (warm-up); `http://<arduino-ip>/status` in a browser returns JSON.
4. Test a relay by hand: `http://<arduino-ip>/relay?id=1&state=1` (bulb 1 on), `state=0` (off).

Behaviour to know: all three sensor lights start in MANUAL (nothing auto at boot). Auto logic has hysteresis so the relay does not chatter: smoke bulb ON above the limit (default 512 of 1023), OFF below 90% of it; temperature bulb ON above 30 C, OFF below 29 C; dark bulb ON below 100 lux, OFF above 1.1x+5 lux.

# 7. The dashboard (web page)

Files: the `dashboard/` folder of the repository (`index.html`, `style.css`, `app.js`, `sw.js`, `manifest.webmanifest`, `icon-192.png`, `icon-512.png`). The same code is in sections 12.3 to 12.7 (without the repository, any simple 192 and 512 px square PNG icons work, background #121315). It is a single screen, no scrolling, works on phone and landscape, bulbs glow when on, All ON/OFF buttons, limits popup, starts with everything OFF and "Syncing" until the Arduino answers.
- It needs internet only for the MQTT library from jsDelivr (`mqtt@5.10.1`) and Google Fonts.
- It stores your cloud login only in the browser (localStorage). The first time you open the page, enter Adafruit username + key in the settings. You can also open `https://<your-site>/#cloud=<AIO_USERNAME>:<AIO_KEY>` once on the phone (this puts the key in your own phone only; do not share this link). Then "Add to Home Screen".

# 8. Host the dashboard free on Cloudflare Pages

1. Make a free Cloudflare account. Install Node.js.
2. Open a terminal in the `dashboard/` folder and run:
   `npx wrangler login` (browser opens, approve), then
   `npx wrangler pages deploy . --project-name home-control`
   (first time it asks to create the project; choose the production branch `main`).
3. You get a link like `https://home-control-xxx.pages.dev`. Open it on the phone.
4. If deploy fails with an npm `_npx` / ENOTEMPTY error: run `rm -rf ~/.npm/_npx` and deploy again.

# 9. WhatsApp agent (text, voice, alerts)

What it does: a Python script (standard library + `paho-mqtt`) that reads your WhatsApp messages, uses an OpenAI model to understand any sentence (English / Hindi / Roman Hindi), runs relay/mode/limit commands, transcribes voice notes with Whisper ("I heard: ..."), and sends alerts (smoke high, temperature high, Arduino offline/back online, sensor not working; repeated every 10 minutes while the problem lasts, then a "back to normal" message). Only the paired chat can use it. A plain word parser works as fallback if OpenAI is unreachable.

Setup:
1. Create your own WhatsApp agent and get its API key. This is a built-in feature of the normal WhatsApp app, no Meta developer account and no third-party provider needed:
   1. Open WhatsApp on your phone and go to Settings.
   2. Scroll down a little until you see the option called **Agents** and tap it.
   3. Tap **Add agent**, give your agent a name (for example "Home") and confirm. The agent is added.
   4. A chat with your new agent opens. From the agent you get its **API key**. Copy it. This is your `WHATSAPP_TOKEN`. Keep it secret like a password; never post it or put it in a video. (Menu names can change a little between WhatsApp versions; if a name differs, look for the Agents option in Settings.)
   5. The script already uses the agent API address (`https://api.whatsapp.com/agent/v1`, the default of `API_BASE`), so you only paste your key into `.env`. Your own number goes into `WHATSAPP_ALLOWED_NUMBER` so only you can control the home.
   AI assistant: walk the person through these taps one at a time and wait for "done". If the agent API behaves differently from the code (for example different message fields), read the error the script prints and adjust only the small `WhatsApp` class in section 12.8.
2. OpenAI: create an API key at platform.openai.com (small cost per message; model default `gpt-4o-mini`, voice uses `whisper-1`).
3. In the `whatsapp_agent/` folder copy `.env.example` to `.env` and fill it (your own values, never share this file). Put each value right after the `=`, with no spaces and no comment on the same line:

       WHATSAPP_TOKEN=<YOUR_AGENT_API_KEY>
       WHATSAPP_ALLOWED_NUMBER=<YOUR_NUMBER_WITH_COUNTRY_CODE_DIGITS_ONLY>
       WHATSAPP_PAIR_CODE=<ANY_SECRET_WORD_YOU_CHOOSE>
       OPENAI_API_KEY=<YOUR_OPENAI_KEY>
       MQTT_USER=<YOUR_AIO_USERNAME>
       MQTT_KEY=<YOUR_AIO_KEY>
       ARDUINO_IP=<ARDUINO_LOCAL_IP>

   `ARDUINO_IP` is only used in local mode (when `MQTT_USER` is empty). The `.gitignore` already keeps `.env` out of git.

4. Install and run (macOS/Linux need a virtual environment because of PEP 668):

       cd whatsapp_agent
       python3 -m venv venv
       ./venv/bin/pip install -r requirements.txt
       ./venv/bin/python home_agent.py

   On Windows: `py -m venv venv`, then `venv\Scripts\pip install -r requirements.txt`, then `venv\Scripts\python home_agent.py`.

   Keep it running (it must stay on to answer). Only one program may read the WhatsApp token at a time.
5. First message from your phone (from the number in `WHATSAPP_ALLOWED_NUMBER`): `status`. If the agent answers "This assistant is private", send `PAIR <your pair code>` once. Then try `help`.

Example commands: `status`, `turn off light 1 and light 2`, `fan on`, `all off`, `auto smoke`, `set temp 35`, `alerts off`, or a voice note.

# 10. Final test checklist

1. Serial monitor: values for lux, temp, humidity; smoke after 60 s warm-up.
2. Dashboard on phone (also on mobile data): every button works on the FIRST press; the lights glow.
3. Hold a lighter flame near the DHT22 (careful, do not melt it): temperature goes over the limit, the temperature light turns on (Auto), and WhatsApp sends a warning at the same time.
4. Smoke near the MQ-2 (a lighter's unlit gas or a safe smoke source): reading goes over the limit, smoke light ON, WhatsApp warning.
5. Cover the BH1750: lux drops below the limit, dark light ON (Auto).
6. WhatsApp: `bulb 1 on`, voice note "switch off everything".
Optional fun test: upload `arduino/happy_birthday_lights/happy_birthday_lights.ino` (also in section 12.10). It plays Happy Birthday on the lights (fan forced off). Re-upload smartnest_v2 afterwards.

# 11. Known problems and fixes

- First button press is lost / buttons work only after refresh: caused by sensor lights defaulting to Auto and the page ignoring clicks before the first status. Fixed in this version (manual at boot, "Syncing" state, `hello` + `/get` fast status). Make sure the board runs this firmware and the page is the latest one.
- WiFi not joining: the Arduino UNO R4 only supports 2.4 GHz. Check name/password; phone hotspots can be slow to give an IP (the sketch waits 20 s).
- Cloud MQTT fails (error codes in serial): check username/key/topics, port 8883, that the feeds exist.
- Messages blocked / rate limits: never go above the limits in section 5.
- `pip install` says externally-managed-environment: use the venv commands in section 9.
- Cloudflare deploy ENOTEMPTY: `rm -rf ~/.npm/_npx`.
- MQ-2 shows 0 for a minute: normal warm-up.
- DHT22 returns NaN: check DATA on D11 and the 10k pull-up (bare sensor).
- Relays click inverted (on at boot): module is active LOW; the code sets HIGH before pinMode to avoid flicker. Some modules need a separate JD-VCC jumper/supply.

# 12. The exact code

This is the same code as in the repository folders. Replace only the placeholders.


## 12.1 arduino/smartnest_v2/smartnest_v2.ino

```cpp
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
```


## 12.2 arduino/smartnest_v2/arduino_secrets.h (placeholders)

```cpp
// arduino_secrets.h  - second tab next to smartnest_v2.ino. Fill in YOUR values. Never share this file.
// ---- WiFi (2.4 GHz only; a phone hotspot works) ----
#define SECRET_SSID "<YOUR_WIFI_NAME>"
#define SECRET_PASS "<YOUR_WIFI_PASSWORD>"

// ---- Cloud (Adafruit IO MQTT). Leave SECRET_MQTT_USER as "" to use the local network only ----
#define SECRET_MQTT_HOST "io.adafruit.com"
#define SECRET_MQTT_PORT 8883
#define SECRET_MQTT_USER "<YOUR_AIO_USERNAME>"
#define SECRET_MQTT_KEY  "<YOUR_AIO_KEY>"
#define SECRET_MQTT_TOPIC_STATUS "<YOUR_AIO_USERNAME>/feeds/home-status"
#define SECRET_MQTT_TOPIC_CMD    "<YOUR_AIO_USERNAME>/feeds/home-cmd"
```


## 12.3 dashboard/index.html

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0b1220">
<title>Home Control</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=IBM+Plex+Mono:wght@500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="style.css">
<link rel="manifest" href="manifest.webmanifest">
<link rel="icon" href="icon-192.png">
<link rel="apple-touch-icon" href="icon-192.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Home">
</head>
<body>
<main class="app">
  <header class="top">
    <div class="brand"><h1>Home Control</h1><p id="clock">&nbsp;</p></div>
    <div class="top-r">
      <span class="pill" id="conn"><i data-i="wifi-off"></i><b>Connecting</b></span>
      <button class="icon-btn" id="limBtn" aria-label="Limits"><i data-i="sliders-horizontal"></i></button>
      <button class="icon-btn" id="ipBtn" aria-label="Connection"><i data-i="settings-2"></i></button>
    </div>
  </header>

  <div>
    <div class="alert hidden" id="smokeAlert"><i data-i="triangle-alert"></i><span>Smoke level is above the limit</span></div>
    <div class="sensors" id="sensors"></div>
  </div>

  <section class="devs" id="devs"></section>

  <div class="actions">
    <button class="allon" id="allOn">All ON</button>
    <button class="alloff" id="allOff">All OFF</button>
  </div>
</main>

<div class="modal hidden" id="limModal">
  <div class="sheet">
    <h3>Limits for the sensor lights</h3>
    <div class="lim"><label><span>Smoke light on above</span><b id="lSmoke"></b></label><input type="range" id="sSmoke" min="5" max="100" step="1"></div>
    <div class="lim"><label><span>Temperature light on above</span><b id="lTemp"></b></label><input type="range" id="sTemp" min="15" max="60" step="0.5"></div>
    <div class="lim"><label><span>Dark light on below</span><b id="lLux"></b></label><input type="range" id="sLux" min="5" max="1000" step="5"></div>
    <div class="row"><button class="ghost" id="limClose">Close</button><button class="primary" id="apply">Apply limits</button></div>
  </div>
</div>

<div class="modal hidden" id="modal">
  <div class="sheet">
    <h3>Connection</h3>
    <div class="seg2">
      <label><input type="radio" name="mode" id="mCloud"><span>Cloud (anywhere)</span></label>
      <label><input type="radio" name="mode" id="mLocal"><span>Local WiFi</span></label>
    </div>
    <div id="cloudBox">
      <p>Adafruit IO details. They stay only on this device.</p>
      <input id="cUser" placeholder="Adafruit IO username" autocomplete="off" autocapitalize="off" spellcheck="false">
      <input id="cKey" type="password" placeholder="Adafruit IO key" autocomplete="off" autocapitalize="off" spellcheck="false">
      <details><summary>Advanced</summary>
        <input id="cWs" placeholder="WebSocket address" autocomplete="off" autocapitalize="off" spellcheck="false">
      </details>
    </div>
    <div id="localBox" class="hidden">
      <p>Arduino IP from the Serial Monitor. Works only on the same WiFi.</p>
      <input id="ipInput" inputmode="decimal" placeholder="192.168.1.50" autocomplete="off">
    </div>
    <div class="row">
      <button class="ghost" id="ipCancel">Cancel</button>
      <button class="primary" id="ipSave">Connect</button>
    </div>
  </div>
</div>

<script>window.ICONS={"lightbulb":"<path d=\"M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5\" /> <path d=\"M9 18h6\" /> <path d=\"M10 22h4\" />","fan":"<path d=\"M10.827 16.379a6.082 6.082 0 0 1-8.618-7.002l5.412 1.45a6.082 6.082 0 0 1 7.002-8.618l-1.45 5.412a6.082 6.082 0 0 1 8.618 7.002l-5.412-1.45a6.082 6.082 0 0 1-7.002 8.618l1.45-5.412Z\" /> <path d=\"M12 12v.01\" />","flame":"<path d=\"M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z\" />","thermometer":"<path d=\"M14 4v10.54a4 4 0 1 1-4 0V4a2 2 0 0 1 4 0Z\" />","sun":"<circle cx=\"12\" cy=\"12\" r=\"4\" /> <path d=\"M12 2v2\" /> <path d=\"M12 20v2\" /> <path d=\"m4.93 4.93 1.41 1.41\" /> <path d=\"m17.66 17.66 1.41 1.41\" /> <path d=\"M2 12h2\" /> <path d=\"M20 12h2\" /> <path d=\"m6.34 17.66-1.41 1.41\" /> <path d=\"m19.07 4.93-1.41 1.41\" />","droplets":"<path d=\"M7 16.3c2.2 0 4-1.83 4-4.05 0-1.16-.57-2.26-1.71-3.19S7.29 6.75 7 5.3c-.29 1.45-1.14 2.84-2.29 3.76S3 11.1 3 12.25c0 2.22 1.8 4.05 4 4.05z\" /> <path d=\"M12.56 6.6A10.97 10.97 0 0 0 14 3.02c.5 2.5 2 4.9 4 6.5s3 3.5 3 5.5a6.98 6.98 0 0 1-11.91 4.97\" />","wifi":"<path d=\"M12 20h.01\" /> <path d=\"M2 8.82a15 15 0 0 1 20 0\" /> <path d=\"M5 12.859a10 10 0 0 1 14 0\" /> <path d=\"M8.5 16.429a5 5 0 0 1 7 0\" />","wifi-off":"<path d=\"M12 20h.01\" /> <path d=\"M8.5 16.429a5 5 0 0 1 7 0\" /> <path d=\"M5 12.859a10 10 0 0 1 5.17-2.69\" /> <path d=\"M19 12.859a10 10 0 0 0-2.007-1.523\" /> <path d=\"M2 8.82a15 15 0 0 1 4.177-2.643\" /> <path d=\"M22 8.82a15 15 0 0 0-11.288-3.764\" /> <path d=\"m2 2 20 20\" />","sliders-horizontal":"<line x1=\"21\" x2=\"14\" y1=\"4\" y2=\"4\" /> <line x1=\"10\" x2=\"3\" y1=\"4\" y2=\"4\" /> <line x1=\"21\" x2=\"12\" y1=\"12\" y2=\"12\" /> <line x1=\"8\" x2=\"3\" y1=\"12\" y2=\"12\" /> <line x1=\"21\" x2=\"16\" y1=\"20\" y2=\"20\" /> <line x1=\"12\" x2=\"3\" y1=\"20\" y2=\"20\" /> <line x1=\"14\" x2=\"14\" y1=\"2\" y2=\"6\" /> <line x1=\"8\" x2=\"8\" y1=\"10\" y2=\"14\" /> <line x1=\"16\" x2=\"16\" y1=\"18\" y2=\"22\" />","check":"<path d=\"M20 6 9 17l-5-5\" />","settings-2":"<path d=\"M20 7h-9\" /> <path d=\"M14 17H5\" /> <circle cx=\"17\" cy=\"17\" r=\"3\" /> <circle cx=\"7\" cy=\"7\" r=\"3\" />","x":"<path d=\"M18 6 6 18\" /> <path d=\"m6 6 12 12\" />","triangle-alert":"<path d=\"m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3\" /> <path d=\"M12 9v4\" /> <path d=\"M12 17h.01\" />"};</script>
<script src="https://cdn.jsdelivr.net/npm/mqtt@5.10.1/dist/mqtt.min.js"></script>
<script src="app.js"></script>
</body>
</html>
```


## 12.4 dashboard/style.css

```css
/* Home dashboard v5 - a physical control panel: matte graphite plates, screws, recessed lamp windows, glowing LEDs */
:root{
  --bg:#121315; --plate1:#25272b; --plate2:#1b1c1f; --edge:#3a3d43; --hole:#0b0b0c;
  --ink:#efe9dc; --mute:#948f84; --amber:#ffb326; --ok:#9be15d; --bad:#ff5a3c;
  --c-bulb:#ffc94a; --c-smoke:#ff5a3c; --c-temp:#ff8a2b; --c-dark:#c8e6ff; --c-fan:#7fe6c4;
}
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
html,body{height:100%;overflow:hidden;background:var(--bg);color:var(--ink);font-family:"Barlow Condensed","Arial Narrow",system-ui,sans-serif}
body{background-color:var(--bg);
  background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 .05 0'/></filter><rect width='160' height='160' filter='url(%23n)'/></svg>")}
button{font:inherit;color:inherit;border:0;background:none;cursor:pointer}
.hidden{display:none!important}

.app{height:100dvh;max-width:1200px;margin:0 auto;padding:max(12px,env(safe-area-inset-top)) 14px max(12px,env(safe-area-inset-bottom));
  display:grid;grid-template-rows:auto auto minmax(0,1fr) auto;gap:10px}

/* top bar */
.top{display:flex;align-items:center;justify-content:space-between;gap:8px}
.brand h1{font-size:25px;font-weight:700;letter-spacing:2.4px;text-transform:uppercase;line-height:1}
.brand p{font-size:13px;color:var(--mute);margin-top:3px;letter-spacing:.8px;text-transform:uppercase}
.top-r{display:flex;align-items:center;gap:8px}
.pill{display:inline-flex;align-items:center;gap:7px;padding:6px 12px;border-radius:6px;background:var(--plate2);border:1px solid var(--edge);font-size:14px;letter-spacing:1px;text-transform:uppercase;color:var(--mute);box-shadow:inset 0 2px 5px rgba(0,0,0,.6)}
.pill svg{display:none}
.pill::before{content:"";width:9px;height:9px;border-radius:50%;background:#55575c;box-shadow:inset 0 1px 2px rgba(0,0,0,.6)}
.pill.ok{color:var(--ink)} .pill.ok::before{background:var(--ok);box-shadow:0 0 9px var(--ok)}
.pill.warn{color:var(--ink)} .pill.warn::before{background:var(--amber);box-shadow:0 0 9px var(--amber);animation:blink 1s infinite}
@keyframes blink{50%{opacity:.35}}
.icon-btn{width:34px;height:34px;border-radius:6px;background:linear-gradient(var(--plate1),var(--plate2));border:1px solid var(--edge);display:grid;place-items:center;box-shadow:0 2px 0 #000}
.icon-btn:active{transform:translateY(1px);box-shadow:none}
.icon-btn svg{width:17px;height:17px;fill:none;stroke:var(--ink);stroke-width:2;stroke-linecap:round;stroke-linejoin:round}

/* sensors: small instrument plates */
.sensors{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
.sn{background:linear-gradient(var(--plate1),var(--plate2));border:1px solid var(--edge);border-radius:8px;padding:6px 10px 7px;min-width:0;box-shadow:0 3px 0 #000,inset 0 1px 0 rgba(255,255,255,.07)}
.sn .l{font-size:12px;color:var(--mute);text-transform:uppercase;letter-spacing:1.4px;display:flex;align-items:center;gap:5px}
.sn .l svg{width:12px;height:12px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.sn .v{font-family:"IBM Plex Mono",ui-monospace,Menlo,monospace;font-size:19px;font-weight:600;margin-top:2px;white-space:nowrap;color:var(--amber)}
.sn .v small{font-size:11px;font-weight:500;color:var(--mute);margin-left:3px}
.sn .v.na{font-size:12px;font-weight:500;color:var(--mute);padding-top:5px}
.sn.hot{border-color:var(--bad);box-shadow:0 3px 0 #000,0 0 20px rgba(255,90,60,.35)}
.sn.hot .v{color:var(--bad)}
.alert{display:flex;align-items:center;gap:8px;padding:7px 12px;margin-bottom:8px;border-radius:8px;background:rgba(255,90,60,.14);border:1px solid var(--bad);font-size:16px;font-weight:600;letter-spacing:.8px;text-transform:uppercase;color:#ffb5a6}
.alert svg{width:18px;height:18px;fill:none;stroke:currentColor;stroke-width:2}

/* devices: one plate each */
.devs{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));grid-template-rows:repeat(4,minmax(0,1fr));gap:10px;min-height:0}
@media (min-aspect-ratio:1/1){.devs{grid-template-columns:repeat(4,minmax(0,1fr));grid-template-rows:repeat(2,minmax(0,1fr))}}
.dev{position:relative;display:flex;flex-direction:column;align-items:center;justify-content:space-between;min-height:0;
  padding:12px 10px 10px;border-radius:10px;cursor:pointer;user-select:none;
  background:
    radial-gradient(circle,#8a8d93 0 1.4px,#2b2c2f 2.2px,transparent 3px) left 7px top 7px/8px 8px no-repeat,
    radial-gradient(circle,#8a8d93 0 1.4px,#2b2c2f 2.2px,transparent 3px) right 7px top 7px/8px 8px no-repeat,
    radial-gradient(circle,#8a8d93 0 1.4px,#2b2c2f 2.2px,transparent 3px) left 7px bottom 7px/8px 8px no-repeat,
    radial-gradient(circle,#8a8d93 0 1.4px,#2b2c2f 2.2px,transparent 3px) right 7px bottom 7px/8px 8px no-repeat,
    linear-gradient(180deg,var(--plate1),var(--plate2));
  border:1px solid var(--edge);box-shadow:0 5px 0 #000,0 12px 20px rgba(0,0,0,.5),inset 0 1px 0 rgba(255,255,255,.09);
  transition:transform .15s,box-shadow .15s,border-color .3s;overflow:hidden}
.dev:active{transform:translateY(3px);box-shadow:0 2px 0 #000,0 6px 12px rgba(0,0,0,.5),inset 0 1px 0 rgba(255,255,255,.09)}
.dev .halo{position:absolute;inset:0;opacity:0;transition:opacity .35s;pointer-events:none;
  background:radial-gradient(55% 48% at 50% 38%,color-mix(in srgb,var(--c) 42%,transparent),transparent 74%)}
.dev.on{border-color:color-mix(in srgb,var(--c) 60%,var(--edge))}
.dev.on .halo{opacity:1}
/* the lamp sits in a recessed round window */
.dev .stage{flex:1 1 0;min-height:0;width:100%;position:relative;z-index:1;display:grid;place-items:center}
.dev .stage::before{content:"";position:absolute;height:100%;aspect-ratio:1;max-width:100%;border-radius:50%;
  background:radial-gradient(circle at 50% 40%,#17181a,var(--hole) 70%);
  box-shadow:inset 0 5px 12px rgba(0,0,0,.9),0 1px 0 rgba(255,255,255,.1),0 0 0 4px #2d2f33,0 0 0 5px #46494f}
.dev .stage svg{position:absolute;inset:0;margin:auto;width:62%;height:78%;overflow:visible}
.dev .info{position:relative;z-index:1;width:100%;display:flex;align-items:center;justify-content:space-between;gap:6px;padding:0 6px;margin-top:6px}
.dev .nm{font-size:17px;font-weight:700;letter-spacing:1.1px;text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.dev .st{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11px;font-weight:600;letter-spacing:1px;color:var(--mute)}
.dev.on .st{color:var(--c)}
/* rocker switch */
.dev .sw{position:relative;width:40px;height:22px;border-radius:5px;background:var(--hole);flex:none;box-shadow:inset 0 2px 5px #000,0 1px 0 rgba(255,255,255,.1)}
.dev .sw::after{content:"";position:absolute;top:3px;left:3px;width:17px;height:16px;border-radius:3px;background:linear-gradient(#8b8e94,#5a5d63);box-shadow:0 2px 3px rgba(0,0,0,.6);transition:transform .15s,background .15s}
.dev.on .sw::after{transform:translateX(17px);background:linear-gradient(color-mix(in srgb,var(--c) 85%,#fff),var(--c));box-shadow:0 0 10px var(--c)}
.dev .mode{position:relative;z-index:2;display:flex;margin:4px 0 2px;border-radius:5px;background:var(--hole);border:1px solid var(--edge);overflow:hidden}
.dev .mode button{padding:2px 11px;font-size:13px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:var(--mute)}
.dev .mode button.act{background:var(--c);color:#17120a}
.dev .hint{position:relative;z-index:1;font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:10px;color:var(--mute);min-height:13px;text-align:center}
.dev.locked{cursor:default}
.dev.locked .sw{opacity:.35}

/* bulb + fan drawings */
.bulb .glass{fill:rgba(255,255,255,.07);stroke:rgba(255,255,255,.32);stroke-width:2;transition:fill .3s,stroke .3s,filter .3s}
.dev.on .bulb .glass{fill:color-mix(in srgb,var(--c) 80%,#fff 20%);stroke:#fff8e8;filter:drop-shadow(0 0 12px var(--c)) drop-shadow(0 0 28px var(--c))}
.bulb .fil{stroke:rgba(255,255,255,.3);stroke-width:2.4;fill:none;stroke-linecap:round}
.dev.on .bulb .fil{stroke:#fff}
.bulb .shine{fill:rgba(255,255,255,.4)}
.fan .blades{transform-origin:50px 50px}
.fan .blade{fill:rgba(255,255,255,.16);stroke:rgba(255,255,255,.38);stroke-width:1.5}
.dev.on .fan .blade{fill:color-mix(in srgb,var(--c) 75%,#fff 25%);stroke:#eafff7}
.dev.on .fan .blades{animation:spin .5s linear infinite;filter:drop-shadow(0 0 7px var(--c))}
.fan .ring{fill:none;stroke:rgba(255,255,255,.22);stroke-width:3}
@keyframes spin{to{transform:rotate(360deg)}}

/* bottom keys */
.actions{display:flex;gap:10px}
.actions button{flex:1;padding:11px 8px;border-radius:8px;font-weight:700;font-size:19px;letter-spacing:2px;text-transform:uppercase;
  background:linear-gradient(var(--plate1),var(--plate2));border:1px solid var(--edge);box-shadow:0 4px 0 #000,inset 0 1px 0 rgba(255,255,255,.1)}
.actions button:active{transform:translateY(3px);box-shadow:0 1px 0 #000}
.actions .allon{background:linear-gradient(#ffc24d,#e8960f);color:#1a1205;border-color:#ffd983}
.actions .alloff{color:var(--ink)}

/* limits sheet + connection dialog */
.modal{position:fixed;inset:0;background:rgba(6,6,7,.8);display:grid;place-items:center;z-index:20;padding:16px}
.sheet{width:min(440px,100%);max-height:92dvh;overflow:auto;background:var(--plate2);border:1px solid var(--edge);border-radius:10px;padding:18px;display:grid;gap:12px;box-shadow:0 6px 0 #000,0 30px 60px rgba(0,0,0,.7);font-family:system-ui,sans-serif}
.sheet h3{font-family:"Barlow Condensed",sans-serif;font-size:21px;letter-spacing:1.4px;text-transform:uppercase}
.sheet p{font-size:13px;color:var(--mute)}
.sheet input[type=text],.sheet input:not([type]),.sheet input[type=password]{width:100%;padding:11px 12px;border-radius:6px;border:1px solid var(--edge);background:var(--hole);color:var(--ink);font:inherit}
.sheet .row{display:flex;gap:10px}
.sheet .row button,.primary,.ghost{flex:1;padding:11px;border-radius:6px;font-weight:700;letter-spacing:.4px}
.primary{background:var(--amber);color:#1a1205} .primary.done{background:var(--ok)}
.ghost{background:var(--plate1);border:1px solid var(--edge)}
.seg2{display:flex;gap:8px} .seg2 label{flex:1} .seg2 input{display:none}
.seg2 span{display:block;text-align:center;padding:9px;border-radius:6px;background:var(--plate1);border:1px solid var(--edge);font-size:13px;font-weight:600}
.seg2 input:checked+span{background:var(--amber);color:#1a1205}
.lim label{display:flex;justify-content:space-between;font-size:13px;margin-bottom:4px} .lim label b{color:var(--amber)}
.lim input[type=range]{width:100%;accent-color:var(--amber)}
details summary{font-size:12px;color:var(--mute);cursor:pointer;margin-bottom:6px}
.toast{position:fixed;left:50%;bottom:90px;transform:translateX(-50%);background:var(--plate1);border:1px solid var(--edge);padding:9px 16px;border-radius:6px;font:600 14px system-ui,sans-serif;z-index:30;box-shadow:0 10px 24px rgba(0,0,0,.6)}

@media (max-height:640px){.sn .v{font-size:16px}.brand p{display:none}.dev .nm{font-size:15px}}
@media (max-width:480px){.dev .st{display:none}}
@media (max-width:480px){.brand h1{font-size:20px;letter-spacing:1.6px;white-space:nowrap}.brand p{font-size:11px;white-space:nowrap}.dev .nm{font-size:14px;letter-spacing:.4px}.sn .l{letter-spacing:.5px;font-size:11px}.sn .l svg{display:none}.pill{padding:5px 9px;font-size:12px}}
.app{grid-template-columns:minmax(0,1fr)}
.brand{min-width:0;flex:1}.top-r{flex:none}
.sensors{grid-template-columns:repeat(4,minmax(0,1fr))}
.sn .l,.sn .v{overflow:hidden;text-overflow:ellipsis}
@media (max-width:480px){.brand h1{font-size:17px;letter-spacing:1.2px}.pill{font-size:11px;letter-spacing:.5px}.icon-btn{width:30px;height:30px}.sn .v{font-size:17px}}
```


## 12.5 dashboard/app.js

```javascript
// Home dashboard - works on the local network (HTTP) and from anywhere through the cloud (MQTT)
const $ = (s, r = document) => r.querySelector(s);
const ic = (name) =>
  `<svg viewBox="0 0 24 24" aria-hidden="true">${window.ICONS[name] || ""}</svg>`;
document.querySelectorAll("[data-i]").forEach((el) => (el.innerHTML = ic(el.dataset.i)));

// relay index -> what it is (same order as the Arduino sketch)
const DEVICES = [
  { id: 0, name: "Fan", kind: "fan", c: "--c-fan" },
  { id: 1, name: "Bulb 1", kind: "bulb", c: "--c-bulb" },
  { id: 2, name: "Bulb 2", kind: "bulb", c: "--c-bulb" },
  { id: 3, name: "Bulb 3", kind: "bulb", c: "--c-bulb" },
  { id: 4, name: "Bulb 4", kind: "bulb", c: "--c-bulb" },
  { id: 5, name: "Smoke light", kind: "bulb", c: "--c-smoke", key: "smoke" },
  { id: 6, name: "Temp light", kind: "bulb", c: "--c-temp", key: "temp" },
  { id: 7, name: "Dark light", kind: "bulb", c: "--c-dark", key: "lux" },
];
// everything is OFF and manual until the board reports its real state
const blankState = () => ({ relays: [0,0,0,0,0,0,0,0], auto: [0,0,0], smoke: 0, mq2Ready: false, temp: 0, hum: 0, dhtOk: false,
  lux: 0, luxOk: false, tSmoke: 512, tTemp: 30, tLux: 100 });

/* ---------- settings (kept only in this browser) ---------- */
const DEFAULT_WS = "wss://io.adafruit.com:443";
let cfg = { mode: "", ip: "", user: "", key: "", ws: DEFAULT_WS };
try {
  const saved = JSON.parse(localStorage.getItem("home_cfg") || "null");
  if (saved) cfg = Object.assign(cfg, saved);
  else if (localStorage.getItem("sn_ip")) { cfg.mode = "local"; cfg.ip = localStorage.getItem("sn_ip"); }
} catch (e) {}
// phone setup link:  https://your-page/#cloud=USERNAME:KEY   (saved, then removed from the address bar)
try {
  const m = location.hash.match(/cloud=([^:&]+):([^&]+)/);
  if (m) {
    cfg.mode = "cloud"; cfg.user = decodeURIComponent(m[1]); cfg.key = decodeURIComponent(m[2]);
    saveCfg();
    history.replaceState(null, "", location.pathname + location.search);
  }
} catch (e) {}
function saveCfg() { try { localStorage.setItem("home_cfg", JSON.stringify(cfg)); } catch (e) {} }

const topicStatus = () => `${cfg.user}/feeds/home-status`;
const topicCmd = () => `${cfg.user}/feeds/home-cmd`;

let S = blankState();       // last known status (all OFF until the board reports)
let synced = false;         // true after the first REAL status arrived
let threshInit = false;
let inflight = 0;
let lastStatusAt = 0;       // cloud: when the Arduino last reported
let brokerUp = false;
const desired = {};         // cloud: what you just pressed, until the Arduino confirms

function toast(msg) {
  const t = document.createElement("div");
  t.className = "toast"; t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2600);
}

/* ---------- local transport (HTTP to the Arduino) ---------- */
let chain = Promise.resolve();
function localApi(path) {
  const run = async () => {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), 3500);
    try {
      const r = await fetch("http://" + cfg.ip + path, { signal: ctl.signal, cache: "no-store" });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || r.status);
      return j;
    } finally { clearTimeout(t); }
  };
  const p = chain.then(run, run);
  chain = p.catch(() => {});
  return p;
}

/* ---------- cloud transport (MQTT over secure WebSocket) ---------- */
let client = null;
const pubTimes = [];
function allowPublish() {                       // free plans limit messages per minute: stay far below
  const now = Date.now();
  while (pubTimes.length && now - pubTimes[0] > 60000) pubTimes.shift();
  if (pubTimes.length >= 18) return false;
  pubTimes.push(now);
  return true;
}

function cloudPublish(obj) {
  if (!client || !brokerUp) return Promise.reject(new Error("Not connected to the cloud"));
  if (!allowPublish()) return Promise.reject(new Error("Slow down: too many commands this minute"));
  client.publish(topicCmd(), JSON.stringify(obj));
  return Promise.resolve();
}

function pathToCmd(path) {
  const u = new URL(path, "http://x");
  const q = (k) => u.searchParams.get(k);
  if (u.pathname === "/relay") return { c: "relay", id: +q("id"), s: +q("state") };
  if (u.pathname === "/all") return { c: "all", s: +q("state") };
  if (u.pathname === "/mode") return { c: "mode", id: +q("id"), a: +q("auto") };
  if (u.pathname === "/threshold") return { c: "limits", smoke: +q("smoke"), temp: +q("temp"), lux: +q("lux") };
  return null;
}

function api(path) {
  if (cfg.mode !== "cloud") return localApi(path);
  if (path.startsWith("/status")) return Promise.resolve(S);
  const cmd = pathToCmd(path);
  if (!cmd) return Promise.reject(new Error("unknown command"));
  return cloudPublish(cmd).then(() => S);
}

function cloudConnect() {
  if (client) { try { client.end(true); } catch (e) {} client = null; }
  brokerUp = false;
  if (cfg.mode !== "cloud" || !cfg.user || !cfg.key) return;
  if (typeof mqtt === "undefined") { toast("Cloud library did not load. Check the internet."); return; }
  client = mqtt.connect(cfg.ws || DEFAULT_WS, {
    username: cfg.user, password: cfg.key,
    clientId: "home-web-" + Math.random().toString(16).slice(2, 10),
    reconnectPeriod: 4000, connectTimeout: 10000, keepalive: 30, clean: true,
  });
  client.on("connect", () => {
    brokerUp = true;
    client.subscribe(topicStatus());
    // 1) Adafruit keeps the last status of the feed: "/get" sends it to us at once, so the buttons are ready immediately
    try { client.publish(topicStatus() + "/get", ""); } catch (e) {}
    // 2) ask the Arduino for a fresh state too (repeats until it answers)
    synced = false; askHello();
    updatePill();
  });
  client.on("close", () => { brokerUp = false; updatePill(); });
  client.on("error", () => { brokerUp = false; updatePill(); });
  client.on("message", (topic, payload) => {
    let j;
    try { j = JSON.parse(payload.toString()); } catch (e) { return; }
    if (!j || !j.relays) return;
    lastStatusAt = Date.now();
    synced = true;
    applyDesired(j);
    render(j);
  });
}

// keep what you just pressed on screen until the Arduino confirms it
// ask for the real state; repeat every 3 s until it arrives (the first press is never wasted)
let helloTimer = null, helloTries = 0;
function askHello() {
  clearInterval(helloTimer); helloTries = 0;
  const go = () => {
    if (synced || cfg.mode !== "cloud" || !brokerUp) { clearInterval(helloTimer); return; }
    if (++helloTries > 8) { clearInterval(helloTimer); return; }
    cloudPublish({ c: "hello" }).catch(() => {});
  };
  go(); helloTimer = setInterval(go, 3000);
}

function applyDesired(j) {
  const now = Date.now();
  for (const k of Object.keys(desired)) {
    const d = desired[k];
    const same = d.type === "r" ? j.relays[d.id] === d.val : j.auto[d.id - 5] === d.val;
    if (same || now > d.until) delete desired[k];
    else if (d.type === "r") j.relays[d.id] = d.val;
    else j.auto[d.id - 5] = d.val;
  }
}

/* ---------- connection pill ---------- */
function updatePill() {
  const el = $("#conn");
  let cls = "pill", label = "Offline", icon = "wifi-off";
  if (cfg.mode === "cloud") {
    const fresh = Date.now() - lastStatusAt < 45000;
    if (brokerUp && synced && fresh) { cls += " ok"; label = "Connected"; icon = "wifi"; }
    else if (brokerUp && !synced) { cls += " warn"; label = "Syncing"; icon = "wifi"; }
    else if (brokerUp) { cls += " warn"; label = "Arduino offline"; icon = "wifi-off"; }
  } else if (synced && localOk) { cls += " ok"; label = "Connected"; icon = "wifi"; }
  el.className = cls;
  el.innerHTML = ic(icon) + `<b>${label}</b>`;
}
let localOk = false;
function setConn(ok) { localOk = ok; updatePill(); }

/* ---------- drawings (SVG) ---------- */
const bulbSvg = () => `<svg class="bulb" viewBox="0 0 100 140" aria-hidden="true">
  <path class="glass" d="M50 8C28 8 14 24 14 44c0 13 6 22 13 30 5 6 8 11 8 18v6h30v-6c0-7 3-12 8-18 7-8 13-17 13-30C86 24 72 8 50 8Z"/>
  <path class="shine" d="M30 26c4-9 12-13 20-13-9 2-16 8-18 18-1 3-4 2-2-5Z"/>
  <path class="fil" d="M40 98V70l6 8 4-12 4 12 6-8v28"/>
  <rect x="35" y="98" width="30" height="9" rx="3" fill="#9aa7b8"/><rect x="36" y="107" width="28" height="8" rx="3" fill="#7d8aa0"/>
  <rect x="37" y="115" width="26" height="8" rx="3" fill="#9aa7b8"/><path d="M42 123h16l-3 9H45Z" fill="#5d6a80"/></svg>`;
const fanSvg = () => `<svg class="fan" viewBox="0 0 100 100" aria-hidden="true">
  <circle class="ring" cx="50" cy="50" r="44"/>
  <g class="blades">
    <path class="blade" d="M50 50C40 36 42 14 50 8c8 6 10 28 0 42Z"/>
    <path class="blade" d="M50 50C64 40 86 42 92 50c-6 8-28 10-42 0Z"/>
    <path class="blade" d="M50 50C60 64 58 86 50 92c-8-6-10-28 0-42Z"/>
    <path class="blade" d="M50 50C36 60 14 58 8 50c6-8 28-10 42 0Z"/>
    <circle cx="50" cy="50" r="7" fill="#c9d4e6"/></g></svg>`;

const SENSORS = [
  { k: "smoke", label: "Smoke", icon: "flame" },
  { k: "temp", label: "Temp", icon: "thermometer" },
  { k: "lux", label: "Light", icon: "sun" },
  { k: "hum", label: "Humidity", icon: "droplets" },
];
$("#sensors").innerHTML = SENSORS.map((s) => `
  <div class="sn" id="sn-${s.k}">
    <div class="l">${ic(s.icon)}${s.label}</div>
    <div class="v na" id="v-${s.k}">--</div>
  </div>`).join("");

$("#devs").innerHTML = DEVICES.map((d) => `
  <div class="dev ${d.key ? "sensorlight" : ""}" id="d-${d.id}" data-relay="${d.id}" style="--c:var(${d.c})" role="button" tabindex="0" aria-label="${d.name}">
    <div class="halo"></div>
    <div class="stage">${d.kind === "fan" ? fanSvg() : bulbSvg()}</div>
    ${d.key ? `<div class="mode"><button data-mode="${d.id}" data-auto="1">Auto</button><button data-mode="${d.id}" data-auto="0">Manual</button></div><div class="hint"></div>` : ""}
    <div class="info"><span class="nm">${d.name}</span><span class="st">OFF</span><span class="sw"></span></div>
  </div>`).join("");

/* ---------- render (updates in place, no rebuild) ---------- */
function setSensor(k, ok, html, hot) {
  const v = $("#v-" + k);
  v.className = "v" + (ok ? "" : " na");
  v.innerHTML = ok ? html : (k === "smoke" && S.mq2Ready === false && synced ? "Warming up" : "No data");
  $("#sn-" + k).classList.toggle("hot", !!(ok && hot));
}

function renderSensors(s) {
  const sm = Math.round((s.smoke / 1023) * 100);
  setSensor("smoke", s.mq2Ready, `${sm}<small>%</small>`, s.smoke > s.tSmoke);
  setSensor("temp", s.dhtOk, `${s.temp.toFixed(1)}<small>°C</small>`, s.temp > s.tTemp);
  setSensor("lux", s.luxOk, `${Math.round(s.lux)}<small>lux</small>`, false);
  setSensor("hum", s.dhtOk, `${s.hum.toFixed(0)}<small>%</small>`, false);
  $("#smokeAlert").classList.toggle("hidden", !(s.mq2Ready && s.smoke > s.tSmoke));
}

function autoHint(d, s) {
  if (d.key === "smoke") return s.mq2Ready ? `Smoke ${Math.round((s.smoke / 1023) * 100)}% · limit ${Math.round((s.tSmoke / 1023) * 100)}%` : "Sensor warming up";
  if (d.key === "temp") return s.dhtOk ? `${s.temp.toFixed(1)}°C · limit ${s.tTemp}°C` : "No sensor";
  return s.luxOk ? `${Math.round(s.lux)} lux · limit ${Math.round(s.tLux)}` : "No sensor";
}

function renderDevices(s) {
  DEVICES.forEach((d) => {
    const on = s.relays[d.id] === 1;
    const el = $("#d-" + d.id);
    el.classList.toggle("on", on);
    el.querySelector(".st").textContent = on ? "ON" : "OFF";
    if (d.key) {
      const auto = s.auto[d.id - 5] === 1;
      el.classList.toggle("locked", auto);
      el.querySelectorAll(".mode button").forEach((b) => b.classList.toggle("act", (b.dataset.auto === "1") === auto));
      el.querySelector(".hint").textContent = auto ? autoHint(d, s) : "Manual: tap to switch";
    }
  });
}

function initThresholds(s) {
  $("#sSmoke").value = Math.round((s.tSmoke / 1023) * 100);
  $("#sTemp").value = s.tTemp;
  $("#sLux").value = s.tLux;
  updateLabels();
  threshInit = true;
}
function updateLabels() {
  $("#lSmoke").textContent = $("#sSmoke").value + "%";
  $("#lTemp").textContent = $("#sTemp").value + " °C";
  $("#lLux").textContent = $("#sLux").value + " lux";
}

function render(s) {
  if (!s) return;
  S = s; synced = true;
  if (cfg.mode !== "cloud") setConn(true); else updatePill();
  renderSensors(s);
  renderDevices(s);
  if (!threshInit) initThresholds(s);
}

/* ---------- actions: update screen first, then tell the board ---------- */
function failed(err) {
  toast(err && err.message ? err.message : "Could not send");
  if (cfg.mode !== "cloud") poll();
}

function notReady() {
  if (synced) return false;
  toast("Connecting to your home... one second");
  if (cfg.mode === "cloud" && brokerUp) askHello();
  return true;
}

function toggle(id) {
  if (notReady()) return;
  const idx = Number(id);
  if (idx >= 5 && S.auto[idx - 5] === 1) { toast("This light is in Auto. Switch it to Manual first."); return; }
  const next = S.relays[idx] === 1 ? 0 : 1;
  S.relays[idx] = next;                                    // instant feedback
  renderDevices(S);
  inflight++;
  api(`/relay?id=${idx}&state=${next}`)
    .then((j) => { if (cfg.mode === "cloud") desired["r" + idx] = { type: "r", id: idx, val: next, until: Date.now() + 9000 }; if (j) render(j); })
    .catch((e) => { S.relays[idx] = next ? 0 : 1; renderDevices(S); failed(e); })
    .finally(() => { inflight--; });
}

function setAll(on) {
  if (notReady()) return;
  const val = on ? 1 : 0, old = S.relays.slice();
  for (let i = 0; i < 8; i++) if (!(i >= 5 && S.auto[i - 5] === 1)) { S.relays[i] = val; if (cfg.mode === "cloud") desired["r" + i] = { type: "r", id: i, val, until: Date.now() + 9000 }; }
  renderDevices(S);
  inflight++;
  const send = cfg.mode === "cloud"
    ? api(`/all?state=${val}`)
    : Promise.all(S.relays.map((_, i) => (i >= 5 && S.auto[i - 5] === 1) ? null : localApi(`/relay?id=${i}&state=${val}`)).filter(Boolean));
  send.then((j) => { if (j && j.relays) render(j); })
      .catch((e) => { S.relays = old; renderDevices(S); failed(e); })
      .finally(() => { inflight--; });
}

function setMode(id, auto) {
  if (notReady()) return;
  const idx = Number(id), val = Number(auto);
  const old = S.auto[idx - 5];
  S.auto[idx - 5] = val;
  renderDevices(S);
  inflight++;
  api(`/mode?id=${idx}&auto=${val}`)
    .then((j) => { if (cfg.mode === "cloud") desired["m" + idx] = { type: "m", id: idx, val, until: Date.now() + 9000 }; if (j) render(j); })
    .catch((e) => { S.auto[idx - 5] = old; renderDevices(S); failed(e); })
    .finally(() => { inflight--; });
}

document.addEventListener("click", (e) => {
  const m = e.target.closest("[data-mode]");
  if (m) { e.stopPropagation(); return setMode(m.dataset.mode, m.dataset.auto); }
  const r = e.target.closest("[data-relay]");
  if (r) return toggle(r.dataset.relay);
});
document.addEventListener("keydown", (e) => {
  if ((e.key === "Enter" || e.key === " ") && e.target.matches && e.target.matches("[data-relay]")) { e.preventDefault(); toggle(e.target.dataset.relay); }
});
$("#allOn").addEventListener("click", () => setAll(true));
$("#allOff").addEventListener("click", () => setAll(false));

["#sSmoke", "#sTemp", "#sLux"].forEach((id) => $(id).addEventListener("input", updateLabels));
$("#limBtn").addEventListener("click", () => $("#limModal").classList.remove("hidden"));
$("#limClose").addEventListener("click", () => $("#limModal").classList.add("hidden"));
$("#apply").addEventListener("click", () => {
  if (notReady()) return;
  const smoke = Math.round(($("#sSmoke").value / 100) * 1023);
  const b = $("#apply");
  api(`/threshold?smoke=${smoke}&temp=${$("#sTemp").value}&lux=${$("#sLux").value}`)
    .then((s) => {
      if (s && s.relays) render(s);
      b.classList.add("done"); b.textContent = "Saved";
      setTimeout(() => { b.classList.remove("done"); b.textContent = "Apply limits"; $("#limModal").classList.add("hidden"); }, 900);
    })
    .catch(failed);
});

/* ---------- settings dialog ---------- */
const modal = $("#modal");
function showMode() {
  const cloud = $("#mCloud").checked;
  $("#cloudBox").classList.toggle("hidden", !cloud);
  $("#localBox").classList.toggle("hidden", cloud);
}
function openModal() {
  $("#mCloud").checked = cfg.mode !== "local";
  $("#mLocal").checked = cfg.mode === "local";
  $("#cUser").value = cfg.user; $("#cKey").value = cfg.key;
  $("#cWs").value = cfg.ws || DEFAULT_WS; $("#ipInput").value = cfg.ip;
  showMode();
  modal.classList.remove("hidden");
}
function closeModal() { modal.classList.add("hidden"); }
$("#ipBtn").addEventListener("click", openModal);
$("#ipCancel").addEventListener("click", closeModal);
$("#mCloud").addEventListener("change", showMode);
$("#mLocal").addEventListener("change", showMode);
$("#ipSave").addEventListener("click", () => {
  cfg.mode = $("#mCloud").checked ? "cloud" : "local";
  cfg.user = $("#cUser").value.trim(); cfg.key = $("#cKey").value.trim();
  cfg.ws = $("#cWs").value.trim() || DEFAULT_WS;
  cfg.ip = $("#ipInput").value.trim().replace(/^https?:\/\//, "").replace(/\/$/, "");
  saveCfg();
  threshInit = false; S = blankState(); synced = false; lastStatusAt = 0; renderSensors(S); renderDevices(S);
  closeModal();
  start();
});

/* ---------- polling (local mode only) ---------- */
let polling = false;
async function poll() {
  if (cfg.mode !== "local" || !cfg.ip) return;
  if (polling || inflight > 0) return;
  polling = true;
  try { const s = await localApi("/status"); if (inflight === 0) render(s); }
  catch (e) { setConn(false); }
  polling = false;
}

function tick() {
  $("#clock").textContent = new Date().toLocaleString([], { weekday: "long", hour: "2-digit", minute: "2-digit" });
  if (cfg.mode === "cloud") updatePill();
}

function start() {
  synced = false; S = blankState(); renderSensors(S); renderDevices(S);
  if (client) { try { client.end(true); } catch (e) {} client = null; }
  brokerUp = false;
  if (cfg.mode === "cloud") cloudConnect();
  updatePill();
  poll();
}

// when you come back to the page, ask the Arduino for a fresh status
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && cfg.mode === "cloud" && Date.now() - lastStatusAt > 25000) { synced = false; askHello(); }
});

tick(); setInterval(tick, 30000); setInterval(() => { if (cfg.mode === "cloud") updatePill(); }, 5000);
setInterval(poll, 1500);
renderSensors(S); renderDevices(S);
if (!cfg.mode || (cfg.mode === "cloud" && (!cfg.user || !cfg.key))) openModal();
start();
if ("serviceWorker" in navigator && location.protocol.startsWith("http")) navigator.serviceWorker.register("sw.js").catch(() => {});
```


## 12.6 dashboard/sw.js

```javascript
// minimal service worker: lets the page install as an app. Live data always comes from the network.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});
```


## 12.7 dashboard/manifest.webmanifest

```json
{
  "name": "Home Control",
  "short_name": "Home",
  "start_url": "./",
  "display": "standalone",
  "background_color": "#121315",
  "theme_color": "#121315",
  "icons": [
    {"src": "icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
    {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}
  ]
}
```


## 12.8 whatsapp_agent/home_agent.py

```python
#!/usr/bin/env python3
"""
Home WhatsApp agent  -  control the lights and fan from WhatsApp, and get alerts.

  * Uses your own WhatsApp agent (WhatsApp > Settings > Agents > Add agent) and its API key.
  * Cloud mode (Adafruit IO) works from any internet. Local mode needs the same WiFi as the Arduino.
  * Python 3. Cloud mode needs one package: paho-mqtt (see requirements.txt).

Commands (English, Hindi or Roman Hindi/Urdu):
  status                      fan on / fan off            bulb 2 on / bulb 3 off
  all off / all on            smoke light on / off        temp light on / off
  dark light on / off         auto smoke / manual smoke   auto all / manual all
  set smoke 60                set temp 35                 set lux 150
  alerts off / alerts on      ip 192.168.1.50             help

Alerts sent to you: smoke, high temperature, Arduino offline/back online, sensor not working.
Only the paired chat can use it. Nothing secret is ever printed.
"""
import json
import logging
import os
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
log = logging.getLogger("home-agent")

# ----------------------------------------------------------------------------- settings
def read_env_file(path: Path) -> dict:
    out = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


CFG = {}
CFG.update(read_env_file(HERE / ".env"))                # your settings (never share this file)
for _k in ("OPENAI_API_KEY", "OPENAI_CHAT_MODEL", "WHATSAPP_TOKEN", "WHATSAPP_ALLOWED_NUMBER", "WHATSAPP_PAIR_CODE", "WHATSAPP_API_BASE",
           "ARDUINO_IP", "ALERT_COOLDOWN_MIN", "ARDUINO_MODE", "MQTT_HOST", "MQTT_PORT", "MQTT_USER", "MQTT_KEY",
           "MQTT_TOPIC_STATUS", "MQTT_TOPIC_CMD", "MQTT_TLS"):
    if os.environ.get(_k):
        CFG[_k] = os.environ[_k]

TOKEN = CFG.get("WHATSAPP_TOKEN", "")
ALLOWED = CFG.get("WHATSAPP_ALLOWED_NUMBER", "")
PAIR_CODE = CFG.get("WHATSAPP_PAIR_CODE", "")
API_BASE = (CFG.get("WHATSAPP_API_BASE") or "https://api.whatsapp.com/agent/v1").rstrip("/")
COOLDOWN = float(CFG.get("ALERT_COOLDOWN_MIN", "10")) * 60
MQTT_HOST = CFG.get("MQTT_HOST", "io.adafruit.com")
MQTT_PORT = int(CFG.get("MQTT_PORT", "8883"))
MQTT_USER = CFG.get("MQTT_USER", "")
MQTT_KEY = CFG.get("MQTT_KEY", "")
TOPIC_STATUS = CFG.get("MQTT_TOPIC_STATUS") or f"{MQTT_USER}/feeds/home-status"
TOPIC_CMD = CFG.get("MQTT_TOPIC_CMD") or f"{MQTT_USER}/feeds/home-cmd"
CLOUD = (CFG.get("ARDUINO_MODE", "cloud" if MQTT_USER else "local").lower() == "cloud") and bool(MQTT_USER and MQTT_KEY)
OPENAI_KEY = CFG.get("OPENAI_API_KEY", "")
CHAT_MODEL = CFG.get("OPENAI_CHAT_MODEL", "gpt-4o-mini")
STATE_FILE = HERE / "home_state.json"

NAMES = ["Fan", "Bulb 1", "Bulb 2", "Bulb 3", "Bulb 4", "Smoke light", "Temperature light", "Dark light"]
SENSOR_KEYS = ["smoke", "temp", "dark"]     # relay index 5, 6, 7


def digits(x) -> str:
    return re.sub(r"\D", "", str(x or ""))


def same_number(a, b) -> bool:
    x, y = digits(a), digits(b)
    return bool(x and y) and (x == y or (len(x) >= 9 and len(y) >= 9 and x[-9:] == y[-9:]))


# ----------------------------------------------------------------------------- saved state
class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = {"owner_id": "", "muted": False, "ip": ""}
        try:
            self.data.update(json.loads(STATE_FILE.read_text()))
        except Exception:  # noqa: BLE001
            pass
        if CFG.get("ARDUINO_IP") and not self.data["ip"]:
            self.data["ip"] = CFG["ARDUINO_IP"]

    def get(self, k):
        return self.data.get(k)

    def set(self, k, v):
        with self.lock:
            self.data[k] = v
            try:
                STATE_FILE.write_text(json.dumps(self.data))
            except OSError as exc:
                log.warning("Could not save state: %s", exc)


STATE = State()


# ----------------------------------------------------------------------------- the Arduino
class ArduinoError(Exception):
    pass


class Arduino:
    def __init__(self):
        self.lock = threading.Lock()

    @property
    def ip(self):
        return STATE.get("ip")

    def settle(self):
        pass

    def get(self, path, timeout=4.0, ip=None, wait=True):
        ip = ip or self.ip
        if not ip:
            raise ArduinoError("I don't know the Arduino address yet.")
        url = f"http://{ip}{path}"
        with self.lock:
            try:
                with urllib.request.urlopen(url, timeout=timeout) as r:
                    return json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                try:
                    msg = json.loads(e.read().decode()).get("error", str(e))
                except Exception:  # noqa: BLE001
                    msg = str(e)
                raise ArduinoError(msg)
            except Exception as e:  # noqa: BLE001
                raise ArduinoError(f"Arduino not reachable ({e})")

    def status(self):
        return self.get("/status")

    def find(self):
        """Look for the Arduino on this WiFi (scans the /24 of this computer)."""
        ips = set()
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ips.add(s.getsockname()[0])
            s.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            ips.add(socket.gethostbyname(socket.gethostname()))
        except Exception:  # noqa: BLE001
            pass
        bases = {".".join(i.split(".")[:3]) for i in ips if i and not i.startswith("127.")}

        def probe(ip):
            try:
                with urllib.request.urlopen(f"http://{ip}/status", timeout=0.8) as r:
                    return ip if b'"relays"' in r.read(2000) else None
            except Exception:  # noqa: BLE001
                return None

        for b in bases:
            with ThreadPoolExecutor(64) as ex:
                for found in ex.map(probe, [f"{b}.{n}" for n in range(1, 255)]):
                    if found:
                        return found
        return None


class CloudArduino:
    """Talks to the Arduino through the MQTT cloud broker (works from any internet)."""

    def __init__(self):
        try:
            import paho.mqtt.client as paho
        except ImportError:
            print("The cloud mode needs one small package. Run this once:  python3 -m pip install paho-mqtt")
            sys.exit(1)
        self.paho = paho
        self.status_data = None
        self.seq = -1
        self.at = 0.0
        self.sent = []
        self.cv = threading.Condition()
        self.connected = False
        try:
            self.c = paho.Client(paho.CallbackAPIVersion.VERSION2, client_id="home-agent-" + str(os.getpid()))
        except AttributeError:      # paho-mqtt 1.x
            self.c = paho.Client(client_id="home-agent-" + str(os.getpid()))
        self.c.username_pw_set(MQTT_USER, MQTT_KEY)
        if CFG.get("MQTT_TLS", "1") != "0":
            self.c.tls_set()
        self.c.on_connect = self._on_connect
        self.c.on_disconnect = self._on_disconnect
        self.c.on_message = self._on_message
        self.c.reconnect_delay_set(min_delay=2, max_delay=60)
        self.c.connect_async(MQTT_HOST, MQTT_PORT, keepalive=45)
        self.c.loop_start()

    @property
    def ip(self):
        return "cloud"

    def _on_connect(self, client, userdata, flags, rc, *args):
        ok = (getattr(rc, "is_failure", None) is False) or rc == 0
        self.connected = bool(ok)
        if ok:
            client.subscribe(TOPIC_STATUS)
            log.info("Connected to the cloud broker")
            self._publish({"c": "hello"})
        else:
            log.warning("Cloud broker refused the connection (%s). Check MQTT_USER / MQTT_KEY.", rc)

    def _on_disconnect(self, *args):
        self.connected = False

    def _on_message(self, client, userdata, msg):
        try:
            j = json.loads(msg.payload.decode())
        except Exception:  # noqa: BLE001
            return
        if not isinstance(j, dict) or "relays" not in j:
            return
        with self.cv:
            self.status_data, self.seq, self.at = j, j.get("seq", self.seq + 1), time.time()
            self.cv.notify_all()

    def _publish(self, obj):
        now = time.time()
        self.sent = [t for t in self.sent if now - t < 60]
        if len(self.sent) >= 14:
            raise ArduinoError("Too many commands this minute (the free cloud plan has a limit). Try again in a bit.")
        if not self.connected:
            raise ArduinoError("Not connected to the cloud broker yet.")
        self.sent.append(now)
        self.c.publish(TOPIC_CMD, json.dumps(obj))

    def status(self):
        if not self.status_data or time.time() - self.at > 45:
            raise ArduinoError("Arduino is not reporting (offline?)")
        return self.status_data

    def settle(self, timeout=9.0, since=None):
        since = self.seq if since is None else since
        end = time.time() + timeout
        with self.cv:
            while self.seq == since and time.time() < end:
                self.cv.wait(0.5)

    def get(self, path, timeout=4.0, ip=None, wait=True):
        u = urllib.parse.urlparse(path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        if u.path == "/status":
            return self.status()
        if u.path == "/relay":
            cmd = {"c": "relay", "id": int(q["id"]), "s": int(q["state"])}
        elif u.path == "/mode":
            cmd = {"c": "mode", "id": int(q["id"]), "a": int(q["auto"])}
        elif u.path == "/threshold":
            cmd = {"c": "limits"}
            for k in ("smoke", "temp", "lux"):
                if k in q:
                    cmd[k] = float(q[k]) if k != "smoke" else int(float(q[k]))
        else:
            raise ArduinoError("unknown command")
        self.status()                      # must be online
        before = self.seq
        self._publish(cmd)
        if wait:
            self.settle(since=before)
        return self.status_data

    def find(self):
        return None


ARD = CloudArduino() if CLOUD else Arduino()


# ----------------------------------------------------------------------------- WhatsApp API
class WhatsApp:
    def __init__(self):
        self.headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

    def _req(self, method, path, body=None, params=None, timeout=60):
        url = API_BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, headers=self.headers, method=method)
        return urllib.request.urlopen(req, timeout=timeout)

    def updates(self, offset):
        params = {"limit": "50", "timeout": "15"}
        if offset is not None:
            params["offset"] = str(offset)
        try:
            with self._req("GET", "/updates", params=params, timeout=45) as r:
                if r.status == 204:
                    return 204, {}
                return r.status, json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            return e.code, {}

    def send(self, to, text):
        for i in range(0, len(text), 3800):
            with self._req("POST", "/messages", {
                "messaging_product": "whatsapp", "to": to, "type": "text",
                "text": {"body": text[i:i + 3800]}}, timeout=30):
                pass

    def download_media(self, media_id):
        with self._req("GET", f"/media/{media_id}", timeout=40) as r:
            body, ctype = r.read(), r.headers.get("Content-Type", "")
        if "json" in ctype:
            url = json.loads(body.decode()).get("url")
            if not url:
                raise RuntimeError("no download link for the voice note")
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
            with urllib.request.urlopen(req, timeout=60) as r2:
                return r2.read()
        return body

    def mark_read(self, msg_id):
        try:
            with self._req("POST", "/statuses", {
                "messaging_product": "whatsapp", "status": "read", "message_id": msg_id,
                "typing_indicator": {"type": "text"}}, timeout=10):
                pass
        except Exception:  # noqa: BLE001
            pass


WA = WhatsApp()


def notify(text, force=False):
    """Send to the paired chat."""
    to = STATE.get("owner_id")
    if not to:
        log.info("Not paired yet, cannot send: %s", text.split("\n")[0])
        return
    if STATE.get("muted") and not force:
        return
    try:
        WA.send(to, text)
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not send a WhatsApp message: %s", exc)


# ----------------------------------------------------------------------------- understanding commands
ON_WORDS = {"on", "chalu", "chalao", "chala", "chalo", "chalado", "start", "jala", "jalao", "jalado", "jalana",
            "laga", "lagao", "ऑन", "चालू", "चला", "चलाओ", "चलादो", "जला", "जलाओ", "जलादो", "जलाना", "लगा", "लगाओ", "खोल"}
OFF_WORDS = {"off", "band", "bandh", "bujha", "bujhao", "bujhado", "stop", "ऑफ", "बंद", "बन्द", "बुझा", "बुझाओ", "बुझादो", "हटा"}
ALL_WORDS = {"all", "everything", "sab", "sabhi", "saari", "sari", "सब", "सभी", "सारी", "सारे"}
FAN_WORDS = {"fan", "pankha", "pankhe", "pankhay", "पंखा", "पंखे", "पँखा", "पंखा"}
BULB_WORDS = {"bulb", "bulbs", "light", "lights", "batti", "bati", "bulb1", "बल्ब", "लाइट", "बत्ती", "लाईट"}
NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4,
             "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "1": 1, "2": 2, "3": 3, "4": 4}
SMOKE_WORDS = {"smoke", "dhua", "dhuan", "dhuaan", "धुआँ", "धुआं", "धुँआ"}
TEMP_WORDS = {"temp", "temperature", "garmi", "tapman", "तापमान", "गर्मी", "तापमान"}
DARK_WORDS = {"dark", "andhera", "andhere", "अंधेरा", "अँधेरा", "lux", "ldr"}
AUTO_WORDS = {"auto", "automatic", "ऑटो", "ऑटोमैटिक", "स्वचालित"}
MANUAL_WORDS = {"manual", "मैन्युअल", "हाथ"}
STATUS_WORDS = {"status", "report", "state", "halat", "haal", "sensors", "sensor", "humidity", "stat", "kya", "स्थिति", "हाल"}
LIMIT_WORDS = {"set", "limit", "threshold", "limits"}

HELP = (
    "Just write or say what you want, in any words. Examples:\n"
    "- turn off light 1 and light 2\n"
    "- bulb 3 on, fan off\n"
    "- switch everything off\n"
    "- is the fan on? / what is the temperature?\n"
    "- smoke light auto / set temp limit 35\n"
    "- alerts off / alerts on\n"
    "Voice notes work too. Hindi and Urdu are fine."
)


def tokens(text):
    return re.findall(r"[\wऀ-ॿ]+", text.lower())


def parse_one(text, inherit=None):
    """One clause -> (actions, error_text). inherit = "on"/"off" from the clause before."""
    t = text.strip()
    low = t.lower()
    tk = tokens(t)
    ts = set(tk)

    if not tk:
        return [], None
    if ts & {"help", "commands", "menu", "madad", "मदद"} and len(tk) <= 3:
        return [("help",)], None
    m = re.match(r"^\s*ip\s+(\d{1,3}(?:\.\d{1,3}){3})\s*$", low)
    if m:
        return [("ip", m.group(1))], None
    if "alerts" in ts or "alert" in ts or "notifications" in ts:
        if ts & OFF_WORDS or "mute" in ts:
            return [("mute", True)], None
        if ts & ON_WORDS or "unmute" in ts:
            return [("mute", False)], None
    if "mute" in ts:
        return [("mute", True)], None
    if "unmute" in ts:
        return [("mute", False)], None

    # set a limit:  set smoke 60 / set temp 35 / set lux 150
    if ts & LIMIT_WORDS:
        m = re.search(r"(smoke|dhua|dhuan|temp|temperature|lux|dark|light)\D{0,12}?(\d+(?:\.\d+)?)", low)
        if m:
            what = m.group(1)
            key = "smoke" if what in SMOKE_WORDS else "temp" if what in TEMP_WORDS else "lux"
            return [("limit", key, float(m.group(2)))], None

    on = bool(ts & ON_WORDS) and not (ts & OFF_WORDS)
    off = bool(ts & OFF_WORDS)
    action = "off" if off else "on" if on else None
    mode = "auto" if ts & AUTO_WORDS else "manual" if ts & MANUAL_WORDS else None

    targets = []   # relay indexes
    want_all = bool(ts & ALL_WORDS)
    if ts & FAN_WORDS:
        targets.append(0)
    for m in re.finditer(r"(?:bulb|light|batti|bati|बल्ब|लाइट|बत्ती|लाईट)\s*([1-4])", low):
        targets.append(int(m.group(1)))
    if not any(1 <= x <= 4 for x in targets):
        # "bulb two", "bulb ek"
        for i, w in enumerate(tk):
            if w in BULB_WORDS and i + 1 < len(tk) and tk[i + 1] in NUM_WORDS and NUM_WORDS[tk[i + 1]] <= 4:
                targets.append(NUM_WORDS[tk[i + 1]])
    sensor_idx = []
    if ts & SMOKE_WORDS:
        sensor_idx.append(5)
    if ts & TEMP_WORDS:
        sensor_idx.append(6)
    if ts & DARK_WORDS:
        sensor_idx.append(7)

    if action is None and inherit and (targets or sensor_idx) and not mode:
        action = inherit
    acts = []
    if mode and (sensor_idx or want_all):
        for i in (sensor_idx or [5, 6, 7]):
            acts.append(("mode", i, mode == "auto"))
        if not action:
            return acts, None
    if action:
        if want_all and not targets and not sensor_idx:
            acts.append(("all", action == "on"))
            return acts, None
        for i in targets + sensor_idx:
            acts.append(("relay", i, action == "on"))
        if acts and any(a[0] == "relay" for a in acts):
            return acts, None
        if sensor_idx == [] and not targets:
            return [], "Which one? For example: fan on, bulb 2 off, smoke light on, all off."
    if ts & STATUS_WORDS or low in ("?", "hi", "hello", "hey"):
        return [("status",)], None
    if len(tk) <= 2 and (ts & FAN_WORDS or ts & BULB_WORDS or sensor_idx):
        return [], "Say on or off, for example: fan on."
    return [], "I did not understand. Send HELP to see the commands."


def parse(text):
    """Whole message -> (actions, error). 'fan on and bulb 1 off' works; 'bulb 1 and bulb 3 on' shares the action."""
    clauses = [c for c in re.split(r"\s+(?:and|aur|then|phir|plus)\s+|\s+(?:और|फिर)\s+|[,;&]", text.strip(), flags=re.I) if c.strip()]
    if len(clauses) <= 1:
        return parse_one(text)
    # a clause with no on/off word takes it from the next clause ("bulb 1 and bulb 3 on")
    def has_action(c):
        ts = set(tokens(c))
        return bool(ts & ON_WORDS or ts & OFF_WORDS)
    all_acts, last = [], None
    for idx, c in enumerate(clauses):
        inherit = last
        if not has_action(c):
            for later in clauses[idx + 1:]:
                if has_action(later):
                    ts = set(tokens(later))
                    inherit = "off" if ts & OFF_WORDS else "on"
                    break
        acts, err = parse_one(c, inherit)
        if err and len(clauses) > 1 and not acts:
            return [], err
        for a in acts:
            if a[0] == "relay":
                last = "on" if a[2] else "off"
        all_acts += acts
    return all_acts, None


# ----------------------------------------------------------------------------- AI understanding + voice (OpenAI)
LLM_SYSTEM = """You control a home with 8 switches. Read the user's message (English, Hindi, Urdu or Roman Hindi, typed or from a voice note) and answer with JSON only.
Devices (id): 0 Fan, 1 Bulb 1, 2 Bulb 2, 3 Bulb 3, 4 Bulb 4, 5 Smoke light, 6 Temperature light, 7 Dark light.
Words like light, lights, bulb, batti all mean a bulb. "light 1" and "bulb 1" are the same (id 1). Lights 5, 6, 7 are only the Smoke, Temperature and Dark lights.
Allowed actions (use as many as needed):
{"do":"relay","id":0-7,"on":true|false}   switch one device
{"do":"all","on":true|false}              fan + bulbs 1-4 together (everything)
{"do":"mode","id":5|6|7,"auto":true|false}  automatic or manual for a sensor light
{"do":"limit","key":"smoke"|"temp"|"lux","value":number}  smoke is a percent 0-100, temp in C, lux in lux
{"do":"status"}                           report sensors and switches
{"do":"mute","on":true|false}             alerts off / on
Output format: {"actions":[...], "say":"one short friendly sentence only if you could not act or the user asked a question you can answer from the state; otherwise empty"}.
Never invent devices. If the message is unclear, return no actions and ask one short question in "say". Use the current state to answer questions like "is the fan on".
"""


def openai_json(path, payload, timeout=40):
    req = urllib.request.Request("https://api.openai.com" + path, data=json.dumps(payload).encode(),
                                 headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def llm_actions(text):
    """Message -> (actions as tuples, say). Raises on any problem so the old reader can take over."""
    try:
        state = status_text(ARD.status())
    except Exception:  # noqa: BLE001
        state = "(state not available)"
    out = openai_json("/v1/chat/completions", {
        "model": CHAT_MODEL, "temperature": 0, "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": LLM_SYSTEM},
                     {"role": "user", "content": f"Current state:\n{state}\n\nMessage: {text}"}]})
    data = json.loads(out["choices"][0]["message"]["content"])
    acts = []
    for a in data.get("actions") or []:
        k = a.get("do")
        if k == "relay" and isinstance(a.get("id"), int) and 0 <= a["id"] <= 7:
            acts.append(("relay", a["id"], bool(a.get("on"))))
        elif k == "all":
            acts.append(("all", bool(a.get("on"))))
        elif k == "mode" and a.get("id") in (5, 6, 7):
            acts.append(("mode", a["id"], bool(a.get("auto"))))
        elif k == "limit" and a.get("key") in ("smoke", "temp", "lux"):
            acts.append(("limit", a["key"], float(a["value"])))
        elif k == "status":
            acts.append(("status",))
        elif k == "mute":
            acts.append(("mute", bool(a.get("on"))))
    return acts, str(data.get("say") or "").strip()


def transcribe(audio: bytes, filename="voice.ogg") -> str:
    """Voice note -> text (OpenAI Whisper). Plain urllib, nothing to install."""
    b = "----homeagent" + str(int(time.time() * 1000))
    parts = []
    for name, val in (("model", "whisper-1"), ("response_format", "text")):
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{val}\r\n'.encode())
    parts.append(f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                 f'Content-Type: audio/ogg\r\n\r\n'.encode() + audio + b"\r\n")
    parts.append(f"--{b}--\r\n".encode())
    req = urllib.request.Request("https://api.openai.com/v1/audio/transcriptions", data=b"".join(parts),
                                 headers={"Authorization": f"Bearer {OPENAI_KEY}",
                                          "Content-Type": f"multipart/form-data; boundary={b}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode().strip()


# ----------------------------------------------------------------------------- doing commands
def pct(raw):
    return round(raw / 1023 * 100)


def status_text(s):
    r, au = s["relays"], s["auto"]
    lines = ["Home status"]
    lines.append(f"Fan: {'ON' if r[0] else 'off'}")
    lines.append("Bulbs: " + ", ".join(f"{i} {'ON' if r[i] else 'off'}" for i in range(1, 5)))
    sl = []
    for n, i in enumerate((5, 6, 7)):
        sl.append(f"{NAMES[i].replace(' light', '')} {'ON' if r[i] else 'off'} ({'auto' if au[n] else 'manual'})")
    lines.append("Sensor lights: " + ", ".join(sl))
    lines.append("")
    lines.append("Temperature: " + (f"{s['temp']:.1f} C (limit {s['tTemp']:g})" if s["dhtOk"] else "no sensor"))
    lines.append("Humidity: " + (f"{s['hum']:.0f}%" if s["dhtOk"] else "no sensor"))
    lines.append("Light: " + (f"{s['lux']:.0f} lux (dark below {s['tLux']:g})" if s["luxOk"] else "no sensor"))
    lines.append("Smoke: " + (f"{pct(s['smoke'])}% (limit {pct(s['tSmoke'])}%)" if s["mq2Ready"] else "sensor warming up"))
    return "\n".join(lines)


def run_action(a):
    kind = a[0]
    if kind == "help":
        return HELP
    if kind == "status":
        return status_text(ARD.status())
    if kind == "ip":
        if CLOUD:
            return "Cloud mode is on, so no IP is needed."
        ip = a[1]
        try:
            ARD.get("/status", ip=ip)
        except ArduinoError as e:
            return f"No Arduino at {ip}: {e}"
        STATE.set("ip", ip)
        return f"Saved. Arduino address is now {ip}."
    if kind == "mute":
        STATE.set("muted", a[1])
        return "Alerts are muted. Send 'alerts on' to turn them back on." if a[1] else "Alerts are on."
    if kind == "limit":
        key, val = a[1], a[2]
        if key == "smoke":
            raw = round(val / 100 * 1023) if val <= 100 else int(val)
            ARD.get(f"/threshold?smoke={raw}")
            return f"Smoke light limit set to {pct(raw)}%."
        if key == "temp":
            ARD.get(f"/threshold?temp={val:g}")
            return f"Temperature limit set to {val:g} C."
        ARD.get(f"/threshold?lux={val:g}")
        return f"Dark light turns on below {val:g} lux."
    if kind == "mode":
        i, auto = a[1], a[2]
        ARD.get(f"/mode?id={i}&auto={1 if auto else 0}")
        return f"{NAMES[i]}: {'automatic' if auto else 'manual'}."
    if kind == "relay":
        i, on = a[1], a[2]
        note = ""
        if i >= 5:
            s = ARD.status()
            if s["auto"][i - 5]:
                ARD.get(f"/mode?id={i}&auto=0", wait=False)
                note = " (switched to manual)"
        ARD.get(f"/relay?id={i}&state={1 if on else 0}")
        return f"{NAMES[i]} {'ON' if on else 'OFF'}{note}."
    if kind == "all":
        on = a[1]
        s = ARD.status()
        todo = list(range(0, 5))
        skipped = []
        for n, i in enumerate((5, 6, 7)):
            if s["auto"][n]:
                skipped.append(NAMES[i])
            else:
                todo.append(i)
        if CLOUD:                       # fewer messages: only change what is different
            todo = [i for i in todo if s["relays"][i] != (1 if on else 0)]
        for i in todo:
            ARD.get(f"/relay?id={i}&state={1 if on else 0}", wait=False)
        ARD.settle()
        msg = f"Fan and all bulbs {'ON' if on else 'OFF'}."
        if skipped:
            msg += " Left automatic: " + ", ".join(skipped) + "."
        return msg
    return "?"


def execute(acts):
    out = []
    for a in acts:
        try:
            out.append(run_action(a))
        except ArduinoError as e:
            # the address may have changed: look once, then retry
            if "not reachable" in str(e):
                ip = ARD.find()
                if ip:
                    STATE.set("ip", ip)
                    try:
                        out.append(run_action(a))
                        continue
                    except ArduinoError as e2:
                        e = e2
            out.append(f"Could not do that: {e}")
    return "\n".join(out)


def handle_text(text):
    """AI reads any normal sentence. If the AI is not available, the old word reader is used."""
    if OPENAI_KEY:
        try:
            acts, say = llm_actions(text)
            parts = []
            if acts:
                parts.append(execute(acts))
            if say:
                parts.append(say)
            if parts:
                return "\n".join(parts)
            return "I did not find anything to do. Try: turn off light 1 and light 2."
        except Exception as exc:  # noqa: BLE001
            log.warning("AI reading failed (%s), using the simple reader", type(exc).__name__)
    acts, err = parse(text)
    if err:
        return err
    if not acts:
        return None
    return execute(acts)


# ----------------------------------------------------------------------------- alerts
class Monitor(threading.Thread):
    daemon = True

    def __init__(self):
        super().__init__()
        self.active = {}      # key -> last time we told you
        self.count = {}       # key -> consecutive bad reads
        self.fails = 0
        self.last_find = 0
        self.up_since = time.time()

    def bad(self, key, text, need=2):
        self.count[key] = self.count.get(key, 0) + 1
        if self.count[key] < need:
            return
        now = time.time()
        if key not in self.active:
            self.active[key] = now
            notify(text)
        elif now - self.active[key] >= COOLDOWN:
            self.active[key] = now
            notify("Still happening: " + text)

    def good(self, key, text):
        self.count[key] = 0
        if key in self.active:
            del self.active[key]
            notify(text)

    def run(self):
        while True:
            try:
                s = ARD.status()
                self.fails = 0
                self.good("offline", "Arduino is back online.")
                self.check(s)
            except ArduinoError:
                self.fails += 1
                if self.fails >= 3:
                    self.bad("offline", "Arduino is not responding. Check its power and WiFi.", need=1)
                if not CLOUD and self.fails % 6 == 3 and time.time() - self.last_find > 60:
                    self.last_find = time.time()
                    ip = ARD.find()
                    if ip and ip != STATE.get("ip"):
                        STATE.set("ip", ip)
                        log.info("Found the Arduino at a new address")
            except Exception:  # noqa: BLE001
                log.exception("monitor error")
            time.sleep(5)

    def check(self, s):
        if s["mq2Ready"] and s["smoke"] > s["tSmoke"]:
            self.bad("smoke", f"SMOKE detected: {pct(s['smoke'])}% (limit {pct(s['tSmoke'])}%). Please check the house.")
        else:
            self.good("smoke", "Smoke is back to normal.")
        if s["dhtOk"] and s["temp"] > s["tTemp"]:
            self.bad("temp", f"High temperature: {s['temp']:.1f} C (limit {s['tTemp']:g} C).")
        else:
            self.good("temp", "Temperature is back to normal.")
        # sensors that stopped working (only after the Arduino has been up for a while)
        if time.time() - self.up_since > 90:
            if not s["dhtOk"]:
                self.bad("dht", "Temperature/humidity sensor (DHT22) is not working. Check its wiring.", need=6)
            else:
                self.good("dht", "Temperature/humidity sensor is working again.")
            if not s["luxOk"]:
                self.bad("lux", "Light sensor (BH1750) is not working. Check its wiring.", need=6)
            else:
                self.good("lux", "Light sensor is working again.")


# ----------------------------------------------------------------------------- reading WhatsApp
def authorized(sender):
    oid = STATE.get("owner_id")
    return bool((oid and str(sender) == oid) or (ALLOWED and same_number(sender, ALLOWED) and not oid))


seen = []
warned = {}


def on_message(msg):
    mid = msg.get("id") or ""
    sender = str(msg.get("from"))
    typ = msg.get("type")
    text = ((msg.get("text") or {}).get("body") or "").strip() if typ == "text" else ""

    if not authorized(sender):
        parts = text.split()
        if PAIR_CODE and len(parts) == 2 and parts[0].lower() == "pair" and parts[1] == PAIR_CODE:
            STATE.set("owner_id", sender)
            WA.send(sender, "Connected. Only this chat can control the home now. Send HELP.")
        elif time.time() - warned.get(sender, 0) > 600:
            warned[sender] = time.time()
            if PAIR_CODE:
                WA.send(sender, "This assistant is private. Send: PAIR followed by your code.")
        return
    if mid in seen:
        return
    seen.append(mid)
    del seen[:-300]
    WA.mark_read(mid)
    heard = ""
    if typ == "audio":
        if not OPENAI_KEY:
            WA.send(sender, "Voice notes need the OpenAI key. Please send text for now.")
            return
        try:
            text = transcribe(WA.download_media((msg.get("audio") or {}).get("id", "")))
        except Exception as exc:  # noqa: BLE001
            log.warning("voice note failed (%s)", type(exc).__name__)
            WA.send(sender, "I could not understand that voice note. Please try again or type it.")
            return
        if not text:
            WA.send(sender, "I heard nothing in that voice note. Please try again.")
            return
        heard = f'I heard: "{text}"\n'
    elif typ != "text":
        WA.send(sender, "Please send a text or a voice note, for example: turn off light 1 and light 2.")
        return
    log.info("command received (%s, %d chars)", typ, len(text))
    reply = handle_text(text)
    if reply or heard:
        WA.send(sender, heard + (reply or ""))


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    if not TOKEN:
        print("WHATSAPP_TOKEN not found. Put it in whatsapp_agent/.env (see README).")
        sys.exit(1)
    if CLOUD:
        log.info("Mode: cloud (works from any internet)")
    else:
        if not STATE.get("ip"):
            log.info("Looking for the Arduino on this WiFi...")
            ip = ARD.find()
            if ip:
                STATE.set("ip", ip)
        log.info("Mode: local WiFi. Arduino address: %s", STATE.get("ip") or "not found yet (send: ip 10.x.x.x)")
    log.info("Paired chat: %s", "yes" if STATE.get("owner_id") else "no (send PAIR <code> from WhatsApp)")
    Monitor().start()
    notify("Home agent started. Write or say what you want, for example: turn off light 1.")
    offset, fails = None, 0
    while True:
        try:
            code, data = WA.updates(offset)
            if code == 409:
                log.warning("Another program is reading WhatsApp with this token. Stop the other program first.")
                time.sleep(60)
                continue
            if code in (401, 403):
                log.warning("The WhatsApp token was refused. Check WHATSAPP_TOKEN.")
                time.sleep(300)
                continue
            if code == 204:
                fails = 0
                continue
            if code != 200:
                raise RuntimeError(f"HTTP {code}")
            fails = 0
            if data.get("next_offset") is not None:
                offset = data["next_offset"]
            for entry in data.get("entry") or []:
                for change in entry.get("changes") or []:
                    for msg in (change.get("value") or {}).get("messages") or []:
                        try:
                            on_message(msg)
                        except Exception:  # noqa: BLE001
                            log.exception("could not handle a message")
        except KeyboardInterrupt:
            break
        except Exception as exc:  # noqa: BLE001
            fails += 1
            log.warning("WhatsApp polling problem (%s)", exc)
            time.sleep(min(30, 2 * fails))


if __name__ == "__main__":
    main()
```


## 12.9 whatsapp_agent/requirements.txt

```text
paho-mqtt>=1.6
```


## 12.10 arduino/happy_birthday_lights/happy_birthday_lights.ino

```cpp
/*
  Happy Birthday - light show  (Arduino UNO R4 WiFi + 8-channel relay)

  The 7 lights flash with the Happy Birthday melody. Each note of the song
  switches ON one light for as long as the note lasts:

      note  C  D  E  F  G  A  B
      light 1  2  3  4  5  6  7      (same note in any octave = same light)

  The fan relay is NOT used. Relays are active LOW (LOW = light ON).
  Optional: a passive buzzer on pin D10 plays the real tune (see BUZZER_PIN).

  Note: this sketch replaces SmartNest on the board. Upload smartnest_v2 again
  afterwards to get the home control back.
*/

// ---------- Relay pins (same wiring as SmartNest) ----------
// order = notes C D E F G A B  ->  Bulb1, Bulb2, Bulb3, Bulb4, Smoke light, Temp light, Dark light
const uint8_t LIGHT_PIN[7] = {9, 6, 7, 5, 4, 3, 2};
const uint8_t FAN_PIN = 8;               // kept OFF the whole time

// ---------- Optional buzzer ----------
const int BUZZER_PIN = 10;               // passive buzzer: + to D10, - to GND. Set to -1 if you have none.

// ---------- Song settings ----------
const unsigned int UNIT_MS = 125;        // length of one sixteenth note. Bigger = slower song
const unsigned int GAP_MS  = 25;         // short pause between notes so repeated notes are visible
const unsigned long PAUSE_BETWEEN_PLAYS_MS = 5000;

struct Note {
  uint16_t freq;     // Hz
  uint8_t  units;    // length in sixteenths
  int8_t   light;    // 0..6 (C..B)
};

// Notes: C=0 D=1 E=2 F=3 G=4 A=5 B=6
#define C4 262
#define D4 294
#define E4 330
#define F4 349
#define G4 392
#define A4 440
#define B4 494
#define C5 523
#define D5 587
#define E5 659
#define F5 698
#define G5 784

const Note SONG[] = {
  // Happy birthday to you
  {G4, 3, 4}, {G4, 1, 4}, {A4, 4, 5}, {G4, 4, 4}, {C5, 4, 0}, {B4, 8, 6},
  // Happy birthday to you
  {G4, 3, 4}, {G4, 1, 4}, {A4, 4, 5}, {G4, 4, 4}, {D5, 4, 1}, {C5, 8, 0},
  // Happy birthday dear (name)
  {G4, 3, 4}, {G4, 1, 4}, {G5, 4, 4}, {E5, 4, 2}, {C5, 4, 0}, {B4, 4, 6}, {A4, 4, 5},
  // Happy birthday to you
  {F5, 3, 3}, {F5, 1, 3}, {E5, 4, 2}, {C5, 4, 0}, {D5, 4, 1}, {C5, 8, 0},
};
const int SONG_LEN = sizeof(SONG) / sizeof(SONG[0]);

// ---------- Helpers ----------
void lightOn(int i)  { digitalWrite(LIGHT_PIN[i], LOW); }    // active LOW
void lightOff(int i) { digitalWrite(LIGHT_PIN[i], HIGH); }

void allLights(bool on) {
  for (int i = 0; i < 7; i++) digitalWrite(LIGHT_PIN[i], on ? LOW : HIGH);
}

void playNote(const Note &n) {
  digitalWrite(FAN_PIN, HIGH);            // keep the fan OFF
  unsigned long total = (unsigned long)n.units * UNIT_MS;
  unsigned long on = total > GAP_MS ? total - GAP_MS : total;
  lightOn(n.light);
  if (BUZZER_PIN >= 0) tone(BUZZER_PIN, n.freq, on);
  delay(on);
  lightOff(n.light);
  if (BUZZER_PIN >= 0) noTone(BUZZER_PIN);
  delay(total - on);
}

// Finale: lights run left to right and back, then all flash 3 times
void finale() {
  for (int i = 0; i < 7; i++)  { lightOn(i);  delay(90); lightOff(i); }
  for (int i = 6; i >= 0; i--) { lightOn(i);  delay(90); lightOff(i); }
  for (int k = 0; k < 3; k++) {
    allLights(true);
    if (BUZZER_PIN >= 0) tone(BUZZER_PIN, C5, 200);
    delay(220);
    allLights(false);
    delay(220);
  }
}

void setup() {
  // everything OFF first (HIGH) so nothing flickers when the board starts
  pinMode(FAN_PIN, OUTPUT);
  digitalWrite(FAN_PIN, HIGH);           // fan OFF
  for (int i = 0; i < 7; i++) {
    pinMode(LIGHT_PIN[i], OUTPUT);
    digitalWrite(LIGHT_PIN[i], HIGH);
  }
  if (BUZZER_PIN >= 0) pinMode(BUZZER_PIN, OUTPUT);
  delay(2000);                            // short wait before the first play
}

void loop() {
  digitalWrite(FAN_PIN, HIGH);            // keep the fan OFF
  for (int i = 0; i < SONG_LEN; i++) playNote(SONG[i]);
  finale();
  delay(PAUSE_BETWEEN_PLAYS_MS);          // then it plays again
}
```
