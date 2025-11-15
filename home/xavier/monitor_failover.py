#!/usr/bin/env python3
# ============================================================================
#  Failover-Pi : Surveillance Freebox <-> 4G SIM7600E
#
#  - Surveille l'accès Internet via la Freebox (LAN + ping 8.8.8.8 via Freebox)
#  - Surveille l'accès Internet via la 4G (ping 8.8.8.8 via wwan0)
#  - Lance /home/xavier/connect_4g.sh en cas de perte Freebox
#  - Envoie des SMS via /home/xavier/send_sms.py
#  - Gère les messages :
#       ⚠️ La Freebox n’a plus d'accès à Internet.
#       ✅ La connexion Internet Freebox est rétablie.
#       📡 Connexion 4G établie (failover).
#       📵 La connexion 4G (SIM7600E) est perdue.
#       ❌ Aucune connexion disponible (ni Freebox, ni 4G).
#       Le Raspberry Pi Failover vient de redemarrer.
# ============================================================================

import os
import json
import time
import subprocess
from datetime import datetime


CONFIG_FILE = "/home/xavier/config.json"
LOG_FILE = "/home/xavier/monitor.log"
SMS_SCRIPT = "/home/xavier/send_sms.py"
CONNECT_4G_SCRIPT = "/home/xavier/connect_4g.sh"

# Intervalle entre deux checks (en secondes)
CHECK_INTERVAL = 60

# Délai minimal entre deux tentatives d'activation 4G (en secondes)
MIN_4G_RETRY_DELAY = 90


# ----------------------------------------------------------------------------
# Helpers log
# ----------------------------------------------------------------------------
def ts():
    """Horodatage type [dd/mm/YYYY HH:MM:SS]."""
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


def log(msg: str):
    """Écrit dans monitor.log + stdout."""
    line = f"[{ts()}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
def load_config(path: str):
    cfg = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        pass
    # Valeurs par défaut
    cfg.setdefault("gateway", "192.168.0.254")
    cfg.setdefault("apn", "free")
    return cfg


# ----------------------------------------------------------------------------
# Commandes & ping
# ----------------------------------------------------------------------------
def run_cmd(cmd: str, timeout: int = 10):
    """
    Exécute une commande shell, retourne (rc, stdout, stderr)
    """
    try:
        res = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except subprocess.TimeoutExpired:
        return 1, "", f"Timeout ({timeout}s)"
    except Exception as e:
        return 1, "", str(e)


def ping(host: str, iface: str | None = None, count: int = 1, timeout: int = 2) -> bool:
    """
    Ping simple, True si OK.
    On ignore la sortie, seul le code retour compte.
    """
    if iface:
        cmd = f"ping -I {iface} -c {count} -W {timeout} {host}"
    else:
        cmd = f"ping -c {count} -W {timeout} {host}"

    rc, _, _ = run_cmd(cmd, timeout=timeout + 1)
    return rc == 0


