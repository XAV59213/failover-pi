import subprocess
import os
import json
from datetime import datetime
import shutil
import stat


# ============================================================================
# HELPERS GÉNÉRIQUES
# ============================================================================

def run(cmd: str) -> str:
    """
    Exécute une commande shell et renvoie stdout ou 'N/A' en cas d'erreur.
    """
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=6)
        if result.returncode == 0:
            return result.stdout.strip()
        return "N/A"
    except Exception:
        return "N/A"


def log(msg: str, log_file: str) -> str:
    """
    Ajoute une ligne au fichier de log et renvoie l'entrée écrite.
    """
    entry = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    try:
        with open(log_file, "a") as f:
            f.write(entry + "\n")
    except Exception:
        pass
    return entry


# ============================================================================
# CONFIG
# ============================================================================

def load_config(config_file: str):
    """
    Charge config.json en appliquant des valeurs par défaut.
    """
    default = {
        "apn": "free",
        "sim_pin": "",
        "sms_phone": "+33XXXXXXXXX",
        "gateway": "192.168.0.254",
        "port": 5123,
        "serial_port": "/dev/ttyUSB3",
    }
    if os.path.exists(config_file):
        try:
            with open(config_file, "r") as f:
                data = json.load(f)
            default.update(data)
            return default
        except Exception:
            pass
    return default


def save_config(data, config_file: str):
    """
    Écrit config.json de manière atomique pour éviter la corruption.
    """
    try:
        tmp = config_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, config_file)
        return True
    except Exception:
        return False


# ============================================================================
# ÉTAT RÉSEAU / SIGNAL
# ============================================================================

def get_gateway(config_file: str):
    """
    Détermine la route par défaut :
      - 'Freebox OK' si la route default passe par la gateway (eth0)
      - '4G ACTIVE' si la route default passe par wwan0
      - 'Inconnu' sinon
    Retourne (texte, couleur_led).
    """
    config = load_config(config_file)
    gateway_ip = config.get("gateway", "192.168.0.254")

    route = run("ip route show default")
    if route == "N/A":
        return "Inconnu", "gray"

    if gateway_ip in route and "eth0" in route:
        return "Freebox OK", "green"
    elif "wwan0" in route:
        return "4G ACTIVE", "red"
    return "Inconnu", "gray"


def get_signal():
    """
    Récupère la force du signal SIM7600E via qmicli.
    Retourne (texte_rssi, pourcentage, couleur).
    """
    raw = run("qmicli -d /dev/cdc-wdm0 --nas-get-signal-strength 2>/dev/null | grep rssi")
    if not raw or raw == "N/A":
        return "Non connecté", 0, "gray"

    try:
        # Exemple de ligne : "RSSI: '-75 dBm' ..."
        rssi = float(raw.split("'")[1].split()[0])  # -75
        # Mapping simple -110 dBm → 0%, -70 dBm → 100%
        percent = max(0, min(100, int((rssi + 110) * 2.5)))
        color = "green" if rssi > -70 else ("orange" if rssi > -90 else "red")
        return f"{rssi} dBm", percent, color
    except Exception:
        return "Erreur", 0, "gray"


# ============================================================================
# LOGS / BACKUPS / HISTORIQUE
# ============================================================================

def get_logs(log_file: str):
    """
    Retourne les 8 dernières lignes de log (ou un message).
    """
    if not os.path.exists(log_file):
        return ["Aucun log"]
    try:
        with open(log_file) as f:
            lines = f.readlines()
        return [l.strip() for l in lines[-8:] if l.strip()]
    except Exception:
        return ["Erreur lecture logs"]


def list_backups(backup_dir: str):
    """
    Liste les 10 derniers fichiers .zip du répertoire de backup.
    """
    try:
        files = [f for f in os.listdir(backup_dir) if f.endswith(".zip")]
        return sorted(files, reverse=True)[:10]
    except Exception:
        return []


def get_freebox_history(log_file: str):
    """
    Renvoie l'historique Freebox / 4G pour l'affichage du graphique.

    Priorité :
      1. Lecture de /home/xavier/status_history.json (format structuré)
         {
           "times": ["01/01 10:00", ...],
           "states": [1, 0, 1, ...]  # 1=Freebox, 0=4G
         }
      2. Sinon : fallback sur le fichier de log (recherche 'Freebox OK' / '4G ACTIVE').
    """
    history_file = "/home/xavier/status_history.json"

    # --- 1) Fichier structuré (recommandé) ---
    if os.path.exists(history_file):
        try:
            with open(history_file, "r") as f:
                data = json.load(f)
            times = data.get("times", [])
            states = data.get("states", [])

            # On tronque au cas où ça gonfle (sécurité)
            if len(times) > 2000:
                times = times[-2000:]
            if len(states) > 2000:
                states = states[-2000:]

            # Alignement tailles
            n = min(len(times), len(states))
            return times[-n:], states[-n:]
        except Exception:
            # En cas de problème, on tombera sur le fallback log
            pass

    # --- 2) Fallback : parsing du fichier de log ---
    if not os.path.exists(log_file):
        return [], []

    times, states = [], []
    try:
        with open(log_file) as f:
            lines = f.readlines()

        # On ne garde que les dernières lignes pertinentes
        for line in lines[-500:]:
            if "Freebox OK" in line or "4G ACTIVE" in line:
                try:
                    time_part = line.split("]")[0].replace("[", "").strip()
                except Exception:
                    continue

                state = 1 if "Freebox OK" in line else 0
                times.append(time_part)
                states.append(state)

        return times, states
    except Exception:
        return [], []


