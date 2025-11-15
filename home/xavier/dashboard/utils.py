import os
import json
import subprocess
import datetime
import shutil
from typing import List, Tuple


# ----------------------------------------------------------------------
#  LOG & CONFIG
# ----------------------------------------------------------------------
def log(msg: str, log_file: str) -> str:
    """Écrit un log horodaté dans log_file et le renvoie."""
    ts = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    line = f"[{ts}] {msg}"
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        # On évite les crashs si le log ne peut pas s'écrire
        pass
    print(line)
    return line


def load_config(path: str) -> dict:
    """Charge config.json (ou renvoie des valeurs par défaut)."""
    default_cfg = {
        "apn": "free",
        "sim_pin": "1234",
        "sms_phone": "+33600000000",
        "gateway": "192.168.0.254",
        "serial_port": "/dev/ttyUSB3",
        "port": 5123,
        "qmi_device": "/dev/cdc-wdm0",
        "wwan_interface": "wwan0",
    }
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            default_cfg.update(data or {})
    except Exception:
        pass
    return default_cfg


def save_config(cfg: dict, path: str) -> bool:
    """Sauvegarde config.json, renvoie True si OK."""
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


# ----------------------------------------------------------------------
#  COMMANDES SHELL
# ----------------------------------------------------------------------
def _run_cmd(cmd, timeout=10) -> Tuple[int, str, str]:
    """Exécute une commande shell et renvoie (rc, stdout, stderr)."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except Exception as e:
        return 1, "", str(e)


# ----------------------------------------------------------------------
#  LECTURE LOGS & HISTORIQUE
# ----------------------------------------------------------------------
def get_logs(log_file: str, limit: int = 80) -> List[str]:
    """Retourne les dernières lignes du fichier de log."""
    if not os.path.exists(log_file):
        return []
    try:
        with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        return [l.rstrip("\n") for l in lines[-limit:]]
    except Exception:
        return []


def get_freebox_history(log_file: str):
    """
    Renvoie l'historique Freebox / 4G pour l'affichage du graphique.

    Format recommandé de /home/xavier/status_history.json :
    {
      "times": ["06:43", "06:44", ...],
      "states": [1, 1, 0, ...]   # 1 = Freebox, 0 = 4G
    }

    On :
      - lit ce JSON si présent,
      - normalise les valeurs d'état,
      - ne garde que les N derniers points (pour un graphe lisible),
      - sinon, fallback : parsing du fichier de log.
    """
    history_file = "/home/xavier/status_history.json"
    MAX_POINTS = 60  # nombre max de points sur le graphe

    # --- 1) Fichier structuré (recommandé) ---
    if os.path.exists(history_file):
        try:
            with open(history_file, "r") as f:
                data = json.load(f)

            times = data.get("times", [])
            states = data.get("states", [])

            # Alignement tailles
            n = min(len(times), len(states))
            times = times[-n:]
            states = states[-n:]

            # Normalisation des états :
            #  - 1  => Freebox
            #  - 0  => 4G
            #  - tout le reste (ex: -1) => on force à 0 pour ne pas casser l'échelle
            norm_states = []
            for s in states:
                try:
                    v = int(s)
                except Exception:
                    v = 0
                if v <= 0:
                    v = 0
                else:
                    v = 1
                norm_states.append(v)

            states = norm_states

            # On limite le nombre de points pour garder un graphe lisible
            n = min(len(times), len(states), MAX_POINTS)
            if n > 0:
                return times[-n:], states[-n:]
            else:
                return [], []
        except Exception:
            # En cas de problème de lecture, fallback sur les logs
            pass

    # --- 2) Fallback : parsing du fichier de log (ancien système) ---
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

        # On limite aussi ici
        n = min(len(times), len(states), MAX_POINTS)
        return times[-n:], states[-n:]
    except Exception:
        return [], []


# ----------------------------------------------------------------------
#  BACKUPS
# ----------------------------------------------------------------------
def list_backups(backup_dir: str) -> List[str]:
    """Liste les backups ZIP dans le dossier backup_dir, triés par date descendante."""
    if not os.path.isdir(backup_dir):
        return []
    files = []
    for f in os.listdir(backup_dir):
        if f.lower().endswith(".zip"):
            full = os.path.join(backup_dir, f)
            files.append((f, os.path.getmtime(full)))
    files.sort(key=lambda x: x[1], reverse=True)
    return [f for f, _ in files]


# ----------------------------------------------------------------------
#  STATUT GATEWAY & SIGNAL 4G (pour le dashboard)
# ----------------------------------------------------------------------
def _ping_host(host: str, count: int = 2, timeout: int = 2) -> bool:
    rc, out, err = _run_cmd(
        ["ping", "-c", str(count), "-W", str(timeout), host],
        timeout=timeout * count + 2,
    )
    return rc == 0


def get_gateway(config_file: str) -> Tuple[str, str]:
    """
    Retourne (texte_statut, couleur_led) pour le dashboard.
    On ping la gateway Freebox et 8.8.8.8 via la route par défaut.
    """
    cfg = load_config(config_file)
    gw = cfg.get("gateway", "192.168.0.254")

    lan_ok = _ping_host(gw, count=1, timeout=1)
    internet_ok = _ping_host("8.8.8.8", count=1, timeout=1)

    if lan_ok and internet_ok:
        return "Freebox OK (Internet OK)", "#3fb950"
    if lan_ok and not internet_ok:
        return "Freebox OK (pas d'accès Internet)", "#f0883e"
    if not lan_ok:
        # On pourrait raffiner en testant wwan0, ici on simplifie :
        return "Connexion 4G ou aucune (Freebox KO)", "#f85149"

    return "État réseau inconnu", "#8b949e"


def get_signal() -> Tuple[str, int, int]:
    """
    Retourne (description_signal, pourcentage, rssi_dbm) pour le SIM7600E.
    Utilise qmicli --nas-get-signal-strength.
    """
    rc, out, err = _run_cmd(
        ["sudo", "qmicli", "-d", "/dev/cdc-wdm0", "--nas-get-signal-strength"],
        timeout=8,
    )
    if rc != 0:
        return ("Non connecté", 0, 0)

    # On cherche 'Network 'xxx': '-72 dBm''
    rssi_dbm = 0
    for line in out.splitlines():
        line = line.strip()
        if "Network" in line and "dBm" in line and ":" in line:
            # ex: Network 'lte': '-72 dBm'
            try:
                part = line.split(":")[-1].strip()
                val = part.split()[0].strip().replace("'", "")
                rssi_dbm = int(val)
                break
            except Exception:
                continue

    if rssi_dbm == 0:
        return ("Non connecté", 0, 0)

    # Conversion grossière dBm → %
    # -110 dBm = 0 %, -50 dBm = 100 %
    percent = int((rssi_dbm + 110) * 100 / 60)
    if percent < 0:
        percent = 0
    if percent > 100:
        percent = 100

    desc = f"{rssi_dbm} dBm ({percent}%)"
    return (desc, percent, rssi_dbm)


# ----------------------------------------------------------------------
#  DIAGNOSTICS (pour /diagnostics)
# ----------------------------------------------------------------------
def _check_python_module(name: str) -> dict:
    try:
        __import__(name)
        return {"name": f"Module Python: {name}", "ok": True, "detail": "OK"}
    except Exception as e:
        return {"name": f"Module Python: {name}", "ok": False, "detail": str(e)}


def _check_binary(name: str) -> dict:
    rc, out, err = _run_cmd(["which", name], timeout=3)
    if rc == 0 and out:
        return {"name": f"Binaire: {name}", "ok": True, "detail": out}
    return {"name": f"Binaire: {name}", "ok": False, "detail": err or "Introuvable"}


def _check_dir_writable(path: str, label: str) -> dict:
    if not os.path.isdir(path):
        return {"name": f"Dossier {label}", "ok": False, "detail": path}
    test_file = os.path.join(path, ".test_write")
    try:
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
        return {"name": f"{label} inscriptible", "ok": True, "detail": path}
    except Exception as e:
        return {"name": f"{label} inscriptible", "ok": False, "detail": f"{path} ({e})"}


def _check_file_exists(path: str, label: str) -> dict:
    if os.path.exists(path):
        return {"name": f"Présence: {label}", "ok": True, "detail": path}
    return {"name": f"Présence: {label}", "ok": False, "detail": f"{path} introuvable"}


def _check_executable(path: str, label: str) -> dict:
    if os.path.exists(path) and os.access(path, os.X_OK):
        return {"name": f"Executable: {label}", "ok": True, "detail": path}
    return {"name": f"Executable: {label}", "ok": False, "detail": f"{path} non exécutable ou introuvable"}


def _check_device(path: str, label: str) -> dict:
    if os.path.exists(path):
        return {"name": f"Périphérique {path}", "ok": True, "detail": path}
    return {"name": f"Périphérique {path}", "ok": False, "detail": "Introuvable"}


def _check_iface(name: str) -> dict:
    rc, out, err = _run_cmd(["ip", "a", "show", name], timeout=5)
    if rc == 0:
        return {"name": f"Interface {name}", "ok": True, "detail": out}
    return {"name": f"Interface {name}", "ok": False, "detail": err or "Introuvable"}


def _check_service(name: str) -> dict:
    rc, out, err = _run_cmd(["systemctl", "is-active", name], timeout=5)
    if rc == 0 and out.strip() == "active":
        return {"name": f"Service {name}", "ok": True, "detail": "active"}
    return {"name": f"Service {name}", "ok": False, "detail": out or err or "inactif"}


def _check_lsusb_sim7600() -> dict:
    rc, out, err = _run_cmd(["lsusb"], timeout=5)
    if rc == 0 and ("SimTech" in out or "1e0e:9001" in out or "Qualcomm" in out):
        return {"name": "Module SIM7600E (lsusb)", "ok": True, "detail": out}
    return {"name": "Module SIM7600E (lsusb)", "ok": False, "detail": err or out or "Non détecté"}


def _check_ttyusb_ports() -> dict:
    # On liste /dev/ttyUSB*
    ports = [p for p in os.listdir("/dev") if p.startswith("ttyUSB")]
    if ports:
        detail = " ".join(f"/dev/{p}" for p in ports)
        return {"name": "Port série (ttyUSB*)", "ok": True, "detail": detail}
    return {"name": "Port série (ttyUSB*)", "ok": False, "detail": "Aucun /dev/ttyUSB* détecté"}


def check_sim_card() -> dict:
    """
    Vérifie la présence de la carte SIM via qmicli --uim-get-card-status.
    'Card state: 'present'' → OK
    """
    rc, out, err = _run_cmd(
        ["sudo", "qmicli", "-d", "/dev/cdc-wdm0", "--uim-get-card-status"],
        timeout=10,
    )

    if rc != 0:
        return {"name": "SIM : Détection carte", "ok": False, "detail": f"Erreur qmicli ({rc})"}

    if "Card state: 'present'" in out:
        return {"name": "SIM : Détection carte", "ok": True, "detail": "Carte SIM détectée"}
    if "Card state: 'absent'" in out:
        return {"name": "SIM : Détection carte", "ok": False, "detail": "Aucune carte détectée"}

    return {"name": "SIM : Détection carte", "ok": False, "detail": "État carte inconnu"}


def check_sim_pin() -> dict:
    """
    Lit l'état du PIN via qmicli --uim-get-card-status.
    PIN1 state: 'enabled-verified' → OK (PIN validé / READY).
    """
    rc, out, err = _run_cmd(
        ["sudo", "qmicli", "-d", "/dev/cdc-wdm0", "--uim-get-card-status"],
        timeout=10,
    )

    if rc != 0:
        return {"name": "SIM : PIN (info)", "ok": False, "detail": f"Erreur qmicli ({rc})"}

    if "PIN1 state: 'enabled-verified'" in out:
        return {"name": "SIM : PIN (info)", "ok": True, "detail": "PIN vérifié (READY)"}
    if "PIN1 state: 'enabled-not-verified'" in out:
        return {"name": "SIM : PIN (info)", "ok": False, "detail": "PIN demandé (non saisi)"}
    if "PIN1 state: 'disabled'" in out:
        return {"name": "SIM : PIN (info)", "ok": True, "detail": "PIN désactivé"}

    return {"name": "SIM : PIN (info)", "ok": False, "detail": "État PIN inconnu"}


def check_modem_registration() -> dict:
    """
    Vérifie l'enregistrement réseau via qmicli --nas-get-serving-system.
    """
    rc, out, err = _run_cmd(
        ["sudo", "qmicli", "-d", "/dev/cdc-wdm0", "--nas-get-serving-system"],
        timeout=10,
    )

    if rc != 0:
        return {"name": "Modem : Enregistrement réseau", "ok": False, "detail": "N/A"}

    if "Registration state: 'registered'" in out:
        # On peut ajouter l'opérateur
        desc = "Enregistré"
        for line in out.splitlines():
            if "Description:" in line:
                desc = line.strip()
                break
        return {"name": "Modem : Enregistrement réseau", "ok": True, "detail": desc}

    return {"name": "Modem : Enregistrement réseau", "ok": False, "detail": "Non enregistré"}


def check_modem_signal() -> dict:
    """Diagnostic pour le signal SIM7600E."""
    desc, percent, rssi = get_signal()
    ok = percent > 0
    return {
        "name": "Signal SIM7600E",
        "ok": ok,
        "detail": desc,
    }


def check_wwan_active(wwan: str = "wwan0") -> dict:
    """
    Vérifie l'état de l'interface wwan0 (UP/DOWN).
    """
    rc, out, err = _run_cmd(["ip", "a", "show", wwan], timeout=5)
    if rc != 0:
        return {"name": "Modem : Interface wwan0 active", "ok": False, "detail": err or "Introuvable"}

    up = "UP" in out and "LOWER_UP" in out
    detail = out
    return {
        "name": "Modem : Interface wwan0 active",
        "ok": up,
        "detail": detail,
    }


def check_dependencies(app_config: dict) -> List[dict]:
    """
    Construit la liste de tous les diagnostics.
    app_config est app.config (Flask), on récupère LOG_FILE, BACKUP_DIR, etc.
    """
    checks: List[dict] = []

    # Modules Python
    for m in ["flask", "json", "subprocess", "zipfile", "hashlib", "secrets", "base64"]:
        checks.append(_check_python_module(m))

    # Binaires
    for b in ["qmicli", "ip", "ping", "zip", "unzip", "crontab", "systemctl", "fuser"]:
        checks.append(_check_binary(b))

    # Fichiers / Dossiers depuis la config Flask
    sms_script = app_config.get("SMS_SCRIPT", "/home/xavier/send_sms.py")
    log_file = app_config.get("LOG_FILE", "/home/xavier/monitor.log")
    backup_dir = app_config.get("BACKUP_DIR", "/home/xavier/backups")
    upload_dir = app_config.get("UPLOAD_DIR", "/home/xavier/restore_tmp")

    # SMS_SCRIPT
    checks.append(_check_file_exists(sms_script, "send_sms.py"))
    # Dossier du LOG_FILE
    log_dir = os.path.dirname(log_file)
    checks.append(_check_dir_writable(log_dir, "Dossier du LOG_FILE"))
    # BACKUP_DIR
    if not os.path.isdir(backup_dir):
        try:
            os.makedirs(backup_dir, exist_ok=True)
        except Exception:
            pass
    checks.append(_check_dir_writable(backup_dir, "BACKUP_DIR"))
    # UPLOAD_DIR
    if not os.path.isdir(upload_dir):
        try:
            os.makedirs(upload_dir, exist_ok=True)
        except Exception:
            pass
    checks.append(_check_dir_writable(upload_dir, "UPLOAD_DIR"))

    # Scripts principaux
    base_home = "/home/xavier"
    scripts = [
        ("monitor_failover.py", os.path.join(base_home, "monitor_failover.py")),
        ("connect_4g.sh", os.path.join(base_home, "connect_4g.sh")),
        ("run_dashboard.py", os.path.join(base_home, "run_dashboard.py")),
        ("send_sms.py", os.path.join(base_home, "send_sms.py")),
    ]
    for label, path in scripts:
        checks.append(_check_file_exists(path, label))
        checks.append(_check_executable(path, label))

    # Périphérique /dev/cdc-wdm0
    qmi_dev = app_config.get("QMI_DEVICE", "/dev/cdc-wdm0")
    checks.append(_check_device(qmi_dev, qmi_dev))

    # Interface wwan0
    wwan_if = app_config.get("WWAN_INTERFACE", "wwan0")
    checks.append(_check_iface(wwan_if))

    # Services systemd
    checks.append(_check_service("failover-dashboard.service"))
    checks.append(_check_service("failover-monitor.service"))

    # Module SIM7600E & ports série
    checks.append(_check_lsusb_sim7600())
    checks.append(_check_ttyusb_ports())

    # Signal, SIM, modem
    checks.append(check_modem_signal())
    checks.append(check_sim_card())
    checks.append(check_sim_pin())
    checks.append(check_modem_registration())
    checks.append(check_wwan_active(wwan_if))

    return checks
