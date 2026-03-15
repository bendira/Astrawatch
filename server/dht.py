# dht_sensor.py
# Branchement :
# VCC → 3.3V ou 5V
# GND → GND
# DATA → GPIO4
# résistance pull-up 10kΩ entre DATA et VCC

import adafruit_dht
import board
import time

# =========================
# CONFIGURATION
# =========================

TYPE_DHT = "DHT11"     # changer ici : "DHT11" ou "DHT22"
BROCHE_DHT = board.D17  # GPIO17

# =========================
# Initialisation capteur
# =========================

def init_capteur():

    if TYPE_DHT == "DHT22":
        print("🔧 Initialisation DHT22")
        return adafruit_dht.DHT22(BROCHE_DHT)

    elif TYPE_DHT == "DHT11":
        print("🔧 Initialisation DHT11")
        return adafruit_dht.DHT11(BROCHE_DHT)

    else:
        raise ValueError("Type de capteur inconnu")

# =========================
# Lecture capteur
# =========================

def lire_dht(nb_essais=5):

    capteur = init_capteur()

    for essai in range(nb_essais):

        try:
            temperature = capteur.temperature
            humidite = capteur.humidity

            if temperature is not None and humidite is not None:

                print(f"✅ {TYPE_DHT} :")
                print(f"   Température : {temperature:.1f} °C")
                print(f"   Humidité    : {humidite:.1f} %")
                print(f"   Indice chaleur : {calcul_ic(temperature, humidite):.1f} °C")

                capteur.exit()

                return {
                    "temperature": temperature,
                    "humidite": humidite
                }

        except RuntimeError as e:

            print(f"Essai {essai+1}/{nb_essais} échoué : {e}")
            time.sleep(2.5)

    capteur.exit()
    print("❌ Impossible de lire le capteur")

    return None

# =========================
# Calcul Heat Index
# =========================

def calcul_ic(temp, hum):

    if temp < 27 or hum < 40:
        return temp

    ic = (-8.78469475556 + 1.61139411 * temp + 2.33854883889 * hum
          - 0.14611605 * temp * hum - 0.012308094 * temp**2
          - 0.0164248277778 * hum**2 + 0.002211732 * temp**2 * hum
          + 0.00072546 * temp * hum**2 - 0.000003582 * temp**2 * hum**2)

    return ic

# =========================
# Lecture continue
# =========================

def lecture_continue(intervalle=10):

    print(f"\n📊 Lecture continue {TYPE_DHT}\n")

    while True:
        lire_dht()
        print()
        time.sleep(intervalle)

# =========================
# TEST
# =========================

if __name__ == "__main__":

    lire_dht()

    # pour lecture continue
    # lecture_continue(10)
