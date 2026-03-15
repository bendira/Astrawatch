# ens160.py
# Branchement I2C :
#   VCC  → 3.3V (broche 17)
#   GND  → GND  (broche 20)
#   SDA  → GPIO2 / SDA (broche 3)
#   SCL  → GPIO3 / SCL (broche 5)
#   ADDR → GND (adresse 0x52) ou 3.3V (adresse 0x53)
# Installation : pip install adafruit-circuitpython-ens160
# Activer I2C : sudo raspi-config → Interface Options → I2C → OUI

import board
import busio
import adafruit_ens160
import time

# Initialisation I2C
i2c = busio.I2C(board.SCL, board.SDA)

def init_ens160():
    """Initialise le capteur ENS160"""
    try:
        capteur = adafruit_ens160.ENS160(i2c)
        print("✅ ENS160 détecté")
        print("   ⏳ Préchauffage en cours (3 minutes pour données stables)...")
        return capteur
    except Exception as e:
        print(f"❌ ENS160 non détecté : {e}")
        print("   Vérifier câblage I2C et adresse (0x52 ou 0x53)")
        return None

def lire_ens160(capteur):
    """Lecture de la qualité d'air"""
    statuts = {
        0: "🔄 Sans objet",
        1: "🔄 Préchauffage en cours",
        2: "⚡ Démarrage initial",
        3: "✅ Données valides"
    }

    data_mode = capteur.data_validity
    print(f"\n🌬️  ENS160 - Qualité de l'air :")
    print(f"   Statut          : {statuts.get(data_mode, 'Inconnu')}")
    print(f"   AQI (1-5)       : {capteur.AQI}  (1=Excellent, 5=Dangereux)")
    print(f"   eCO2            : {capteur.eCO2} ppm")
    print(f"   TVOC            : {capteur.TVOC} ppb")

    # Interprétation AQI
    aqi = capteur.AQI
    if aqi == 1:   qualite = "🟢 Excellente"
    elif aqi == 2: qualite = "🟡 Bonne"
    elif aqi == 3: qualite = "🟠 Modérée"
    elif aqi == 4: qualite = "🔴 Mauvaise"
    else:           qualite = "🟣 Dangereuse"
    print(f"   Qualité air     : {qualite}")

    # Interprétation eCO2
    co2 = capteur.eCO2
    if co2 < 600:       co2_niveau = "Normal (extérieur)"
    elif co2 < 1000:    co2_niveau = "Acceptable (intérieur)"
    elif co2 < 1500:    co2_niveau = "⚠️  Élevé - Ventiler"
    else:               co2_niveau = "🚨 Très élevé - Danger"
    print(f"   Niveau CO2      : {co2_niveau}")

    return {'aqi': aqi, 'eco2': co2, 'tvoc': capteur.TVOC}

def lecture_continue(intervalle=5):
    capteur = init_ens160()
    if not capteur:
        return
    print(f"\n📊 Lecture continue ENS160 (Ctrl+C pour arrêter)")
    while True:
        lire_ens160(capteur)
        time.sleep(intervalle)

# --- TEST ---
if __name__ == '__main__':
    capteur = init_ens160()
    if capteur:
        time.sleep(2)
        lire_ens160(capteur)
        # Pour continu : lecture_continue()
