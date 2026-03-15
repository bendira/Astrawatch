# AstraWatch 🫁⌚
**Real-time asthma monitoring system**  
RYDI Group © 2024 — Made in Cameroon 🇨🇲

---

## Overview

AstraWatch is an embedded medical system that monitors asthma patients in real time using a smartwatch (ESP32-C3) and an environmental station (Raspberry Pi). Data is analysed by a MindSpore AI model and displayed on a web dashboard accessible from any browser on the local network. Relatives are automatically notified by SMS when the patient's condition becomes critical.

```
┌─────────────────┐   POST /api/watch (WiFi)
│   ESP32-C3      │ ──────────────────────────►┐
│   (Smartwatch)  │                             │
│                 │                             ▼
│  MAX30102       │              ┌──────────────────────────┐
│  → SpO2 + HR    │              │      Raspberry Pi        │
│                 │              │                          │
│  Button → SOS   │              │  ENS160 → AQI/CO2/TVOC  │
│  Vibration motor│              │  DHT22  → Temp/Humidity  │
│  OLED display   │              │  GPS    → Live location  │
└─────────────────┘              │  SIM800L→ SMS alerts     │
                                 │                          │
                                 │  Flask + MindSpore       │
                                 │  → Risk prediction 1-5   │
                                 │  → Web dashboard         │
                                 └──────────────────────────┘
                                           ▲
                              Browser: http://<RPI_IP>:5000
```

---

## Hardware

### Smartwatch (ESP32-C3)
| Component | Role |
|---|---|
| ESP32-C3 | WiFi microcontroller |
| MAX30102 | SpO2 + heart rate sensor |
| OLED SSD1306 (128x64) | Live data display |
| Vibration motor | Haptic alerts |
| Push button | SOS / simulation mode toggle |

### Environmental Station (Raspberry Pi)
| Component | Role |
|---|---|
| Raspberry Pi 3/4/5 | Embedded computer + Flask server |
| ENS160 | AQI + TVOC + eCO2 (I2C) |
| DHT22 | Temperature + Humidity (GPIO) |
| GPS NEO-6M / NEO-8M | Live location tracking (UART) |
| SIM800L | SMS alerts to relatives (UART) |

---

## Project Structure

```
AstraWatch/
│
├── server/                        ← Runs on Raspberry Pi
│   ├── app.py                     ← Main server (Flask + sensors + SMS)
│   ├── templates/
│   │   └── dashboard.html         ← Web dashboard
│   ├── model/
│   │   ├── __init__.py
│   │   └── predict.py             ← MindSpore prediction engine
│   └── model_output/
│       ├── astrawatch_mindspore.ckpt
│       ├── astrawatch_model.pkl   ← sklearn fallback
│       └── scaler.pkl
│
├── esp32/
│   └── astrawatch_esp32/
│       └── astrawatch_esp32.ino   ← ESP32 Arduino code
│
├── training/
│   └── train_model.py             ← MindSpore model training
│
├── requirements.txt               ← Raspberry Pi dependencies
└── README.md
```

---

## Installation

### 1. Raspberry Pi (Flask Server)

```bash
# Install dependencies
pip3 install -r requirements.txt

# Enable I2C and UART interfaces
sudo raspi-config
# → Interface Options → I2C → Enable
# → Interface Options → Serial Port → Enable (disable login shell)

# Run the server
cd server
python app.py
```

The dashboard is available at: **http://\<RASPBERRY_PI_IP\>:5000**

**Configuration** — open `server/app.py` and update:

```python
SMS_NUMBERS = [
    "+237600000001",   # ← Relative 1 phone number
    "+237600000002",   # ← Relative 2 phone number
]
```

---

### 2. ESP32-C3 (Arduino IDE)

**Required libraries** (install via Library Manager):
- `Adafruit SSD1306`
- `Adafruit GFX Library`
- `ArduinoJson` (version 6.x)
- `SparkFun MAX3010x Sensor Library`

**Configuration** — open `astrawatch_esp32.ino` and update:

```cpp
const char* WIFI_SSID  = "YourWiFiName";         // ← WiFi network name
const char* WIFI_PASS  = "YourWiFiPassword";     // ← WiFi password
const char* SERVER_IP  = "192.168.1.xxx";        // ← Raspberry Pi IP address
```

**ESP32-C3 Wiring:**

| Component | ESP32-C3 Pin |
|---|---|
| MAX30102 SDA | GPIO 8 |
| MAX30102 SCL | GPIO 9 |
| OLED SDA | GPIO 8 (same I2C bus) |
| OLED SCL | GPIO 9 (same I2C bus) |
| Vibration motor + | GPIO 2 |
| Button | GPIO 1 → GND |

Flash via Arduino IDE (board: `ESP32C3 Dev Module`).

---

**Raspberry Pi Wiring:**

