"""
================================================================
  AstraWatch — Module SMS via Nexah MobileAds
  Remplace SIM800L par l'API HTTP Nexah (sms.nexah.net)
  RYDI Group © 2024

  Usage dans app.py :
    from nexah_sms import NexahSMS
    sms = NexahSMS()
    sms.send_alert(lat, lon, gps_fix)
================================================================
"""

import requests
import time

# ================================================================
#  CONFIGURATION NEXAH — MODIFIEZ ICI
# ================================================================

NEXAH_USER      = "makaebenezer@yahoo.fr"   # ← Votre email Nexah
NEXAH_PASSWORD  = "nexah 2026"              # ← Votre mot de passe Nexah
NEXAH_SENDER_ID = "AstraWatch"             # ← Nom d'expéditeur (max 11 car.)
NEXAH_API_URL   = "https://smsvas.com/bulk/public/index.php/api/v1/sendsms"

# Numéros destinataires (format: 237XXXXXXXXX ou XXXXXXXXX)
SMS_NUMBERS = [
    "237690059681",   # ← Proche 1
    "237656298493",   # ← Proche 2
]

SMS_RISK_THRESHOLD = 3    # Niveau de risque minimum pour déclencher SMS
SMS_COOLDOWN_S     = 120  # 2 minutes entre deux SMS d'alerte


# ================================================================
#  CLASSE NexahSMS
# ================================================================

class NexahSMS:
    """
    Client SMS via l'API REST Nexah MobileAds.
    Remplace entièrement la classe SIM800L de app.py.
    Compatible avec le reste du code AstraWatch sans modification.
    """

    def __init__(self):
        self.ready = True  # Toujours prêt (API HTTP, pas de port série)
        print("[NEXAH] Module SMS Nexah initialisé")
        print(f"[NEXAH] Compte : {NEXAH_USER}")
        print(f"[NEXAH] Sender : {NEXAH_SENDER_ID}")

    # ----------------------------------------------------------
    def send_sms(self, number: str, message: str) -> bool:
        """
        Envoie un SMS via l'API Nexah.
        number  : format 237XXXXXXXXX ou XXXXXXXXX
        message : texte (max 160 car. pour 1 crédit)
        Retourne True si succès, False sinon.
        """
        # Nettoyer le numéro (supprimer espaces et +)
        number = number.strip().lstrip('+')

        payload = {
            "user":     NEXAH_USER,
            "password": NEXAH_PASSWORD,
            "senderid": NEXAH_SENDER_ID,
            "sms":      message,
            "mobiles":  number,
        }

        try:
            print(f"[NEXAH] Envoi SMS → {number}")
            resp = requests.post(
                NEXAH_API_URL,
                json=payload,
                headers={"Accept": "application/json",
                         "Content-Type": "application/json"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            # Vérifier la réponse Nexah
            # responsecode == 1 → succès
            if isinstance(data, list):
                data = data[0]

            code = data.get("responsecode", 0)
            desc = data.get("responsedescription", "")

            if code == 1:
                print(f"[NEXAH] ✅ SMS envoyé → {number} | {desc}")
                return True
            else:
                print(f"[NEXAH] ❌ Échec → {number} | Code:{code} | {desc}")
                return False

        except requests.exceptions.Timeout:
            print(f"[NEXAH] ❌ Timeout — vérifier connexion internet")
            return False
        except requests.exceptions.ConnectionError:
            print(f"[NEXAH] ❌ Connexion impossible à smsvas.com")
            return False
        except Exception as e:
            print(f"[NEXAH] ❌ Erreur : {e}")
            return False

    # ----------------------------------------------------------
    def send_alert(self, lat: float, lon: float, gps_fix: bool):
        """
        SMS d'alerte crise — envoyé aux proches configurés.
        Même signature que SIM800L.send_alert() → drop-in replacement.
        """
        if gps_fix and lat != 0.0 and lon != 0.0:
            gps_str = f"https://maps.google.com/?q={lat:.5f},{lon:.5f}"
        else:
            gps_str = "Position GPS inconnue"

        msg = (
            f"ALERT ALERT\n"
            f"The patient is about to have an asthma attack!\n"
            f"Location: {gps_str}\n"
            f"- AstraWatch"
        )

        # Tronquer à 160 caractères si nécessaire
        if len(msg) > 160:
            msg = msg[:157] + "..."

        for number in SMS_NUMBERS:
            if number and number.strip():
                self.send_sms(number.strip(), msg)
                time.sleep(1)  # Petit délai entre envois

    # ----------------------------------------------------------
    def send_stable(self):
        """
        SMS de stabilisation — envoyé quand le risque redescend.
        Même signature que SIM800L.send_stable() → drop-in replacement.
        """
        msg = (
            "BONNE NOUVELLE\n"
            "La condition du patient s est stabilisee.\n"
            "Il n y a plus de danger immediat.\n"
            "- AstraWatch"
        )
        for number in SMS_NUMBERS:
            if number and number.strip():
                self.send_sms(number.strip(), msg)
                time.sleep(1)

    # ----------------------------------------------------------
    def get_balance(self) -> float | None:
        """
        Vérifie le solde SMS du compte Nexah.
        Retourne le solde ou None en cas d'erreur.
        """
        balance_url = "https://smsvas.com/bulk/public/index.php/api/v1/checkbalance"
        try:
            resp = requests.post(
                balance_url,
                json={"user": NEXAH_USER, "password": NEXAH_PASSWORD},
                headers={"Accept": "application/json",
                         "Content-Type": "application/json"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                data = data[0]
            balance = data.get("balance", None)
            print(f"[NEXAH] Solde : {balance} crédits")
            return float(balance) if balance is not None else None
        except Exception as e:
            print(f"[NEXAH] Erreur solde : {e}")
            return None


# ================================================================
#  TEST RAPIDE (python nexah_sms.py)
# ================================================================

if __name__ == "__main__":
    print("=== TEST NEXAH SMS ===")
    sms = NexahSMS()

    # Vérifier le solde
    sms.get_balance()

    # Envoyer un SMS de test
    ok = sms.send_sms(
        SMS_NUMBERS[0],
        "Test AstraWatch — Nexah SMS OK !"
    )
    print(f"Résultat : {'✅ Succès' if ok else '❌ Échec'}")
