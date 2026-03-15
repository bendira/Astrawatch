/*
================================================================
  AstraWatch – Code ESP32-C3 (Montre connectée)
  RYDI Group © 2024

  Sensors on the ESP32:
    - MAX30102  → SpO2 + Fréquence cardiaque
    - OLED SSD1306 → Affichage
    - Vibreur    → Alertes haptiques
    - Bouton     → SOS (appui court) / Sim mode (appui long)

  Environmental sensors (ENS160, DHT22, GPS)
  are managed by the Raspberry Pi → see app.py

  Flux de données :
    ESP32 ──POST /api/watch──► Flask Server (Raspberry Pi)
    RPi sensors read directly inside app.py
================================================================
*/

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include "MAX30105.h"        // SparkFun MAX3010x library
#include "spo2_algorithm.h"  // SparkFun SpO2 algorithm

// ================================================================
//  CONFIGURATION — MODIFIEZ ICI
// ================================================================

const char* WIFI_SSID       = "MTN HomeBox_4ED967";  // ← Your WiFi SSID
const char* WIFI_PASS       = "7DD4385D";             // ← Your WiFi password
const char* SERVER_IP       = "192.168.1.188";        // ← Raspberry Pi IP address
const int   SERVER_PORT     = 5000;
const int   SEND_INTERVAL_MS = 5000;                  // Send every 5s

// ================================================================
//  PINS (ESP32-C3)
// ================================================================

#define SDA_PIN       8
#define SCL_PIN       9
#define VIBRO_PIN     2
#define BTN_PIN       1

#define SCREEN_WIDTH  128
#define SCREEN_HEIGHT 64

// ================================================================
//  OBJETS
// ================================================================

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);
MAX30105 particleSensor;

// ================================================================
//  VARIABLES GLOBALES
// ================================================================

bool          simMode       = false;
bool          btnLastState  = HIGH;
unsigned long btnPressTime  = 0;
unsigned long lastSendTime  = 0;
int           riskLevel     = 0;

// Buffers MAX30102 pour l'algorithme SpO2
#define BUFFER_LENGTH 100
uint32_t irBuffer[BUFFER_LENGTH];
uint32_t redBuffer[BUFFER_LENGTH];
int32_t  bufferLength;
int32_t  spo2;
int8_t   validSPO2;
int32_t  heartRate;
int8_t   validHeartRate;

// ================================================================
//  STRUCT DONNÉES
// ================================================================

struct WatchData {
  float spo2;
  float heartRate;
  bool  fingerDetected;
};

// ================================================================
//  SETUP
// ================================================================

void setup() {
  Serial.begin(115200);
  delay(1000);

  // Broches
  pinMode(VIBRO_PIN, OUTPUT);
  pinMode(BTN_PIN,   INPUT_PULLUP);
  digitalWrite(VIBRO_PIN, LOW);

  // I2C
  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(400000);

  // OLED
  initOLED();

  // MAX30102
  initMAX30102();

  // WiFi
  connectWiFi();

  Serial.println("[INIT] ESP32 AstraWatch ready!");
}

// ================================================================
//  LOOP
// ================================================================

void loop() {
  yield();
  handleButton();
  checkWiFi();

  if (millis() - lastSendTime >= SEND_INTERVAL_MS) {
    WatchData data = readMAX30102();

    int risk = sendToServer(data);

    if (risk >= 0) {
      riskLevel = risk;
      updateDisplay(data, risk);
      handleVibration(risk);
    } else {
      showError("Serveur KO");
    }

    lastSendTime = millis();
  }
}

// ================================================================
//  OLED INITIALISATION
// ================================================================

void initOLED() {
  if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println("[OLED] INIT FAILED — Check SDA/SCL pins");
    while (true) delay(2000);
  }
  display.clearDisplay();
  display.setTextColor(WHITE);
  display.setTextSize(2);
  display.setCursor(10, 10);
  display.println("ASTRA");
  display.setCursor(10, 35);
  display.println("WATCH");
  display.display();
  delay(2000);
  Serial.println("[OLED] OK");
}

// ================================================================
//  MAX30102 INITIALISATION
// ================================================================

