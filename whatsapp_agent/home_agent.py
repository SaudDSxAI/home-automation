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
