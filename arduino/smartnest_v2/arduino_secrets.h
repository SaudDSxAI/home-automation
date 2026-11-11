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