| Component | RPi Pin |
|---|---|
| ENS160 SDA | GPIO 2 (pin 3) |
| ENS160 SCL | GPIO 3 (pin 5) |
| DHT22 DATA | GPIO 4 (pin 7) |
| GPS TX | GPIO 15 / RX (pin 10) |
| GPS RX | GPIO 14 / TX (pin 8) |
| SIM800L | USB → /dev/ttyUSB0 |

---

## Usage

### Starting the system

```bash
# 1. On the Raspberry Pi — start the server
cd server && python app.py

# 2. Power on the ESP32 (connects to WiFi automatically)

# 3. Open the dashboard from any device on the same WiFi
# http://<RASPBERRY_PI_IP>:5000
```

### Operating modes

| Mode | Dashboard shows |
|---|---|
| **ESP32 only** | Live SpO2 + HR, default env values |
| **RPi sensors only** | Live AQI + GPS + env, default vitals |
| **ESP32 + RPi** | All data live |

### Watch button

| Gesture | Action |
|---|---|
| Short press (< 0.8s) | 🚨 Send SOS alert to server + immediate SMS to relatives |
| Long press (≥ 2s) | 🔄 Toggle simulation mode ON/OFF |

---

## Risk Levels

| Level | Label | Colour | SMS sent? |
|---|---|---|---|
| 1 | ✅ Normal | Green | No |
| 2 | ⚠️ Attention | Yellow | No |
| 3 | 🔶 Danger | Orange | ✅ Yes |
| 4 | 🚨 Urgent | Red | ✅ Yes |
| 5 | 💀 CRISIS | Purple | ✅ Yes |

### SMS Messages

**Alert SMS** (sent when risk reaches level 3+):
```
ALERT ALERT
The patient is about to have an asthma attack!
Location: https://maps.google.com/?q=3.86670,11.51670
- AstraWatch
```

**Stable SMS** (sent automatically when risk drops back below 3):
```
GOOD NEWS
The patient's condition has stabilised.
There is no longer any immediate danger.
- AstraWatch
```

> A 2-minute cooldown prevents SMS spam. SOS alerts bypass the cooldown.

---

## Dashboard Access

The dashboard is **restricted to patients and doctors only**.  
Relatives do not need an account — they are notified automatically by SMS.

| Role | Dashboard access | SMS alerts |
|---|---|---|
| Patient | ✅ Yes | No |
| Doctor | ✅ Yes | No |
| Relative | ❌ No | ✅ Yes (automatic) |

---

## AI Engine

The system uses **MindSpore 2.x** (Huawei) as the primary prediction engine.

**AstraNet architecture:**
```
Input (6) → Dense(64) → BN → ReLU → Dropout
          → Dense(32) → BN → ReLU
          → Dense(16) → ReLU
          → Dense(5)  → Softmax → Risk 1-5
```

**Input features:** SpO2, Heart rate, AQI, CO2, Temperature, Humidity

**Loading priority:**
1. MindSpore (`.ckpt`) — primary engine
2. scikit-learn (`.pkl`) — automatic fallback
3. Heuristic rules — emergency fallback

---

## Flask API

| Route | Method | Source | Description |
|---|---|---|---|
| `/` | GET | Browser | Web dashboard |
| `/api/watch` | POST | ESP32 | Receives SpO2 + HR |
| `/api/latest` | GET | Dashboard | Latest merged data |
| `/api/history` | GET | — | History (last 50 entries) |
| `/api/sos` | POST | ESP32 | Watch SOS button alert |
| `/api/simulate` | POST | Dashboard | Scenario simulation |
| `/api/data` | POST | — | Legacy route (backwards compat.) |

**POST `/api/watch` example:**
```json
{
  "spo2": 96.5,
  "heart_rate": 78,
  "finger_detected": true,
  "sim_mode": false
}
```

---

## Troubleshooting

**Dashboard shows `internal_server_error`**  
→ Make sure `server/templates/dashboard.html` is in the `templates/` folder

**ESP32 won't connect to WiFi**  
→ Check `WIFI_SSID` and `WIFI_PASS` in the `.ino` file  
→ ESP32-C3 supports 2.4 GHz WiFi only (not 5 GHz)

**MindSpore fails to load**  
→ Run `pip install mindspore==2.3.0`  
→ sklearn fallback activates automatically

**GPS has no fix**  
→ Place the GPS module outdoors or near a window  
→ First fix (cold start) can take 1–5 minutes

**SIM800L not sending SMS**  
→ Check the SIM card is inserted and has credit  
→ Verify the port with `ls /dev/tty*`  
→ Test manually: `minicom -D /dev/ttyUSB0 -b 9600`

---

## Team

Project developed by **RYDI Group** for a medical innovation competition.

---

*AstraWatch — Monitor to protect* 🫁
