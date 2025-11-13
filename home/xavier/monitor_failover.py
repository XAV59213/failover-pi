#!/usr/bin/env python3
import subprocess
import time
import json
import os
from datetime import datetime

LOG_FILE = "/home/xavier/monitor.log"
CONFIG_FILE = "/home/xavier/config.json"
CONNECT_4G = "/home/xavier/connect_4g.sh"
SMS_SCRIPT = "/home/xavier/send_sms.py"
HISTORY_FILE = "/home/xavier/status_history.json"
GATEWAY = "192.168.0.254"  # Freebox par défaut


# ----------------------------------------------------------------------
# Utilitaires
# ----------------------------------------------------------------------
def log(msg):
    entry = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    try:
        with open(LOG_FILE, "a") as f:
            f.write(entry + "\n")
    except:
        pass
    return entry


def is_reachable(ip: str) -> bool:
    """Test si une IP répond au ping."""
    try:
        r = subprocess.run(
            ["ping", "-c", "1", "-W", "1", ip],
            capture_output=True,
            text=True
        )
        return r.returncode == 0
    except:
        return False


def is_4g_connected() -> bool:
    """Vérifie si wwan0 a une adresse IP."""
    try:
        result = subprocess.run(["ip", "addr", "show", "wwan0"], capture_output=True, text=True)
        return "inet " in result.stdout
    except:
        return False


def update_history(state):
    """
    state = 1 → Freebox OK
    state = 0 → 4G ACTIVE
    """
    try:
        if not os.path.exists(HISTORY_FILE):
            data = {"times": [], "states": []}
        else:
            with open(HISTORY_FILE, "r") as f:
                data = json.load(f)
    except:
        data = {"times": [], "states": []}

    data["times"].append(datetime.now().strftime("%d/%m %H:%M"))
    data["states"].append(state)

    # On limite à 1000 points pour éviter le gonflement
    data["times"] = data["times"][-1000:]
    data["states"] = data["states"][-1000:]

    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(data, f)
    except:
        pass


# ----------------------------------------------------------------------
# Actions failover
# ----------------------------------------------------------------------
def switch_to_4g():
    """Active la connexion 4G et redirige la route par wwan0."""

    if not is_4g_connected():
        log("Connexion 4G…")
        subprocess.run(["sudo", CONNECT_4G])

    log("Bascule sur 4G")

    # Supprimer la route Freebox
    subprocess.run(
        ["ip", "route", "del", "default", "via", GATEWAY, "dev", "eth0"],
        stderr=subprocess.DEVNULL
    )

    # Trouver gateway 4G
    route = subprocess.run(
        ["ip", "route", "show", "dev", "wwan0"],
        capture_output=True,
        text=True
    ).stdout

    if "default" not in route:
        log("ERREUR : Aucune route 4G trouvée")
        return

    gw_4g = route.split("via")[1].split()[0]

    # Ajouter la route par wwan0
    subprocess.run(["ip", "route", "add", "default", "via", gw_4g, "dev", "wwan0"])

    # SMS notification
    try:
        subprocess.run(["python3", SMS_SCRIPT, "Failover : Bascule sur 4G !"])
    except:
        log("ERREUR SMS failover")

    update_history(0)


def switch_to_freebox():
    """Rebascule sur Freebox quand elle revient."""
    log("Retour sur Freebox")

    # Supprime la route wwan0 si présente
    subprocess.run(
        ["ip", "route", "del", "default", "dev", "wwan0"],
        stderr=subprocess.DEVNULL
    )

    # Remet route Freebox
    subprocess.run(["ip", "route", "add", "default", "via", GATEWAY, "dev", "eth0"])

    try:
        subprocess.run(["python3", SMS_SCRIPT, "Failback : Retour Freebox OK"])
    except:
        log("ERREUR SMS failback")

    update_history(1)


# ----------------------------------------------------------------------
# Boucle principale (Watchdog)
# ----------------------------------------------------------------------
def load_gateway():
    """Lit la gateway dans config.json."""
    try:
        with open(CONFIG_FILE, "r") as f:
            data = json.load(f)
            return data.get("gateway", "192.168.0.254")
    except:
        return "192.168.0.254"


def main():
    global GATEWAY
    GATEWAY = load_gateway()
    log("=== MONITOR FAILOVER DÉMARRÉ ===")
    update_history(1 if is_reachable(GATEWAY) else 0)

    last_state = None

    while True:
        time.sleep(5)

        GATEWAY = load_gateway()  # recharger automatiquement
        freebox_ok = is_reachable(GATEWAY)

        if freebox_ok:
            if last_state == 0:  # avant : 4G
                switch_to_freebox()
            last_state = 1
            continue

        # Freebox KO
        if last_state != 0:
            switch_to_4g()
        last_state = 0


if __name__ == "__main__":
    main()
