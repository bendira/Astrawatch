# sim800l_sms.py
# Branchement : VCC→Alim externe 4V, GND→GND commun, TXD→GPIO15, RXD→GPIO14
# Installation : pip install pyserial

import serial
import time

SERIAL_PORT = '/dev/tty'  # ou /dev/ttyS0 selon ta config
BAUD_RATE =9600

def send_at(ser, command, wait=1):
    """Envoie une commande AT et retourne la réponse"""
    ser.write((command + '\r\n').encode())
    time.sleep(wait)
    response = ser.read(ser.inWaiting()).decode(errors='ignore')
    print(f">> {command}")
    print(f"<< {response}")
    return response

def send_sms(numero, message):
    with serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1) as ser:
        time.sleep(2)

        # Vérification module
        rep = send_at(ser, 'AT')
        if 'OK' not in rep:
            print("❌ SIM800L non détecté. Vérifier alimentation et câblage.")
            return False

        # Vérification réseau
        send_at(ser, 'AT+CREG?')       # Enregistrement réseau
        send_at(ser, 'AT+CSQ')          # Qualité du signal (10-31 = bon)
        send_at(ser, 'AT+CMGF=1')       # Mode texte SMS

        # Envoi du SMS
        ser.write(f'AT+CMGS="{numero}"\r\n'.encode())
        time.sleep(1)
        ser.write((message + '\x1A').encode())  # \x1A = Ctrl+Z pour valider
        time.sleep(5)

        response = ser.read(ser.inWaiting()).decode(errors='ignore')
        if '+CMGS' in response:
            print(f"✅ SMS envoyé à {numero}")
            return True
        else:
            print(f"❌ Échec envoi : {response}")
            return False

# --- TEST ---
if __name__ == '__main__':
    send_sms('+237692045943', 'Test SIM800L depuis Raspberry Pi 4 !')
