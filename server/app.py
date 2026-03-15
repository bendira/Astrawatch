"""
================================================================
  AstraWatch — app.py FINAL COMPLET (Raspberry Pi)
  RYDI Group © 2024

  TOUT EN UN SEUL FICHIER :
    ✅ Base de données SQLite intégrée (pas besoin de MySQL)
    ✅ DHT11 calibré et corrigé (offset température)
    ✅ SMS Twilio
    ✅ GPS NEO-6M avec position réelle
    ✅ ENS160 qualité air
    ✅ Authentification utilisateurs persistante
    ✅ Historique 7 jours en base

  LANCER : python app.py
  DASHBOARD : http://<IP_RASPBERRY>:5000

  DÉPENDANCES :
    pip install flask flask-cors pyserial pynmea2 \
                adafruit-circuitpython-dht adafruit-circuitpython-ens160 \
                RPi.GPIO twilio --break-system-packages
================================================================
"""

from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
from datetime import datetime, timedelta
import traceback
import threading
import time
import json
import os
import sqlite3
import hashlib
import secrets
import serial
import pynmea2
import board
import busio
import adafruit_dht
import adafruit_ens160
import RPi.GPIO as GPIO

# Twilio SMS
try:
    from twilio.rest import Client as TwilioClient
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False
    print("[WARN] twilio non installé — SMS désactivé")

app = Flask(__name__)
CORS(app)

# ================================================================
#  CONFIGURATION TWILIO — REMPLIR ICI
# ================================================================

TWILIO_ACCOUNT_SID  = "AC90bb83049a220ed414a411f46e0450b7"
TWILIO_AUTH_TOKEN   = "8ddf1b70f21df9a81390b7d82a3f270e"
TWILIO_FROM_NUMBER  = "+19789042639"

SMS_NUMBERS = [
    "+237656298493",
  
]
SMS_RISK_THRESHOLD = 3
SMS_COOLDOWN_S     = 120

# ================================================================
#  CONFIGURATION MATÉRIEL
# ================================================================

DHT_TYPE        = "DHT11"
DHT_PIN         = board.D17

# Correction DHT11 : le DHT11 lit souvent +5°C à +15°C trop haut
# en intérieur à cause de l'auto-échauffement. Mesurer avec
# thermomètre de référence et ajuster cet offset.
# Offset correction DHT — modifiable via /api/config sans redémarrer
# Si DHT11 proche de la RPi qui chauffe, augmenter la correction négative
# Ex: RPi chauffe le boitier de +8°C → mettre -8.0
DHT_TEMP_OFFSET = -8.0    # Correction °C (ajustable via /api/config)
DHT_HUM_OFFSET  =  0.0    # Correction humidité

GPS_PORT        = "/dev/serial0"
GPS_BAUD        = 9600
ENS160_ADDR     = 0x53

DB_PATH         = os.path.join(os.path.dirname(__file__), "astrawatch.db")

# ================================================================
#  BASE DE DONNÉES SQLITE — INIT
# ================================================================

def get_db():
    """Connexion SQLite thread-safe avec timeout pour éviter 'database is locked'."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn

def init_db():
    """Crée les tables si elles n'existent pas."""
    conn = get_db()
    c = conn.cursor()

    c.executescript("""
    PRAGMA journal_mode=WAL;
    PRAGMA foreign_keys=ON;

    CREATE TABLE IF NOT EXISTS users (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        nom         TEXT NOT NULL,
        prenom      TEXT NOT NULL,
        email       TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role        TEXT NOT NULL DEFAULT 'patient',
        patname     TEXT DEFAULT '',
        created_at  TEXT DEFAULT (datetime('now')),
        last_login  TEXT DEFAULT NULL
    );

    CREATE TABLE IF NOT EXISTS sensor_data (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        spo2            REAL,
        heart_rate      REAL,
        finger_detected INTEGER DEFAULT 1,
        sim_mode        INTEGER DEFAULT 0,
        temperature     REAL,
        humidity        REAL,
        aqi             REAL,
        co2             REAL,
        tvoc            REAL,
        latitude        REAL,
        longitude       REAL,
        altitude        REAL,
        speed_kmh       REAL,
        gps_fix         INTEGER DEFAULT 0,
        satellites      INTEGER DEFAULT 0,
        risk_level      INTEGER DEFAULT 0,
        risk_label      TEXT,
        predictive_on   INTEGER DEFAULT 0,
        watch_online    INTEGER DEFAULT 0,
        recorded_at     TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS alerts (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        alert_type  TEXT NOT NULL,
        risk_level  INTEGER,
        message     TEXT,
        sms_sent    INTEGER DEFAULT 0,
        latitude    REAL,
        longitude   REAL,
        gps_fix     INTEGER DEFAULT 0,
        created_at  TEXT DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS idx_sensor_recorded ON sensor_data(recorded_at);
    CREATE INDEX IF NOT EXISTS idx_sensor_risk     ON sensor_data(risk_level);
    CREATE INDEX IF NOT EXISTS idx_alerts_type     ON alerts(alert_type);
    """)

    conn.commit()
    conn.close()
    print(f"[DB] SQLite initialisé → {DB_PATH}")

    # Migration : ajouter colonnes manquantes si DB existait déjà avant cette version
    _migrate_db()