# ============================================================================
# DIAGNOSTICS / PERMISSIONS
# ============================================================================

def which_cmd(cmd: str):
    return shutil.which(cmd)


def is_writable(path: str) -> bool:
    """
    Vérifie si un chemin est inscriptible (fichier ou répertoire).
    """
    try:
        if os.path.isdir(path):
            testfile = os.path.join(path, ".testwrite")
            with open(testfile, "w") as f:
                f.write("ok")
            os.remove(testfile)
            return True
        else:
            if not os.path.exists(path):
                with open(path, "w") as f:
                    f.write("")
                os.remove(path)
                return True
            with open(path, "a"):
                pass
            return True
    except Exception:
        return False


def is_executable(path: str) -> bool:
    """
    Vérifie le bit exécutable (utilisateur) sur un fichier.
    """
    try:
        st = os.stat(path)
        return bool(st.st_mode & stat.S_IXUSR)
    except Exception:
        return False


def check_dependencies(app_config: dict):
    """
    Réalise un diagnostic complet utilisé sur /diagnostics.
    Retourne une liste de dicts {name, ok, detail}.
    """
    checks = []

    def add(name, ok, detail=""):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    # --- Modules Python ---
    modules = [
        ("flask", "from flask import Flask"),
        ("json", "import json"),
        ("subprocess", "import subprocess"),
        ("zipfile", "import zipfile"),
        ("hashlib", "import hashlib"),
        ("secrets", "import secrets"),
        ("base64", "import base64"),
    ]
    for mod_name, code in modules:
        try:
            exec(code, {})
            add(f"Module Python: {mod_name}", True)
        except Exception as e:
            add(f"Module Python: {mod_name}", False, str(e))

    # --- Binaires système ---
    for bin_ in ["qmicli", "ip", "ping", "zip", "unzip", "crontab", "systemctl", "fuser"]:
        path = which_cmd(bin_)
        add(f"Binaire: {bin_}", path is not None, path or "absent")

    # --- Fichiers / permissions ---
    add("Fichier SMS_SCRIPT",
        os.path.exists(app_config["SMS_SCRIPT"]),
        app_config["SMS_SCRIPT"])

    log_dir = os.path.dirname(app_config["LOG_FILE"])
    add("Dossier du LOG_FILE inscriptible", is_writable(log_dir), log_dir)

    add("Dossier BACKUP_DIR", os.path.isdir(app_config["BACKUP_DIR"]), app_config["BACKUP_DIR"])
    add("BACKUP_DIR inscriptible", is_writable(app_config["BACKUP_DIR"]), app_config["BACKUP_DIR"])

    add("Dossier UPLOAD_DIR", os.path.isdir(app_config["UPLOAD_DIR"]), app_config["UPLOAD_DIR"])
    add("UPLOAD_DIR inscriptible", is_writable(app_config["UPLOAD_DIR"]), app_config["UPLOAD_DIR"])

    # Présence et exécution des scripts principaux
    for p in [
        "/home/xavier/monitor_failover.py",
        "/home/xavier/connect_4g.sh",
        "/home/xavier/run_dashboard.py",
        "/home/xavier/send_sms.py",
    ]:
        if os.path.exists(p):
            add(f"Présence: {os.path.basename(p)}", True, p)
            add(f"Executable: {os.path.basename(p)}", is_executable(p), p)
        else:
            add(f"Présence: {os.path.basename(p)}", False, p)

    # --- Matériel / réseau ---
    add("Périphérique /dev/cdc-wdm0", os.path.exists("/dev/cdc-wdm0"), "/dev/cdc-wdm0")

    links = run("ip -o link")
    wwan_present = "wwan0" in (links or "")
    add("Interface wwan0", wwan_present, links if links != "N/A" else "N/A")

    # --- Services systemd ---
    for svc in ["failover-dashboard.service", "failover-monitor.service"]:
        state = run(f"systemctl is-active {svc}")
        ok = state in ("active", "activating")
        add(f"Service {svc}", ok, state if state != "N/A" else "inconnu")

    # --- Module SIM7600E (USB) ---
    usb_out = run("lsusb")
    add(
        "Module SIM7600E (lsusb)",
        ("1e0e" in usb_out) or ("Simcom" in usb_out),
        usb_out if usb_out != "N/A" else "N/A",
    )

    # --- Ports série ---
    ports = run("ls /dev/ttyUSB*")
    add("Port série (ttyUSB*)", "/dev/ttyUSB" in ports, ports if ports != "N/A" else "N/A")

    # --- Signal SIM7600E ---
    signal_txt, _, color = get_signal()
    add("Signal SIM7600E", color != "gray", signal_txt)

    return checks
