#!/usr/bin/env python3
import serial
import time
import sys
import json
import os
import unicodedata

CONFIG_FILE = "/home/xavier/config.json"


# ============================================================
#  CONFIG
# ============================================================
def load_config():
    if not os.path.exists(CONFIG_FILE):
        print("Config manquante :", CONFIG_FILE)
        sys.exit(1)
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


# ============================================================
#  NORMALISATION MESSAGE (compat GSM)
# ============================================================
def normalize_message(msg: str) -> str:
    """
    - Remplace les emojis et symboles non GSM par un équivalent texte
    - Supprime les accents
    - Remplace les apostrophes bizarres
    """
    # Remplacements spécifiques
    msg = msg.replace("⚠️", "ALERTE ")
    msg = msg.replace("✅", "OK ")
    msg = msg.replace("❌", "ERREUR ")

    # Apostrophes “intelligentes”
    msg = msg.replace("’", "'")
    msg = msg.replace("`", "'")

    # Normalisation ASCII (supprime accents)
    msg_norm = unicodedata.normalize("NFKD", msg)
    msg_ascii = "".join(c for c in msg_norm if not unicodedata.combining(c))

    # On force ASCII pur
    msg_ascii = msg_ascii.encode("ascii", errors="ignore").decode("ascii", errors="ignore")

    # Nettoyage espaces multiples
    while "  " in msg_ascii:
        msg_ascii = msg_ascii.replace("  ", " ")

    return msg_ascii.strip()


# ============================================================
#  AT UTILITAIRES
# ============================================================
def send_at(ser, cmd, expected="OK", timeout=5):
    """
    Envoie une commande AT et renvoie (ok, reponse_texte).
    """
    ser.reset_input_buffer()
    ser.write((cmd + "\r\n").encode("ascii", errors="ignore"))
    ser.flush()

    t0 = time.time()
    chunks = []
    while True:
        if ser.in_waiting:
            try:
                chunk = ser.read(ser.in_waiting).decode(errors="ignore")
            except Exception:
                chunk = ""
            if chunk:
                chunks.append(chunk)
                if expected in chunk:
                    break
        if time.time() - t0 > timeout:
            break
        time.sleep(0.1)

    resp = "".join(chunks)
    return (expected in resp), resp


def fatal(msg):
    print("ERREUR:", msg)
    sys.exit(1)


# ============================================================
#  MAIN
# ============================================================
if __name__ == "__main__":

    if len(sys.argv) < 2:
        fatal("Usage: python3 send_sms.py 'message'")

    raw_message = sys.argv[1]

    config = load_config()
    serial_port = config.get("serial_port", "/dev/ttyUSB3")
    pin = config.get("sim_pin", "")

    # Multi-numéros : alert_numbers[] prioritaire, sinon sms_phone
    alert_numbers = config.get("alert_numbers", [])
    if isinstance(alert_numbers, str):
        alert_numbers = [alert_numbers]
    alert_numbers = [n.strip() for n in alert_numbers if n and n.strip()]

    if alert_numbers:
        numbers = alert_numbers
    else:
        numbers = [config.get("sms_phone", "+33XXXXXXXXX").strip()]

    # Normalisation du message pour le modem
    norm_message = normalize_message(raw_message)

    print("Numéros cibles :", ", ".join(numbers))
    print("Port série modem :", serial_port)
    print("Message brut   :", raw_message)
    print("Message envoyé :", norm_message)

    try:
        ser = serial.Serial(
            port=serial_port,
            baudrate=115200,
            timeout=5
        )
    except Exception as e:
        fatal(f"Impossible d'ouvrir {serial_port} : {e}")

    try:
        print("Initialisation modem…")
        print("Reset état modem (sortir d'un éventuel mode SMS)...")

        # Petit reset de l'état : simple AT
        ok, resp = send_at(ser, "AT", expected="OK", timeout=5)
        print("Réponse AT :", resp.strip())
        if not ok:
            fatal("Modem ne répond pas correctement à 'AT'.")
        else:
            print("Modem OK après reset.")

        # Vérifier l'état du PIN
        ok, resp = send_at(ser, "AT+CPIN?", expected="OK", timeout=5)
        print("Réponse AT+CPIN? :", resp.strip())

        if "READY" in resp:
            print("SIM déjà prête (READY). Aucun PIN à envoyer.")
        elif "SIM PIN" in resp:
            if not pin:
                fatal("La SIM demande un PIN, mais aucun 'sim_pin' défini dans config.json")
            print(f"Envoi du PIN SIM '{pin}' ...")
            ok, resp_pin = send_at(ser, f'AT+CPIN="{pin}"', expected="OK", timeout=10)
            print('Réponse AT+CPIN="xxxx" :', resp_pin.strip())
            if not ok:
                fatal("PIN incorrect ou refusé : " + resp_pin)
            time.sleep(3)
        else:
            print("État SIM non reconnu, on poursuit quand même…")

        # Mode texte + jeu de caractères SMS basique
        ok, resp = send_at(ser, "AT+CMGF=1", expected="OK", timeout=5)
        print("Réponse AT+CMGF=1 :", resp.strip())
        if not ok:
            fatal("Impossible de passer en mode texte SMS.")

        ok, resp = send_at(ser, 'AT+CSCS="GSM"', expected="OK", timeout=5)
        print('Réponse AT+CSCS="GSM" :', resp.strip())
        if not ok:
            print("Avertissement : Impossible de fixer CSCS=\"GSM\" (on continue quand même).")

        # Envoi du SMS à chaque numéro
        for phone in numbers:
            print(f"Envoi SMS vers {phone} ...")

            ok, resp = send_at(ser, f'AT+CMGS="{phone}"', expected=">", timeout=5)
            print(f'Response AT+CMGS="{phone}" :', resp.strip())
            if not ok:
                fatal("Erreur entrée mode SMS pour " + phone + " : " + resp)

            # Envoi du message + CTRL+Z
            ser.write((norm_message + chr(26)).encode("ascii", errors="ignore"))
            ser.flush()

            # Lecture robuste de la réponse (évite les crash OSError)
            chunks = []
            start = time.time()
            try:
                while True:
                    try:
                        chunk = ser.read(256).decode(errors="ignore")
                    except OSError as e:
                        print("Erreur lors de la lecture de la réponse (probable reset USB) :", e)
                        break

                    if chunk:
                        chunks.append(chunk)
                        # On arrête si OK ou erreur CMS détectée
                        if "OK" in chunk or "+CMS ERROR" in chunk:
                            break

                    if time.time() - start > 20:
                        break
            except Exception as e:
                print("Exception pendant la lecture de la réponse :", e)

            resp_send = "".join(chunks)
            print("Réponse envoi :", resp_send.strip())

            if "+CMS ERROR" in resp_send:
                fatal(f"Échec envoi SMS pour {phone}: {resp_send}")
            else:
                print(f"SMS envoyé (ou en cours) vers {phone} : {norm_message}")

    finally:
        try:
            ser.close()
        except Exception:
            pass