def _migrate_db():
    """
    SQLite ne supporte pas ALTER TABLE ADD COLUMN IF NOT EXISTS.
    On vérifie manuellement avant chaque ALTER pour être idempotent.
    Appeler à chaque démarrage — sans danger si colonnes déjà présentes.
    """
    migrations = [
        ("users",       "patname",       "ALTER TABLE users ADD COLUMN patname TEXT DEFAULT ''"),
        ("users",       "last_login",    "ALTER TABLE users ADD COLUMN last_login TEXT DEFAULT NULL"),
        ("sensor_data", "tvoc",          "ALTER TABLE sensor_data ADD COLUMN tvoc REAL DEFAULT 0"),
        ("sensor_data", "predictive_on", "ALTER TABLE sensor_data ADD COLUMN predictive_on INTEGER DEFAULT 0"),
        ("sensor_data", "watch_online",  "ALTER TABLE sensor_data ADD COLUMN watch_online INTEGER DEFAULT 0"),
        ("sensor_data", "sensor_type",   "ALTER TABLE sensor_data ADD COLUMN sensor_type TEXT DEFAULT 'finger'"),
    ]
    conn = get_db()
    for table, column, sql in migrations:
        try:
            cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            if column not in cols:
                conn.execute(sql)
                conn.commit()
                print(f"[DB] Migration OK : '{column}' ajouté à '{table}'")
        except Exception as e:
            print(f"[DB] Migration '{table}.{column}' ignorée : {e}")
    conn.close()

# Verrou pour les écritures DB
db_lock = threading.Lock()

