# neo6m_gps.py
# Branchement :
#   VCC → 3.3V (broche 1)
#   GND → GND  (broche 6)
#   TX  → GPIO15 / RXD (broche 10)
#   RX  → GPIO14 / TXD (broche 8) ← optionnel
#
# Installation :
#   pip install pyserial pynmea2 --break-system-packages
#
# Activer UART :
#   sudo raspi-config → Interface Options → Serial Port
#   → Login shell : NON  /  Hardware serial : OUI
#   sudo reboot

import serial
import pynmea2
import time
from datetime import datetime

GPS_PORT = '/dev/serial0'
GPS_BAUD = 9600

# ─────────────────────────────────────────
#  Lecture unique
# ─────────────────────────────────────────
def lire_position(timeout=60):
    """
    Attend un fix GPS et retourne la position.
    timeout : secondes max à attendre
    """
    print(f"🛰️  NEO-6M — Recherche de satellites...")
    print(f"   (Placer le module près d'une fenêtre ou à l'extérieur)\n")

    satellites = 0

    with serial.Serial(GPS_PORT, GPS_BAUD, timeout=1) as ser:
        debut = time.time()

        while time.time() - debut < timeout:
            try:
                ligne = ser.readline().decode('ascii', errors='ignore').strip()

                # ── Nombre de satellites (trame GGA) ──
                if ligne.startswith('$GPGGA'):
                    try:
                        msg = pynmea2.parse(ligne)
                        satellites = int(msg.num_sats or 0)
                        altitude   = msg.altitude
                        unite_alt  = msg.altitude_units

                        if msg.gps_qual > 0:
                            print(f"   📡 Satellites : {satellites} | "
                                  f"Altitude : {altitude} {unite_alt}")
                    except pynmea2.ParseError:
                        pass

                # ── Position + vitesse + cap (trame RMC) ──
                elif ligne.startswith('$GPRMC'):
                    try:
                        msg = pynmea2.parse(ligne)

                        if msg.status == 'A':  # A = fix valide
                            vitesse_kmh = float(msg.spd_over_grnd or 0) * 1.852
                            cap         = float(msg.true_course or 0)

                            print(f"\n✅ Fix GPS obtenu !")
                            print(f"   Latitude   : {msg.latitude:.6f}° {msg.lat_dir}")
                            print(f"   Longitude  : {msg.longitude:.6f}° {msg.lon_dir}")
                            print(f"   Vitesse    : {vitesse_kmh:.1f} km/h")
                            print(f"   Cap        : {cap:.1f}°")
                            print(f"   Satellites : {satellites}")
                            print(f"   Heure UTC  : {msg.timestamp}")
                            print(f"   Date       : {msg.datestamp}")

                            return {
                                'latitude'  : msg.latitude,
                                'lat_dir'   : msg.lat_dir,
                                'longitude' : msg.longitude,
                                'lon_dir'   : msg.lon_dir,
                                'vitesse_kmh': vitesse_kmh,
                                'cap'       : cap,
                                'satellites': satellites,
                                'heure_utc' : str(msg.timestamp),
                                'date'      : str(msg.datestamp),
                            }
                        else:
                            elapsed = int(time.time() - debut)
                            print(f"   ⏳ Pas de fix ({elapsed}s) — "
                                  f"Satellites : {satellites}", end='\r')

                    except pynmea2.ParseError:
                        pass

            except UnicodeDecodeError:
                pass
            except Exception as e:
                print(f"\n   ⚠️  Erreur : {e}")

    print(f"\n❌ Timeout {timeout}s — aucun fix obtenu.")
    print("   → Vérifier position du module (extérieur recommandé)")
    print("   → Vérifier branchement TX/RX")
    return None


# ─────────────────────────────────────────
#  Lecture continue
# ─────────────────────────────────────────
def lecture_continue(intervalle=5):
    """
    Affiche la position en continu.
    intervalle : secondes entre chaque affichage
    """
    print("📊 Lecture continue NEO-6M (Ctrl+C pour arrêter)\n")

    with serial.Serial(GPS_PORT, GPS_BAUD, timeout=1) as ser:
        derniere_pos = None
        dernier_affichage = 0

        while True:
            try:
                ligne = ser.readline().decode('ascii', errors='ignore').strip()

                if ligne.startswith('$GPRMC'):
                    msg = pynmea2.parse(ligne)

                    if msg.status == 'A':
                        vitesse_kmh = float(msg.spd_over_grnd or 0) * 1.852
                        derniere_pos = {
                            'lat' : msg.latitude,
                            'lon' : msg.longitude,
                            'kmh' : vitesse_kmh,
                        }

                if derniere_pos and time.time() - dernier_affichage >= intervalle:
                    now = datetime.now().strftime('%H:%M:%S')
                    print(f"[{now}] 📍 {derniere_pos['lat']:.6f}, "
                          f"{derniere_pos['lon']:.6f} | "
                          f"🚗 {derniere_pos['kmh']:.1f} km/h")
                    dernier_affichage = time.time()

            except pynmea2.ParseError:
                pass
            except KeyboardInterrupt:
                print("\n🛑 Arrêt.")
                break


# ─────────────────────────────────────────
#  Lien Google Maps
# ─────────────────────────────────────────
def lien_maps(position):
    """Génère un lien Google Maps cliquable"""
    if not position:
        return None
    lat = position['latitude']
    lon = position['longitude']
    lien = f"https://www.google.com/maps?q={lat},{lon}"
    print(f"\n🗺️  Google Maps : {lien}")
    return lien


# ─────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────
if __name__ == '__main__':
    print("=" * 45)
    print("       NEO-6M GPS — Raspberry Pi 4")
    print("=" * 45 + "\n")

    # 1 — Lecture unique avec lien Maps
    pos = lire_position(timeout=120)
    if pos:
        lien_maps(pos)

    # 2 — Lecture continue (décommenter pour activer)
    # lecture_continue(intervalle=5)
