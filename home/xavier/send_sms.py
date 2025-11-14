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


def get_recipients(cfg: dict):
    """
    Renvoie la liste des numéros à notifier.
    Priorité :
      1) cfg["sms_recipients"] si liste non vide
      2) sinon cfg["sms_phone"] si défini
    """
    recips = cfg.get("sms_recipients")
    if isinstance(recips, list) and recips:
        cleaned = []
        for r in recips:
            r = str(r).strip()
            if r:
                cleaned.append(r)
        if cleaned:
            return cleaned

    phone = (cfg.get("sms_phone") or "").strip()
    if phone:
        return [phone]

    return []


if __name__ == "__main__":

    if len(sys.argv) < 2:
        fatal("Usage: python3 send_sms.py 'message'")

    message = sys.argv[1]
    config = load_config()

    serial_port = config.get("serial_port", "/dev/ttyUSB3")
    pin = config.get("sim_pin", "")

    recipients = get_recipients(config)
    if not recipients:
        fatal("Aucun numéro SMS configuré (sms_recipients / sms_phone).")

    print("Numéros cibles :", ", ".join(recipients))

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

        # Envoi pour chaque destinataire
        for phone in recipients:
            print(f"Envoi SMS vers {phone}…")
            ok, resp = send_at(ser, f'AT+CMGS="{phone}"', expected=">")
            if not ok:
                print("Erreur entrée mode SMS pour", phone, ":", resp)
                continue

            # Envoi message + CTRL+Z
            ser.write((message + chr(26)).encode())
            time.sleep(4)
            resp = ser.read_all().decode(errors="ignore")

            if "OK" in resp:
                print("SMS envoyé à", phone)
            else:
                print("Réponse modem pour", phone, ":", resp)
                print("Échec envoi SMS pour", phone)

    finally:
        ser.close()