def save_sensor_data(merged: dict):
    """Sauvegarde une lecture en base."""
    try:
        with db_lock:
            conn = get_db()
            conn.execute("""
                INSERT INTO sensor_data (
                    spo2, heart_rate, finger_detected, sim_mode,
                    temperature, humidity, aqi, co2, tvoc,
                    latitude, longitude, altitude, speed_kmh,
                    gps_fix, satellites,
                    risk_level, risk_label, predictive_on, watch_online
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                merged.get("spo2"),       merged.get("heart_rate"),
                merged.get("finger_detected", True),
                merged.get("sim_mode", False),
                merged.get("temperature"), merged.get("humidity"),
                merged.get("aqi"),         merged.get("co2"),
                merged.get("tvoc"),
                merged.get("latitude"),    merged.get("longitude"),
                merged.get("altitude"),    merged.get("speed_kmh"),
                merged.get("gps_fix", False),
                merged.get("satellites", 0),
                merged.get("risk_level", 0),
                merged.get("risk_label", ""),
                merged.get("predictive_on", False),
                merged.get("watch_online", False),
            ))
            conn.commit()
            conn.close()

            # Nettoyage : garder seulement 7 jours
            cleanup_old_data()
    except Exception as e:
        print(f"[DB] Erreur sauvegarde : {e}")

def cleanup_old_data():
    """Supprime les données de plus de 7 jours."""
    try:
        conn = get_db()
        conn.execute("""
            DELETE FROM sensor_data
            WHERE recorded_at < datetime('now', '-7 days')
        """)
        conn.commit()
        conn.close()
    except Exception:
        pass

def save_alert(alert_type: str, risk_level: int, message: str,
               sms_sent: bool, lat: float, lon: float, gps_fix: bool):
    """Sauvegarde une alerte."""
    try:
        with db_lock:
            conn = get_db()
            conn.execute("""
                INSERT INTO alerts (alert_type, risk_level, message, sms_sent,
                                    latitude, longitude, gps_fix)
                VALUES (?,?,?,?,?,?,?)
            """, (alert_type, risk_level, message, sms_sent, lat, lon, gps_fix))
            conn.commit()
            conn.close()
    except Exception as e:
        print(f"[DB] Erreur alerte : {e}")

# ================================================================
#  STOCKAGE EN MÉMOIRE
# ================================================================

MAX_HISTORY   = 50
latest_watch  = {}
latest_env    = {}
latest_merged = {}
data_history  = []
sos_pending   = False

last_sms_time  = 0
alert_sms_sent = False
sensor_lock    = threading.Lock()

# ================================================================
#  TWILIO SMS
# ================================================================

class TwilioSMS:
    def __init__(self):
        self.ready = False
        self.client = None
        if not TWILIO_AVAILABLE:
            print("[TWILIO] Module twilio non installé")
            return
        if "xxxx" in TWILIO_ACCOUNT_SID:
            print("[TWILIO] ⚠️  Credentials non configurés dans app.py")
            return
        try:
            self.client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
            self.client.api.accounts(TWILIO_ACCOUNT_SID).fetch()
            self.ready = True
            print("[TWILIO] ✅ Connecté")
        except Exception as e:
            print(f"[TWILIO] ❌ Erreur : {e}")

    def send_sms(self, number: str, message: str) -> bool:
        if not self.ready: return False
        try:
            number = number.strip()
            if not number.startswith('+'): number = '+' + number
            msg = self.client.messages.create(
                body=message, from_=TWILIO_FROM_NUMBER, to=number)
            print(f"[TWILIO] ✅ SMS → {number} | {msg.sid}")
            return True
        except Exception as e:
            print(f"[TWILIO] ❌ {e}")
            return False

    def send_alert(self, lat, lon, gps_fix):
        if not self.ready: return
        gps_str = (f"https://maps.google.com/?q={lat:.5f},{lon:.5f}"
                   if gps_fix and lat != 0.0 else "Position GPS inconnue")
        msg = f"ALERT ALERT\nPatient asthme en danger!\nPosition: {gps_str}\n- AstraWatch"
        if len(msg) > 160: msg = msg[:157] + "..."
        for n in SMS_NUMBERS:
            if n and n.strip():
                self.send_sms(n.strip(), msg)
                time.sleep(1)

    def send_stable(self):
        if not self.ready: return
        msg = "BONNE NOUVELLE\nLa condition du patient s est stabilisee.\n- AstraWatch"
        for n in SMS_NUMBERS:
            if n and n.strip():
                self.send_sms(n.strip(), msg)
                time.sleep(1)

# ================================================================
#  WRAPPER ENS160
# ================================================================

# Flag global : True si ENS160 hardware OK, False si défectueux/absent
ENS160_AVAILABLE = False

class ENS160Wrapper:
    """
    Wrapper ENS160 avec mode dégradé si le capteur est défectueux.
    Si ENS160_AVAILABLE=False, retourne des valeurs neutres (AQI=1 bon air).
    """
    STATUTS = {0:"N/A", 1:"Warmup", 2:"Starting", 3:"Valid"}

    # Valeurs par défaut quand capteur absent/défectueux
    # AQI=1=Excellent, CO2=420ppm (air extérieur normal), TVOC=0
    DEFAULT_AQI  = 1
    DEFAULT_CO2  = 420
    DEFAULT_TVOC = 0

    def __init__(self, i2c, address=0x53):
        global ENS160_AVAILABLE
        try:
            self._sensor = adafruit_ens160.ENS160(i2c, address=address)
            ENS160_AVAILABLE = True
            print(f"[ENS160] ✅ OK — adresse 0x{address:02X}")
        except Exception as e:
            ENS160_AVAILABLE = False
            self._sensor = None
            print(f"[ENS160] ❌ Non disponible : {e}")
            print("[ENS160] Mode dégradé : AQI/CO2/TVOC = valeurs neutres")

    def set_compensation(self, temp_c, hum_pct):
        if not ENS160_AVAILABLE or not self._sensor: return
        try:
            self._sensor.temperature_compensation = temp_c
            self._sensor.humidity_compensation    = hum_pct
        except Exception: pass

    def read(self):
        if not ENS160_AVAILABLE or not self._sensor:
            return self.DEFAULT_AQI, self.DEFAULT_TVOC, self.DEFAULT_CO2
        try:
            validity = self._sensor.data_validity
            if validity != 3:
                print(f"[ENS160] Statut : {self.STATUTS.get(validity,'?')} — pas encore prêt")
                return self.DEFAULT_AQI, self.DEFAULT_TVOC, self.DEFAULT_CO2
            return self._sensor.AQI, self._sensor.TVOC, self._sensor.eCO2
        except Exception as e:
            print(f"[ENS160] Erreur lecture : {e}")
            return self.DEFAULT_AQI, self.DEFAULT_TVOC, self.DEFAULT_CO2

    @staticmethod
    def interpret_aqi(aqi):
        return {1:"Excellent",2:"Good",3:"Moderate",4:"Poor",5:"Dangerous"}.get(aqi,"?")

# ================================================================
#  DHT11/22 AVEC CORRECTION TEMPÉRATURE
# ================================================================

def init_dht(dht_type, pin):
    if dht_type.upper() == "DHT22":
        print("[DHT] DHT22 init")
        return adafruit_dht.DHT22(pin)
    print("[DHT] DHT11 init")
    return adafruit_dht.DHT11(pin)

def read_dht_corrected(dht_sensor, last_temp, last_hum):
    """
    Lit le DHT11/22 et applique la correction d'offset.
    Le DHT11 en particulier a tendance à donner des valeurs
    trop élevées à cause de l'échauffement interne du PCB.
    Retourne (temp, hum, changed)
    """
    try:
        tv = dht_sensor.temperature
        hv = dht_sensor.humidity
        if tv is not None and hv is not None:
            # Appliquer l'offset de correction
            temp = round(float(tv) + DHT_TEMP_OFFSET, 1)
            hum  = round(float(hv) + DHT_HUM_OFFSET,  1)

            # Sanity check : valeurs physiquement impossibles → ignorer
            if temp < -20 or temp > 60:
                print(f"[DHT] Valeur temp aberrante {tv}°C → ignorée")
                return last_temp, last_hum, False
            if hum < 0 or hum > 100:
                print(f"[DHT] Valeur hum aberrante {hv}% → ignorée")
                return last_temp, last_hum, False

            print(f"[DHT] Brut:{tv}°C → Corrigé:{temp}°C | H:{hum}%")
            return temp, hum, True
    except RuntimeError:
        pass  # Normal pour DHT11
    except Exception as e:
        print(f"[DHT] Erreur : {e}")
    return last_temp, last_hum, False

def calcul_heat_index(temp, hum):
    if temp < 27 or hum < 40: return temp
    ic = (-8.78469 + 1.61139*temp + 2.33855*hum
          - 0.14612*temp*hum - 0.012308*temp**2
          - 0.016425*hum**2 + 0.002212*temp**2*hum
          + 0.000725*temp*hum**2 - 0.000004*temp**2*hum**2)
    return round(ic, 1)

# ================================================================
#  GPS NEO-6M
# ================================================================

class GPSReader:
    def __init__(self, port=GPS_PORT, baud=GPS_BAUD):
        self.ser  = None
        self._sat = 0
        self.data = {"latitude":0.0,"longitude":0.0,"speed_kmh":0.0,
                     "altitude":0.0,"gps_fix":False,"satellites":0}
        try:
            self.ser = serial.Serial(port, baud, timeout=1)
            print(f"[GPS] Port {port} OK")
        except Exception as e:
            print(f"[GPS] Erreur : {e}")

    def read_line(self):
        if not self.ser or not self.ser.is_open: return False
        try:
            raw = self.ser.readline().decode('ascii', errors='ignore').strip()
            if raw.startswith(('$GPGGA','$GNGGA')):
                try:
                    msg = pynmea2.parse(raw)
                    self._sat = int(msg.num_sats or 0)
                    self.data["satellites"] = self._sat
                    if int(msg.gps_qual or 0) > 0:
                        self.data.update({
                            "gps_fix":   True,
                            "latitude":  round(msg.latitude,  6),
                            "longitude": round(msg.longitude, 6),
                            "altitude":  float(msg.altitude or 0.0),
                        })
                    else:
                        self.data["gps_fix"] = False
                    return True
                except pynmea2.ParseError: pass
            elif raw.startswith(('$GPRMC','$GNRMC')):
                try:
                    msg = pynmea2.parse(raw)
                    if msg.status == 'A':
                        self.data.update({
                            "gps_fix":   True,
                            "latitude":  round(msg.latitude,  6),
                            "longitude": round(msg.longitude, 6),
                            "speed_kmh": round(float(msg.spd_over_grnd or 0)*1.852, 2),
                            "satellites": self._sat,
                        })
                    else:
                        self.data["gps_fix"] = False
                    return True
                except pynmea2.ParseError: pass
        except Exception as e:
            print(f"[GPS] Erreur lecture : {e}")
        return False

    def get(self):
        return self.data.copy()

    def maps_link(self):
        if not self.data["gps_fix"]: return None
        return f"https://www.google.com/maps?q={self.data['latitude']},{self.data['longitude']}"

# ================================================================
#  INSTANCES GLOBALES
# ================================================================

ens160_sensor = None
dht_sensor    = None
gps           = None
sms           = None

last_temp = 23.0   # Valeur initiale raisonnable
last_hum  = 60.0

# ================================================================
#  MODÈLE IA (stub si MindSpore non disponible)
# ================================================================

try:
    from model.predict import AstraPredictor
    predictor = AstraPredictor()
    print("[MODEL] AstraPredictor chargé")
except ImportError:
    print("[MODEL] model/predict.py introuvable — mode règles simples")
    class AstraPredictor:
        window_ready = False
        window_fill  = 0

        def predict(self, data):
            spo2 = data.get("spo2", 98)
            hr   = data.get("heart_rate", 72)
            aqi  = data.get("aqi", 20)
            co2  = data.get("co2", 400)
            # Règles simples basées sur les seuils médicaux
            if spo2 < 85 or hr > 140 or aqi > 250 or co2 > 2000: return 5
            if spo2 < 88 or hr > 125 or aqi > 180 or co2 > 1600: return 4
            if spo2 < 91 or hr > 110 or aqi > 120 or co2 > 1200: return 3
            if spo2 < 94 or hr > 95  or aqi > 75  or co2 > 800:  return 2
            return 1

        def get_label(self, level):
            return {0:"---",1:"Normal",2:"Attention",3:"Danger",4:"Urgent",5:"Crise"}.get(level,"?")

        def reset_window(self): pass

    predictor = AstraPredictor()

# ================================================================
#  THREAD CAPTEURS
# ================================================================

def sensor_thread():
    global latest_env, last_temp, last_hum

    print("[THREAD] Capteurs démarrés")

    while True:
        t0  = time.time()
        env = {}

        # ── DHT avec correction ──
        temp = last_temp
        hum  = last_hum
        if dht_sensor:
            t, h, ok = read_dht_corrected(dht_sensor, last_temp, last_hum)
            if ok:
                temp, hum  = t, h
                last_temp, last_hum = t, h
                hi = calcul_heat_index(temp, hum)
                if hi > temp:
                    print(f"[DHT] HeatIndex:{hi}°C")

        env["temperature"] = temp
        env["humidity"]    = hum

        # ── ENS160 (fonctionne même si capteur défectueux → valeurs neutres) ──
        if ens160_sensor:
            ens160_sensor.set_compensation(temp, hum)
            r = ens160_sensor.read()  # Retourne toujours (AQI,TVOC,CO2) même en mode dégradé
            aqi, tvoc, eco2 = r
            env.update({"aqi":aqi,"tvoc":tvoc,"co2":eco2})
            status = "HW" if ENS160_AVAILABLE else "DEFAULT"
            print(f"[ENS160] AQI:{aqi}({ENS160Wrapper.interpret_aqi(aqi)}) "
                  f"CO2:{eco2}ppm TVOC:{tvoc}ppb [{status}]")
        else:
            env.update({"aqi":1,"tvoc":0,"co2":420})

        # ── GPS ──
        if gps:
            gps.read_line()
            gps_data = gps.get()
            if gps_data["gps_fix"]:
                print(f"[GPS] {gps_data['latitude']},{gps_data['longitude']} "
                      f"| {gps_data['speed_kmh']}km/h | Sats:{gps_data['satellites']}")
            else:
                print(f"[GPS] Pas de fix | Sats:{gps_data['satellites']}")
        else:
            gps_data = {"latitude":0.0,"longitude":0.0,"speed_kmh":0.0,
                        "altitude":0.0,"gps_fix":False,"satellites":0}

        env.update(gps_data)

        with sensor_lock:
            latest_env = env.copy()

        time.sleep(max(0, 3 - (time.time() - t0)))

# ================================================================
#  FUSION + PRÉDICTION
# ================================================================

def merge_and_predict():
    global latest_merged

    with sensor_lock:
        env = latest_env.copy()

    spo2        = float(latest_watch.get("spo2",        98.0))
    heart_rate  = float(latest_watch.get("heart_rate",  72.0))
    aqi         = float(env.get("aqi",          20))
    co2         = float(env.get("co2",          420))
    temperature = float(env.get("temperature",  23.0))
    humidity    = float(env.get("humidity",     60.0))

    if not latest_watch:
        predictor.reset_window()

    try:
        risk_level    = predictor.predict({"spo2":spo2,"heart_rate":heart_rate,
                                           "aqi":aqi,"co2":co2,
                                           "temperature":temperature,"humidity":humidity})
        risk_label    = predictor.get_label(risk_level)
        predictive_on = predictor.window_ready
        window_fill   = predictor.window_fill
    except Exception as e:
        print(f"[ERROR] Prediction : {e}")
        risk_level, risk_label = 0, "Erreur"
        predictive_on, window_fill = False, 0

    merged = {
        "spo2":            spo2,
        "heart_rate":      heart_rate,
        "finger_detected": latest_watch.get("finger_detected", True),
        "sim_mode":        latest_watch.get("sim_mode", False),
        "sensor_type":     latest_watch.get("sensor_type", "finger"),
        "aqi":         aqi,  "co2":      co2,
        "temperature": temperature, "humidity": humidity,
        "tvoc":        env.get("tvoc", 0),
        "latitude":    env.get("latitude",   0.0),
        "longitude":   env.get("longitude",  0.0),
        "speed_kmh":   env.get("speed_kmh",  0.0),
        "altitude":    env.get("altitude",   0.0),
        "gps_fix":     env.get("gps_fix",   False),
        "satellites":  env.get("satellites", 0),
        "risk_level":    risk_level,
        "risk_label":    risk_label,
        "predictive_on": predictive_on,
        "window_fill":   window_fill,
        "timestamp":    datetime.now().strftime("%H:%M:%S"),
        "watch_online": bool(latest_watch),
    }

    latest_merged = merged.copy()
    data_history.append(merged.copy())
    if len(data_history) > MAX_HISTORY:
        data_history.pop(0)

    # Sauvegarder en base
    save_sensor_data(merged)

    mode_str = "PREDICTIVE" if predictive_on else f"WARMUP {window_fill}/10"
    print(f"[MERGE] {merged['timestamp']} SpO2:{spo2} FC:{heart_rate} "
          f"T:{temperature}°C H:{humidity}% AQI:{aqi} CO2:{co2} "
          f"→ Risk:{risk_level}({risk_label}) [{mode_str}]")

    return risk_level, risk_label

# ================================================================
#  SMS — Vérification et envoi
# ================================================================

def check_sms(risk_level: int):
    global last_sms_time, alert_sms_sent
    if not sms or not sms.ready: return

    now = time.time()
    with sensor_lock:
        env = latest_env.copy()

    lat, lon, gps_fix = env.get("latitude",0.0), env.get("longitude",0.0), env.get("gps_fix",False)

    if risk_level >= SMS_RISK_THRESHOLD:
        if not alert_sms_sent and now - last_sms_time >= SMS_COOLDOWN_S:
            sms.send_alert(lat=lat, lon=lon, gps_fix=gps_fix)
            save_alert("risk", risk_level, f"Risque {risk_level}", True, lat, lon, gps_fix)
            last_sms_time  = now
            alert_sms_sent = True
    else:
        if alert_sms_sent:
            sms.send_stable()
            save_alert("stable", risk_level, "Patient stabilisé", True, lat, lon, gps_fix)
            alert_sms_sent = False
            last_sms_time  = 0

# ================================================================
#  AUTHENTIFICATION UTILISATEURS
# ================================================================

def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

@app.route('/api/auth/register', methods=['POST'])
def register():
    try:
        data    = request.get_json(force=True, silent=True) or {}
        nom     = data.get('nom', '').strip()
        prenom  = data.get('prenom', '').strip()
        email   = data.get('email', '').strip().lower()
        pw      = data.get('password', '')
        role    = data.get('role', 'patient')
        patname = data.get('patname', '').strip()

        if not nom or not prenom or not email or not pw:
            return jsonify({'error': 'Missing fields'}), 400
        if len(pw) < 6:
            return jsonify({'error': 'Password too short (min 6 characters)'}), 400

        with db_lock:
            conn = get_db()
            try:
                existing = conn.execute(
                    "SELECT id FROM users WHERE email=?", (email,)
                ).fetchone()
                if existing:
                    conn.close()
                    return jsonify({'error': 'Email already in use'}), 409

                conn.execute("""
                    INSERT INTO users (nom, prenom, email, password_hash, role, patname)
                    VALUES (?,?,?,?,?,?)
                """, (nom, prenom, email, hash_password(pw), role, patname))
                conn.commit()
                row = conn.execute(
                    "SELECT id FROM users WHERE email=?", (email,)
                ).fetchone()
                user_id = row['id']
            finally:
                conn.close()

        print(f"[AUTH] New account: {prenom} {nom} <{email}> role={role}")
        return jsonify({'status': 'created', 'user_id': user_id,
                        'nom': nom, 'prenom': prenom, 'email': email,
                        'role': role, 'patname': patname}), 201

    except Exception as e:
        print(f"[AUTH] Register error: {e}")
        traceback.print_exc()
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.route('/api/auth/login', methods=['POST'])
def login():
    try:
        data  = request.get_json(force=True, silent=True) or {}
        email = data.get('email', '').strip().lower()
        pw    = data.get('password', '')

        with db_lock:
            conn = get_db()
            try:
                user = conn.execute(
                    "SELECT * FROM users WHERE email=?", (email,)
                ).fetchone()
            finally:
                conn.close()

        if not user:
            return jsonify({'error': 'Account not found'}), 404
        if user['password_hash'] != hash_password(pw):
            return jsonify({'error': 'Incorrect password'}), 401

        with db_lock:
            conn = get_db()
            try:
                conn.execute("UPDATE users SET last_login=? WHERE id=?",
                             (datetime.now().isoformat(), user['id']))
                conn.commit()
            finally:
                conn.close()

        print(f"[AUTH] Login OK: {user['prenom']} {user['nom']} <{email}>")
        return jsonify({'status': 'ok', 'user_id': user['id'],
                        'nom': user['nom'], 'prenom': user['prenom'],
                        'email': user['email'], 'role': user['role'],
                        'patname': user['patname']}), 200

    except Exception as e:
        print(f"[AUTH] Login error: {e}")
        traceback.print_exc()
        return jsonify({'error': f'Server error: {str(e)}'}), 500

# ================================================================
#  API CAPTEURS
# ================================================================

@app.route('/api/watch', methods=['POST'])
def receive_watch():
    global latest_watch
    data = request.get_json(force=True, silent=True)
    if not data: return jsonify({"error":"Invalid JSON"}), 400

    latest_watch = data.copy()
    print(f"[WATCH] SpO2:{data.get('spo2')} FC:{data.get('heart_rate')} "
          f"Finger:{data.get('finger_detected')} "
          f"Type:{data.get('sensor_type','finger')}")

    risk_level, risk_label = merge_and_predict()
    check_sms(risk_level)
    return jsonify({"risk_level":risk_level,"risk_label":risk_label,"status":"ok"}), 200

@app.route('/api/data', methods=['POST'])
def receive_data_legacy():
    global latest_watch
    data = request.get_json(force=True, silent=True)
    if not data: return jsonify({"error":"Invalid JSON"}), 400
    latest_watch = data.copy()
    risk_level, risk_label = merge_and_predict()
    check_sms(risk_level)
    return jsonify({"risk_level":risk_level,"risk_label":risk_label,"status":"ok"}), 200

@app.route('/api/sos', methods=['POST'])
def receive_sos():
    global sos_pending
    sos_pending = True
    print("[SOS] 🚨 Alerte SOS !")
    if sms and sms.ready:
        with sensor_lock:
            env = latest_env.copy()
        sms.send_alert(lat=env.get("latitude",0.0),
                       lon=env.get("longitude",0.0),
                       gps_fix=env.get("gps_fix",False))
        save_alert("sos", 5, "SOS bouton montre", True,
                   env.get("latitude",0.0), env.get("longitude",0.0),
                   env.get("gps_fix",False))
    return jsonify({"status":"sos_received"}), 200

@app.route('/api/latest', methods=['GET'])
def get_latest():
    global sos_pending
    try:
        merge_and_predict()
        resp = {"data": latest_merged, "sos": sos_pending}
        sos_pending = False
        return jsonify(resp), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"data":{}, "sos":False}), 200

@app.route('/api/history', methods=['GET'])
def get_history():
    return jsonify(data_history), 200

@app.route('/api/history/db', methods=['GET'])
def get_history_db():
    """Retourne les 100 dernières lectures depuis la BDD."""
    limit = int(request.args.get('limit', 100))
    hours = int(request.args.get('hours', 24))
    conn  = get_db()
    rows  = conn.execute("""
        SELECT * FROM sensor_data
        WHERE recorded_at >= datetime('now', ? || ' hours')
        ORDER BY recorded_at DESC LIMIT ?
    """, (f'-{hours}', limit)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in reversed(rows)]), 200

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Stats journalières pour graphiques."""
    conn = get_db()
    rows = conn.execute("""
        SELECT
            strftime('%H:%M', recorded_at) as heure,
            AVG(spo2)       as avg_spo2,
            AVG(heart_rate) as avg_hr,
            AVG(aqi)        as avg_aqi,
            AVG(co2)        as avg_co2,
            MAX(risk_level) as max_risk
        FROM sensor_data
        WHERE recorded_at >= datetime('now', '-24 hours')
        GROUP BY strftime('%H', recorded_at), strftime('%M', recorded_at) / 15
        ORDER BY heure
        LIMIT 96
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows]), 200

@app.route('/api/alerts/db', methods=['GET'])
def get_alerts_db():
    """Retourne les 50 dernières alertes depuis la BDD."""
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM alerts
        ORDER BY created_at DESC LIMIT 50
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows]), 200

# ================================================================
#  SIMULATION
# ================================================================

SIMULATION_SCENARIOS = {
    "normal":    {"spo2":98.0,"heart_rate":72, "aqi":25, "co2":420, "temperature":23.0,"humidity":55},
    "attention": {"spo2":93.5,"heart_rate":105,"aqi":90, "co2":900, "temperature":25.0,"humidity":62},
    "danger":    {"spo2":91.0,"heart_rate":118,"aqi":145,"co2":1300,"temperature":28.0,"humidity":72},
    "urgent":    {"spo2":88.5,"heart_rate":132,"aqi":200,"co2":1700,"temperature":30.0,"humidity":80},
    "crise":     {"spo2":84.0,"heart_rate":155,"aqi":280,"co2":2200,"temperature":33.0,"humidity":88},
}

@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    """
    GET  /api/config           → retourne la config actuelle
    POST /api/config           → modifie à chaud (sans redémarrer)
    Body JSON: {"dht_temp_offset": -10.0, "sms_cooldown": 30}
    """
    global DHT_TEMP_OFFSET, DHT_HUM_OFFSET, SMS_COOLDOWN_S, SMS_RISK_THRESHOLD
    global last_sms_time, alert_sms_sent

    if request.method == 'POST':
        data = request.get_json(force=True, silent=True) or {}
        if 'dht_temp_offset' in data:
            DHT_TEMP_OFFSET = float(data['dht_temp_offset'])
            print(f"[CONFIG] DHT_TEMP_OFFSET → {DHT_TEMP_OFFSET:+.1f}°C")
        if 'dht_hum_offset' in data:
            DHT_HUM_OFFSET = float(data['dht_hum_offset'])
        if 'sms_cooldown' in data:
            SMS_COOLDOWN_S = int(data['sms_cooldown'])
            print(f"[CONFIG] SMS_COOLDOWN_S → {SMS_COOLDOWN_S}s")
        if 'sms_threshold' in data:
            SMS_RISK_THRESHOLD = int(data['sms_threshold'])
        if data.get('reset_sms_cooldown'):
            last_sms_time  = 0
            alert_sms_sent = False
            print("[CONFIG] Cooldown SMS réinitialisé")

    return jsonify({
        "dht_temp_offset":   DHT_TEMP_OFFSET,
        "dht_hum_offset":    DHT_HUM_OFFSET,
        "sms_cooldown_s":    SMS_COOLDOWN_S,
        "sms_threshold":     SMS_RISK_THRESHOLD,
        "ens160_available":  ENS160_AVAILABLE,
        "alert_sms_sent":    alert_sms_sent,
        "sms_ready":         bool(sms and sms.ready),
        "last_sms_ago_s":    int(time.time() - last_sms_time) if last_sms_time else None,
    }), 200

@app.route('/api/simulate', methods=['POST'])
def simulate():
    global latest_watch, latest_env
    try:
        body     = request.get_json(force=True, silent=True) or {}
        scenario = body.get('scenario','normal').lower()
        sim      = SIMULATION_SCENARIOS.get(scenario, SIMULATION_SCENARIOS["normal"]).copy()
        latest_watch = {"spo2":sim["spo2"],"heart_rate":sim["heart_rate"],
                        "finger_detected":True,"sim_mode":True}
        with sensor_lock:
            latest_env.update({"aqi":sim["aqi"],"co2":sim["co2"],
                                "temperature":sim["temperature"],"humidity":sim["humidity"],
                                "tvoc":0,
                                # PK17 Douala — coordonnées réelles
                                "latitude":4.0746,"longitude":9.7305,
                                "gps_fix":True,"speed_kmh":0.0,
                                "altitude":12.0,"satellites":8})
        risk_level, risk_label = merge_and_predict()

        # ── Envoi SMS si scénario dangereux (risk >= threshold) ──
        # En mode simulation, on bypass le cooldown pour les tests
        force_sms = scenario in ('danger', 'urgent', 'crise')
        if force_sms:
            global last_sms_time, alert_sms_sent
            # Reset cooldown pour permettre le test SMS immédiat
            last_sms_time  = 0
            alert_sms_sent = False
        check_sms(risk_level)

        return jsonify({"risk_level":risk_level,"risk_label":risk_label,
                        "scenario":scenario,"status":"ok","sms_triggered":force_sms}), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error":str(e)}), 500

# ================================================================
#  DASHBOARD HTML (inline — pas besoin de fichier templates/)
# ================================================================

DASHBOARD_HTML = open(
    os.path.join(os.path.dirname(__file__), "templates", "dashboard.html")
).read() if os.path.exists(
    os.path.join(os.path.dirname(__file__), "templates", "dashboard.html")
) else "<h1>dashboard.html introuvable</h1>"

@app.route('/')
def dashboard():
    return DASHBOARD_HTML

@app.errorhandler(Exception)
def handle_exception(e):
    print(f"[ERROR] {e}")
    traceback.print_exc()
    return jsonify({"error":"internal_server_error","detail":str(e)}), 500

# ================================================================
#  DÉMARRAGE
# ================================================================

if __name__ == '__main__':
    print("=" * 65)
    print("  AstraWatch — Raspberry Pi FINAL")
    print("  RYDI Group © 2024")
    print("  Base de données : SQLite intégrée")
    print("  SMS : Twilio")
    print("=" * 65)

    # ── Base de données ──
    print("\n[INIT] Base de données SQLite...")
    init_db()

    # ── I2C ──
    print("[INIT] I2C...")
    i2c = None
    try:
        i2c = busio.I2C(board.SCL, board.SDA)
        print("[INIT] I2C OK")
    except Exception as e:
        print(f"[INIT] I2C erreur : {e}")

    # ── ENS160 ──
    print("[INIT] ENS160...")
    try:
        ens160_sensor = ENS160Wrapper(i2c, address=ENS160_ADDR)
    except Exception as e:
        print(f"[ENS160] Non disponible : {e}")

    # ── DHT ──
    print(f"[INIT] {DHT_TYPE} (offset: {DHT_TEMP_OFFSET:+.1f}°C)...")
    try:
        dht_sensor = init_dht(DHT_TYPE, DHT_PIN)
        print(f"[{DHT_TYPE}] OK — offset correction: {DHT_TEMP_OFFSET:+.1f}°C")
        print(f"[{DHT_TYPE}] ⚠️  Si la temp affichée est toujours incorrecte,")
        print(f"[{DHT_TYPE}]    ajuster DHT_TEMP_OFFSET dans ce fichier")
    except Exception as e:
        print(f"[DHT] Non disponible : {e}")

    # ── GPS ──
    print("[INIT] GPS NEO-6M...")
    try:
        gps = GPSReader(port=GPS_PORT, baud=GPS_BAUD)
    except Exception as e:
        print(f"[GPS] Non disponible : {e}")

    # ── Twilio ──
    print("[INIT] Twilio SMS...")
    sms = TwilioSMS()

    # ── Thread capteurs ──
    t = threading.Thread(target=sensor_thread, daemon=True)
    t.start()
    print("[THREAD] Lecture capteurs démarrée (toutes les 3s)")

    # ── IP ──
    import socket
    try:
        rpi_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        rpi_ip = "0.0.0.0"

    print(f"\n{'='*65}")
    print(f"  Dashboard  : http://{rpi_ip}:5000")
    print(f"  API watch  : POST http://{rpi_ip}:5000/api/watch")
    print(f"  DB SQLite  : {DB_PATH}")
    print(f"  SMS        : {'✅ Twilio prêt' if sms and sms.ready else '⚠️  SMS non configuré'}")
    print(f"\n  Pour corriger la température DHT :")
    print(f"  Modifier DHT_TEMP_OFFSET (actuellement {DHT_TEMP_OFFSET:+.1f}°C)")
    print(f"{'='*65}\n")

    app.run(host='0.0.0.0', port=5000, debug=False)
