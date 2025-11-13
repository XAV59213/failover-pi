#!/usr/bin/env python3
import serial
import time
import sys
import json
import os

CONFIG_FILE = "/home/xavier/config.json"


def load_config():
    if not os.path.exists(CONFIG_FILE):
        print("Config manquante :", CONFIG_FILE)
        sys.exit(1)
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


def send_at(ser, cmd, expected="OK", timeout=5):
    """Envoie une commande AT et vérifie la réponse."""
    ser.write((cmd + "\r\n").encode())
    ser.flush()
    time.sleep(timeout)
    resp = ser.read_all().decode(errors="ignore")
    return expected in resp, resp


def fatal(msg):
    print("ERREUR:", msg)
    sys.exit(1)


if __name__ == "__main__":

    if len(sys.argv) < 2:
        fatal("Usage: python3 send_sms.py 'message'")

    message = sys.argv[1]
    config = load_config()

    phone = config.get("sms_phone", "+33XXXXXXXXX")
    serial_port = config.get("serial_port", "/dev/ttyUSB3")
    pin = config.get("sim_pin", "")

    try:
        ser = serial.Serial(
            port=serial_port,
            baudrate=115200,
            timeout=5
        )
    except Exception as e:
        fatal(f"Impossible d'ouvrir {serial_port} : {e}")

    print("Initialisation modem…")

    try:
        # Test modem
        ok, resp = send_at(ser, "AT")
        if not ok:
            fatal("Modem ne répond pas : " + resp)

        # PIN si nécessaire
        if pin:
            ok, resp = send_at(ser, f'AT+CPIN="{pin}"')
            if not ok:
                fatal("PIN incorrect : " + resp)
            time.sleep(3)

        # Mode texte SMS
        send_at(ser, "AT+CMGF=1")

        # Préparation SMS
        ok, resp = send_at(ser, f'AT+CMGS="{phone}"', expected=">")
        if not ok:
            fatal("Erreur entrée mode SMS : " + resp)

        # Envoi message + CTRL+Z
        ser.write((message + chr(26)).encode())
        time.sleep(4)
        resp = ser.read_all().decode(errors="ignore")

        if "OK" in resp:
            print("SMS envoyé :", message)
        else:
            print("Réponse modem :", resp)
            fatal("Échec envoi SMS")

    finally:
        ser.close()