void initMAX30102() {
  if (!particleSensor.begin(Wire, I2C_SPEED_FAST)) {
    Serial.println("[MAX30102] Sensor not found!");
    showError("MAX30102 KO");
    // Continue anyway — simulation mode available
    return;
  }

  // Sensor configuration
  byte ledBrightness = 60;   // 0=Off, 255=50mA
  byte sampleAverage = 4;    // 1, 2, 4, 8, 16, 32
  byte ledMode       = 2;    // 1=Red only, 2=Red+IR
  byte sampleRate    = 100;  // 50, 100, 200, 400, 800, 1000, 1600, 3200
  int  pulseWidth    = 411;  // 69, 118, 215, 411
  int  adcRange      = 4096; // 2048, 4096, 8192, 16384

  particleSensor.setup(ledBrightness, sampleAverage, ledMode,
                       sampleRate, pulseWidth, adcRange);
  particleSensor.setPulseAmplitudeRed(0x0A);
  particleSensor.setPulseAmplitudeGreen(0);

  Serial.println("[MAX30102] OK");
}

// ================================================================
//  READ MAX30102
// ================================================================

WatchData readMAX30102() {
  WatchData d;

  // Simulation mode (long press)
  if (simMode) {
    d.spo2          = random(820, 880) / 10.0;
    d.heartRate     = random(110, 145);
    d.fingerDetected = true;
    Serial.printf("[SIM] SpO2:%.1f HR:%.0f\n", d.spo2, d.heartRate);
    return d;
  }

  // Real MAX30102 reading
  bufferLength = BUFFER_LENGTH;

  // Read 100 samples
  for (int i = 0; i < bufferLength; i++) {
    while (particleSensor.available() == false)
      particleSensor.check();

    redBuffer[i] = particleSensor.getRed();
    irBuffer[i]  = particleSensor.getIR();
    particleSensor.nextSample();
  }

  // Compute SpO2 and HR via SparkFun algorithm
  maxim_heart_rate_and_oxygen_saturation(
    irBuffer, bufferLength, redBuffer,
    &spo2, &validSPO2,
    &heartRate, &validHeartRate
  );

  // Detect if finger is placed (IR > 50000)
  long irValue = particleSensor.getIR();
  d.fingerDetected = (irValue > 50000);

  if (d.fingerDetected && validSPO2 && validHeartRate) {
    d.spo2      = (float)spo2;
    d.heartRate = (float)heartRate;
    // Values de sécurité
    d.spo2      = constrain(d.spo2,      70.0, 100.0);
    d.heartRate = constrain(d.heartRate, 30.0, 220.0);
  } else {
    // No finger or invalid reading — neutral values
    d.spo2      = 0;
    d.heartRate = 0;
  }

  Serial.printf("[MAX] SpO2:%.1f HR:%.0f Valid:%d Finger:%d IR:%ld\n",
    d.spo2, d.heartRate, validSPO2 && validHeartRate,
    d.fingerDetected, irValue);

  return d;
}

// ================================================================
//  SEND TO FLASK SERVER  →  POST /api/watch
// ================================================================

int sendToServer(WatchData& d) {
  if (WiFi.status() != WL_CONNECTED) return -2;

  HTTPClient http;
  String url = "http://" + String(SERVER_IP) + ":" +
               String(SERVER_PORT) + "/api/watch";
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  http.setTimeout(8000);

  // Build JSON payload
  StaticJsonDocument<256> doc;
  doc["spo2"]           = d.spo2;
  doc["heart_rate"]     = d.heartRate;
  doc["finger_detected"]= d.fingerDetected;
  doc["sim_mode"]       = simMode;
  doc["device"]         = "esp32_watch";

  String payload;
  serializeJson(doc, payload);
  Serial.println("[HTTP] POST /api/watch → " + payload);

  int httpCode = http.POST(payload);

  if (httpCode <= 0) {
    Serial.printf("[HTTP] Error: %s\n", http.errorToString(httpCode).c_str());
    http.end();
    return -1;
  }

  String response = http.getString();
  http.end();
  Serial.println("[HTTP] Response: " + response);

  // Parse response
  StaticJsonDocument<256> resp;
  if (deserializeJson(resp, response) != DeserializationError::Ok) {
    return -3;
  }

  int risk = resp["risk_level"] | -1;
  return risk;
}

// ================================================================
//  OLED DISPLAY
// ================================================================

