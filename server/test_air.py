import requests
import random
import time

# =========================
# Position GPS fictive
# =========================

GPS_LAT = 4.0511
GPS_LON = 9.7679

# =========================
# Ta clé API
# =========================

API_KEY = "2416d51b55dc9b7a267d008e848363d3"

# =========================
# Simulation capteurs
# =========================

def fake_dht():
    temperature = random.uniform(24, 32)
    humidity = random.uniform(50, 90)
    return round(temperature,1), round(humidity,1)

def fake_ens160():
    tvoc = random.randint(50, 600)
    eco2 = random.randint(400, 1500)
    return tvoc, eco2

# =========================
# API pollution
# =========================

def get_air_quality(lat, lon):

    url = f"https://api.openweathermap.org/data/2.5/air_pollution?lat={lat}&lon={lon}&appid={API_KEY}"

    try:
        r = requests.get(url)
        data = r.json()

        pm25 = data["list"][0]["components"]["pm2_5"]
        pm10 = data["list"][0]["components"]["pm10"]

        return pm25, pm10

    except Exception as e:
        print("Erreur API :", e)
        return None, None

# =========================
# Programme principal
# =========================

print("🚀 Simulation AstraWatch\n")

while True:

    temp, hum = fake_dht()
    tvoc, eco2 = fake_ens160()

    pm25, pm10 = get_air_quality(GPS_LAT, GPS_LON)

    print("------ Données environnement ------")

    print(f"GPS : {GPS_LAT}, {GPS_LON}")
    print(f"Température : {temp} °C")
    print(f"Humidité : {hum} %")

    print(f"TVOC : {tvoc} ppb")
    print(f"eCO2 : {eco2} ppm")

    print(f"PM2.5 : {pm25}")
    print(f"PM10 : {pm10}")

    print("-----------------------------------\n")

    time.sleep(10)
