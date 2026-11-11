# WhatsApp agent

Control the fan and lights from WhatsApp (text or voice note) and get alerts.

## Setup

1. Create your WhatsApp agent: WhatsApp > **Settings** > scroll down to **Agents** > **Add agent**. Copy its **API key**.
2. Copy `.env.example` to `.env` and fill in your own values (put each value right after `=`, no comment on the same line).
3. Install and run (a virtual environment is needed on macOS / Linux):

       python3 -m venv venv
       ./venv/bin/pip install -r requirements.txt
       ./venv/bin/python home_agent.py

   Windows: `py -m venv venv`, `venv\Scripts\pip install -r requirements.txt`, `venv\Scripts\python home_agent.py`

Keep it running. Only one program can read WhatsApp with the same agent key at a time.

## Modes

- **Cloud** (any internet): fill `MQTT_USER` and `MQTT_KEY` (Adafruit IO). The computer and the Arduino can be on different networks.
- **Local**: leave `MQTT_USER` empty and set `ARDUINO_IP` (the IP the Arduino prints in the Serial Monitor). Same WiFi needed.

## First message

From the number in `WHATSAPP_ALLOWED_NUMBER`, send `status`. If it answers that it is private, send `PAIR <your pair code>` once.

## Commands

Any normal sentence works when `OPENAI_API_KEY` is set (English, Hindi, Urdu, Roman Hindi), and voice notes too.
Simple commands always work: `status`, `fan on`, `bulb 2 off`, `all off`, `smoke light on`, `auto smoke`, `manual all`,
`set smoke 60`, `set temp 35`, `set lux 150`, `alerts off`, `alerts on`, `ip 192.168.1.50`, `help`.

## Alerts

Smoke above the limit, high temperature, Arduino offline / back online, DHT22 or BH1750 not working.
Each alert repeats every `ALERT_COOLDOWN_MIN` minutes (default 10) while it lasts, then a "back to normal" message.
