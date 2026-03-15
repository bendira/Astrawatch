from twilio.rest import Client

# Informations Twilio
account_sid = "TWILIO_SID"
auth_token = "TWILIO_TOKEN"

# Numéro Twilio
twilio_number = "+19789042639"

# Création du client
client = Client(account_sid, auth_token)

# Fonction pour envoyer un SMS
def send_sms():
    message = client.messages.create(
        body="Alert crisis  ",
        from_=twilio_number,
        to="+237656298493"
    )

    print("SMS envoyé !")
    print("SID :", message.sid)

# Exécution
send_sms()