void updateDisplay(WatchData& d, int risk) {
  display.clearDisplay();
  display.setTextSize(1);

  // Titre
  display.setCursor(0, 0);
  display.print("AstraWatch");
  display.drawLine(0, 9, 128, 9, WHITE);

  if (!d.fingerDetected && !simMode) {
    display.setCursor(10, 28);
    display.print("Place finger");
    display.display();
    return;
  }

  // Values
  display.setCursor(0, 12);
  display.printf("SpO2: %.1f%%", d.spo2);
  display.setCursor(0, 22);
  display.printf("FC:   %.0f bpm", d.heartRate);

  // Separator line
  display.drawLine(0, 33, 128, 33, WHITE);

  // Risk level
  display.setCursor(0, 36);
  display.print("Risque: ");

  display.setCursor(50, 36);
  switch (risk) {
    case 1: display.print("NORMAL");    break;
    case 2: display.print("ATTENTION"); break;
    case 3: display.print("DANGER");    break;
    case 4: display.print("URGENT");    break;
    case 5: display.print("CRISIS!");    break;
    default: display.print("---");      break;
  }

  // Simulation mode
  if (simMode) {
    display.setCursor(0, 56);
    display.print("[SIM MODE]");
  }

  display.display();
}

void showError(const char* msg) {
  display.clearDisplay();
  display.setTextSize(1);
  display.setCursor(10, 25);
  display.print(msg);
  display.display();
}

// ================================================================
//  ALERT VIBRATIONS
// ================================================================

void handleVibration(int risk) {
  if (risk < 3) return;

  // Number of vibrations = risk level - 2
  // Risk 3 → 1 vibration, 4 → 2, 5 → 3
  int pulses = risk - 2;
  for (int i = 0; i < pulses; i++) {
    digitalWrite(VIBRO_PIN, HIGH);
    delay(300);
    digitalWrite(VIBRO_PIN, LOW);
    delay(200);
  }
}

// ================================================================
//  BUTTON  (short press = SOS, long press 2s = sim mode)
// ================================================================

void handleButton() {
  bool state = digitalRead(BTN_PIN);

  if (state == LOW && btnLastState == HIGH) {
    btnPressTime = millis();
  }

  if (state == HIGH && btnLastState == LOW) {
    unsigned long duration = millis() - btnPressTime;

    if (duration < 800) {
      // Short press → SOS
      sendSOS();
    } else if (duration >= 2000) {
      // Long press → toggle simulation mode
      simMode = !simMode;
      Serial.println(simMode ? "[BTN] SIM Mode ON" : "[BTN] SIM Mode OFF");

      // Vibration feedback
      digitalWrite(VIBRO_PIN, HIGH);
      delay(simMode ? 600 : 200);
      digitalWrite(VIBRO_PIN, LOW);
    }
  }

  btnLastState = state;
}

// ================================================================
//  SOS
// ================================================================

void sendSOS() {
  Serial.println("[SOS] Sending SOS alert!");

  // SOS vibrations (3 long)
  for (int i = 0; i < 3; i++) {
    digitalWrite(VIBRO_PIN, HIGH);
    delay(600);
    digitalWrite(VIBRO_PIN, LOW);
    delay(200);
  }

  // Display SOS
  display.clearDisplay();
  display.setTextSize(3);
  display.setCursor(30, 20);
  display.print("SOS");
  display.display();

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[SOS] WiFi not connected!");
    return;
  }

  HTTPClient http;
  String url = "http://" + String(SERVER_IP) + ":" +
               String(SERVER_PORT) + "/api/sos";
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  http.POST("{\"sos\":true,\"device\":\"esp32_watch\"}");
  http.end();
  Serial.println("[SOS] Sent to server!");
}

// ================================================================
//  WIFI
// ================================================================

void connectWiFi() {
  display.clearDisplay();
  display.setTextSize(1);
  display.setCursor(0, 20);
  display.print("WiFi...");
  display.display();

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.printf("[WIFI] Connecting to %s\n", WIFI_SSID);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 40) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n[WIFI] Connected! IP: " + WiFi.localIP().toString());
    display.clearDisplay();
    display.setCursor(0, 20);
    display.print("WiFi OK");
    display.setCursor(0, 35);
    display.print(WiFi.localIP().toString());
    display.display();
    delay(1500);
  } else {
    Serial.println("\n[WIFI] WiFi connection failed!");
    showError("WiFi FAILED");
    delay(2000);
  }
}

void checkWiFi() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[WIFI] Disconnected! Reconnecting...");
    WiFi.disconnect();
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 20) {
      delay(500);
      attempts++;
    }
  }
}
