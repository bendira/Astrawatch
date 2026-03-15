"""
================================================================
  AstraWatch — Module SMS via Twilio
  RYDI Group © 2024

  Drop-in replacement pour SIM800L et NexahSMS.
  Même interface : send_alert(), send_stable(), send_sms()

  AVANT DE LANCER :
    pip install twilio --break-system-packages

  Remplir les 4 variables TWILIO_* ci-dessous avec vos
  identifiants depuis https://console.twilio.com

  Test rapide :
    python twilio_sms.py
================================================================
"""

import time
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

# ================================================================
#  CONFIGURATION TWILIO — REMPLIR ICI
# ================================================================

TWILIO_ACCOUNT_SID  = "AC90bb83049a220ed414a411f46e0450b7"  # ← Account SID
TWILIO_AUTH_TOKEN   = "8ddf1b70f21df9a81390b7d82a3f270e"    # ← Auth Token
TWILIO_FROM_NUMBER  = "+19789042639"                       # ← Votre numéro Twilio (format E.164)

# Numéros destinataires (format international E.164 obligatoire)
SMS_NUMBERS = [
"+237656298493",   # ← Proche 1
    "+237656298493",   # ← Proche 2
]

SMS_RISK_THRESHOLD = 3    # Niveau de risque minimum pour déclencher SMS
SMS_COOLDOWN_S     = 120  # 2 minutes entre deux SMS d'alerte


# ================================================================
#  CLASSE TwilioSMS
# ================================================================

class TwilioSMS:
    """
    Client SMS via l'API Twilio Programmable Messaging.
    Interface identique à SIM800L et NexahSMS pour compatibilité
    totale avec le reste du code AstraWatch.
    """

    def __init__(self):
        self.ready = False
        try:
            self.client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
            # Vérification rapide des credentials
            account = self.client.api.accounts(TWILIO_ACCOUNT_SID).fetch()
            self.ready = True
            print(f"[TWILIO] ✅ Connecté — Compte : {account.friendly_name}")
            print(f"[TWILIO] Expéditeur : {TWILIO_FROM_NUMBER}")
        except TwilioRestException as e:
            print(f"[TWILIO] ❌ Erreur authentification : {e}")
            print("[TWILIO] Vérifier ACCOUNT_SID et AUTH_TOKEN sur console.twilio.com")
        except Exception as e:
            print(f"[TWILIO] ❌ Erreur initialisation : {e}")

    # ----------------------------------------------------------
    def send_sms(self, number: str, message: str) -> bool:
        """
        Envoie un SMS via Twilio.
        number  : format E.164 (+237XXXXXXXXX)
        message : texte (160 car. = 1 crédit, au-delà = segments)
        Retourne True si succès, False sinon.
        """
        if not self.ready:
            print(f"[TWILIO] Client non initialisé — SMS annulé vers {number}")
            return False

        # S'assurer que le numéro est bien en format E.164
        number = number.strip()
        if not number.startswith('+'):
            number = '+' + number

        try:
            print(f"[TWILIO] Envoi SMS → {number}")
            msg = self.client.messages.create(
                body=message,
                from_=TWILIO_FROM_NUMBER,
                to=number,
            )
            print(f"[TWILIO] ✅ SMS envoyé → {number} | SID: {msg.sid} | Statut: {msg.status}")
            return True

        except TwilioRestException as e:
            print(f"[TWILIO] ❌ Erreur Twilio → {number} | Code: {e.code} | {e.msg}")
            # Codes d'erreur courants :
            # 21211 : numéro invalide
            # 21608 : numéro non vérifié (compte trial)
            # 21614 : numéro non SMS
            # 20003 : authentification incorrecte
            return False
        except Exception as e:
            print(f"[TWILIO] ❌ Erreur inattendue : {e}")
            return False

    # ----------------------------------------------------------
    def send_alert(self, lat: float, lon: float, gps_fix: bool):
        """
        SMS d'alerte crise — envoyé aux proches configurés.
        Même signature que SIM800L.send_alert() → compatibilité totale.
        """
        if not self.ready:
            return

        if gps_fix and lat != 0.0 and lon != 0.0:
            gps_str = f"https://maps.google.com/?q={lat:.5f},{lon:.5f}"
        else:
            gps_str = "Position GPS inconnue"

        message = (
            f"ALERT ALERT\n"
            f"The patient is about to have an asthma attack!\n"
            f"Location: {gps_str}\n"
            f"- AstraWatch"
        )

        # Twilio supporte jusqu'à 1600 car (segments multiples)
        # mais on reste sous 160 pour 1 seul crédit SMS
        if len(message) > 160:
            message = message[:157] + "..."

        for number in SMS_NUMBERS:
            if number and number.strip():
                self.send_sms(number.strip(), message)
                time.sleep(1)

    # ----------------------------------------------------------
    def send_stable(self):
        """
        SMS de stabilisation — envoyé quand le risque redescend.
        Même signature que SIM800L.send_stable() → compatibilité totale.
        """
        if not self.ready:
            return

        message = (
            "BONNE NOUVELLE\n"
            "La condition du patient s est stabilisee.\n"
            "Il n y a plus de danger immediat.\n"
            "- AstraWatch"
        )

        for number in SMS_NUMBERS:
            if number and number.strip():
                self.send_sms(number.strip(), message)
                time.sleep(1)

    # ----------------------------------------------------------
    def check_balance(self):
        """
        Affiche les infos du compte Twilio (solde non disponible
        via API REST — consulter console.twilio.com/billing).
        """
        if not self.ready:
            return
        try:
            account = self.client.api.accounts(TWILIO_ACCOUNT_SID).fetch()
            print(f"[TWILIO] Compte     : {account.friendly_name}")
            print(f"[TWILIO] Statut     : {account.status}")
            print(f"[TWILIO] Type       : {account.type}")
            print(f"[TWILIO] Solde SMS  : voir https://console.twilio.com/billing")
        except Exception as e:
            print(f"[TWILIO] Erreur infos compte : {e}")


# ================================================================
#  TEST RAPIDE  (python twilio_sms.py)
# ================================================================

if __name__ == "__main__":
    print("=" * 50)
    print("  TEST AstraWatch — Twilio SMS")
    print("=" * 50)

    sms = TwilioSMS()

    if sms.ready:
        sms.check_balance()

        # Test envoi SMS simple
        numero_test = SMS_NUMBERS[0]
        print(f"\nEnvoi d'un SMS de test vers {numero_test}...")
        ok = sms.send_sms(numero_test, "Test AstraWatch — Twilio OK !")
        print(f"Résultat : {'✅ Succès' if ok else '❌ Échec'}")

        # Test alerte
        print("\nTest alerte crise (GPS Douala)...")
        sms.send_alert(lat=3.8667, lon=11.5167, gps_fix=True)
    else:
        print("\n❌ Twilio non initialisé.")
        print("Vérifier les credentials dans twilio_sms.py")
        print("Console : https://console.twilio.com")