# ----------------------------------------------------------------------------
# SMS
# ----------------------------------------------------------------------------
def send_sms(message: str):
    """
    Envoie un SMS via send_sms.py.
    """
    log(f"[SMS] Préparation envoi : {message}")
    try:
        res = subprocess.run(
            ["python3", SMS_SCRIPT, message],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if res.returncode == 0:
            log(f"[SMS] OK : {res.stdout.strip()}")
        else:
            log(
                f"[SMS] ERREUR (code={res.returncode}) : {res.stdout.strip()}\n{res.stderr.strip()}"
            )
    except subprocess.TimeoutExpired:
        log("[SMS] ERREUR : Timeout lors de l'envoi du SMS.")
    except Exception as e:
        log(f"[SMS] Exception lors de l'envoi du SMS : {e}")


# ----------------------------------------------------------------------------
# État des connexions
# ----------------------------------------------------------------------------
def check_status(gateway: str):
    """
    Vérifie :
      - Freebox LAN (ping gateway via eth0)
      - Freebox Internet (ping 8.8.8.8 via eth0 si LAN OK)
      - 4G Internet (ping 8.8.8.8 via wwan0)
    Retourne (freebox_lan_ok, freebox_inet_ok, fourg_inet_ok)
    """
    # Freebox LAN
    freebox_lan_ok = ping(gateway, iface="eth0", count=1, timeout=1)

    # Freebox Internet
    if freebox_lan_ok:
        freebox_inet_ok = ping("8.8.8.8", iface="eth0", count=2, timeout=2)
    else:
        freebox_inet_ok = False

    # 4G Internet
    fourg_inet_ok = ping("8.8.8.8", iface="wwan0", count=2, timeout=2)

    return freebox_lan_ok, freebox_inet_ok, fourg_inet_ok


# ----------------------------------------------------------------------------
# Gestion des routes / interfaces
# ----------------------------------------------------------------------------
def set_freebox_primary(gateway: str):
    """
    Rebasculer la route principale sur la Freebox (eth0),
    remonter le Wi-Fi si besoin, supprimer default wwan0.
    """
    # Remonte le Wi-Fi (au cas où on l'a down pendant le failover)
    rc, out, err = run_cmd("sudo ip link set wlan0 up", timeout=5)
    log(f"[NET] ip link set wlan0 up (rc={rc}) {err}")

    # Route par défaut : Freebox
    rc, out, err = run_cmd(
        f"sudo ip route replace default via {gateway} dev eth0 metric 100", timeout=5
    )
    log(f"[NET] ip route replace default via {gateway} dev eth0 metric 100 (rc={rc}) {err}")

    # Supprimer default via wwan0
    rc, out, err = run_cmd("sudo ip route del default dev wwan0", timeout=5)
    if rc != 0 and "No such process" not in err and "Cannot find device" not in err:
        log(f"[NET] ip route del default dev wwan0 (rc={rc}) {err}")


def prepare_failover_4g():
    """
    Actions réseau lors de l'activation du failover 4G :
      - couper wlan0 (éviter routes par défaut parasites)
      - laisser connect_4g.sh gérer la route default wwan0.
    """
    rc, out, err = run_cmd("sudo ip link set wlan0 down", timeout=5)
    log(f"[NET] ip link set wlan0 down (rc={rc}) {err}")


# ----------------------------------------------------------------------------
# Lancement du script 4G
# ----------------------------------------------------------------------------
def try_start_4g():
    """
    Lance /home/xavier/connect_4g.sh et retourne True si rc == 0.
    """
    log("[4G] Lancement du script de connexion 4G...")
    try:
        res = subprocess.run(
            ["sudo", CONNECT_4G_SCRIPT],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if res.returncode == 0:
            log("[4G] Connexion 4G active (ping OK).")
            log(f"[4G] Script connect_4g.sh terminé (rc={res.returncode}).")
            return True
        else:
            log("[4G] ERREUR : échec du démarrage réseau 4G")
            log(f"[4G] Résultat connect_4g.sh (rc={res.returncode}) :\n{res.stdout}\n{res.stderr}")
            return False
    except subprocess.TimeoutExpired:
        log("[4G] ERREUR : Timeout lors du script connect_4g.sh")
        return False
    except Exception as e:
        log(f"[4G] Exception lors du script connect_4g.sh : {e}")
        return False


# ----------------------------------------------------------------------------
# Boucle principale
# ----------------------------------------------------------------------------
def main():
    cfg = load_config(CONFIG_FILE)
    gateway = cfg.get("gateway", "192.168.0.254")

    log("=== MONITOR FAILOVER DÉMARRÉ ===")

    # SMS au démarrage du monitor (Raspberry reboot / service relancé)
    send_sms("Le Raspberry Pi Failover vient de redemarrer.")

    prev_freebox_inet = None
    prev_any_conn = None
    prev_4g_inet = None

    last_4g_attempt = 0.0

    while True:
        freebox_lan_ok, freebox_inet_ok, fourg_inet_ok = check_status(gateway)

        # Status global
        status_line = (
            f"[STATUS] Freebox LAN={'OK' if freebox_lan_ok else 'KO'} "
            f"Internet={'OK' if freebox_inet_ok else 'KO'} / "
            f"4G={'OK' if fourg_inet_ok else 'KO'}"
        )
        log(status_line)

        any_conn = freebox_inet_ok or fourg_inet_ok

        # --------------------------------------------------------------------
        # Gestion des transitions Freebox Internet
        # --------------------------------------------------------------------
        if prev_freebox_inet is None:
            prev_freebox_inet = freebox_inet_ok
        else:
            if prev_freebox_inet and not freebox_inet_ok:
                # Perte Internet Freebox
                log("Perte de connexion Internet Freebox")
                send_sms("⚠️ La Freebox n’a plus d'accès à Internet.")

            elif not prev_freebox_inet and freebox_inet_ok:
                # Retour Internet Freebox
                log("Connexion Internet Freebox rétablie")
                send_sms("✅ La connexion Internet Freebox est rétablie.")
                # Rebasculer la route sur la Freebox
                set_freebox_primary(gateway)

            prev_freebox_inet = freebox_inet_ok

        # --------------------------------------------------------------------
        # Gestion des transitions 4G
        # --------------------------------------------------------------------
        if prev_4g_inet is None:
            prev_4g_inet = fourg_inet_ok
        else:
            if not prev_4g_inet and fourg_inet_ok and not freebox_inet_ok:
                # 4G vient de devenir OK alors que Freebox KO -> failover
                log("Failover 4G actif (bascule sur 4G)")
                prepare_failover_4g()
                send_sms("📡 Connexion 4G établie (failover).")

            elif prev_4g_inet and not fourg_inet_ok:
                # 4G vient de tomber
                log("Connexion 4G (wwan0) perdue")
                send_sms("📵 La connexion 4G (SIM7600E) est perdue.")

            prev_4g_inet = fourg_inet_ok

        # --------------------------------------------------------------------
        # Gestion "aucune connexion"
        # --------------------------------------------------------------------
        if prev_any_conn is None:
            prev_any_conn = any_conn
        else:
            if prev_any_conn and not any_conn:
                # On vient de passer d'un état "quelque chose fonctionne" à "plus rien"
                log("Aucune connexion disponible (Freebox + 4G KO)")
                send_sms("❌ Aucune connexion disponible (ni Freebox, ni 4G).")
            prev_any_conn = any_conn

        # --------------------------------------------------------------------
        # Tentative d'activation 4G si Freebox HS et 4G HS
        # --------------------------------------------------------------------
        if not freebox_inet_ok and not fourg_inet_ok:
            now = time.time()
            if now - last_4g_attempt >= MIN_4G_RETRY_DELAY:
                log("[4G] Tentative d'activation de la connexion 4G (Freebox KO, 4G KO).")
                last_4g_attempt = now
                # Lance le script 4G
                ok_4g = try_start_4g()
                if not ok_4g:
                    log("[4G] Nouvelle tentative échouée, on réessaiera plus tard.")
            else:
                remaining = int(MIN_4G_RETRY_DELAY - (now - last_4g_attempt))
                log(
                    f"[4G] Dernier essai trop récent, on attend encore {remaining}s avant de relancer."
                )

        # --------------------------------------------------------------------
        # Pause avant le prochain cycle
        # --------------------------------------------------------------------
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
