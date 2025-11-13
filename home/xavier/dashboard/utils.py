import subprocess
import os
import json
from datetime import datetime
import time
import zipfile
import shutil
import stat

def run(cmd: str) -> str:
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=6)
        return result.stdout.strip() if result.returncode == 0 else "N/A"
    except Exception:
        return "N/A"

def log(msg: str, log_file: str) -> str:
    entry = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    try:
        with open(log_file, "a") as f:
            f.write(entry + "\n")
    except Exception:
        pass
    return entry

def load_config(config_file: str):
    default = {
        "apn": "free",
        "sim_pin": "",
        "sms_phone": "+33XXXXXXXXX",
        "gateway": "192.168.0.254",
        "port": 5123,
        "serial_port": "/dev/ttyUSB3"
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
    try:
        tmp = config_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, config_file)
        return True
    except Exception:
        return False

def get_gateway(config_file: str):
    config = load_config(config_file)
    gateway_ip = config.get("gateway", "192.168.0.254")
    route = run("ip route show default")
    if gateway_ip in route and "eth0" in route:
        return "Freebox OK", "green"
    elif "wwan0" in route:
        return "4G ACTIVE", "red"
    return "Inconnu", "gray"

def get_signal():
    raw = run("qmicli -d /dev/cdc-wdm0 --nas-get-signal-strength 2>/dev/null | grep rssi")
    if not raw or "N/A" in raw:
        return "Non connecté", 0, "gray"
    try:
        rssi = float(raw.split("'")[1].split()[0])
        percent = max(0, min(100, int((rssi + 110) * 2.5)))
        color = "green" if rssi > -70 else "orange" if rssi > -90 else "red"
        return f"{rssi} dBm", percent, color
    except Exception:
        return "Erreur", 0, "gray"

def get_logs(log_file: str):
    if os.path.exists(log_file):
        try:
            with open(log_file) as f:
                return [l.strip() for l in f.readlines()[-8:] if l.strip()]
        except Exception:
            return ["Erreur log"]
    return ["Aucun log"]

def list_backups(backup_dir: str):
    try:
        return sorted([f for f in os.listdir(backup_dir) if f.endswith('.zip')], reverse=True)[:10]
    except Exception:
        return []

def get_freebox_history(log_file: str):
    if not os.path.exists(log_file):
        return [], []
    times, states = [], []
    try:
        with open(log_file) as f:
            lines = f.readlines()
        for line in lines[-500:]:
            if "Freebox OK" in line or "4G ACTIVE" in line:
                try:
                    time_part = line.split("]")[0].replace("[", "").strip()
                except Exception:
                    continue
                states.append(1 if "Freebox OK" in line else 0)
                times.append(time_part)
        return times, states
    except Exception:
        return [], []

def which_cmd(cmd: str):
    return shutil.which(cmd)

def is_writable(path: str) -> bool:
    try:
        if os.path.isdir(path):
            testfile = os.path.join(path, ".writetest")
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
                return True
    except Exception:
        return False

def is_executable(path: str) -> bool:
    try:
        st = os.stat(path)
        return bool(st.st_mode & stat.S_IXUSR)
    except Exception:
        return False

def check_dependencies(app_config: dict):
    checks = []

    def add(name, ok, detail=""):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    # Modules Python
    modules = [
        ("flask", "from flask import Flask"),
        ("json", "import json"),
        ("subprocess", "import subprocess"),
        ("zipfile", "import zipfile"),
        ("hashlib", "import hashlib"),
        ("secrets", "import secrets"),
        ("base64", "import base64"),
    ]
    for mod, code in modules:
        try:
            exec(code, {})
            add(f"Module Python: {mod}", True)
        except Exception as e:
            add(f"Module Python: {mod}", False, str(e))

    # Binaires système
    for bin_ in ["qmicli", "ip", "ping", "zip", "unzip", "crontab", "systemctl", "fuser"]:
        path = which_cmd(bin_)
        add(f"Binaire: {bin_}", path is not None, path or "absent")

    # Fichiers / permissions
    add("Fichier SMS_SCRIPT", os.path.exists(app_config['SMS_SCRIPT']), app_config['SMS_SCRIPT'])
    add("Dossier du LOG_FILE inscriptible", is_writable(os.path.dirname(app_config['LOG_FILE'])), os.path.dirname(app_config['LOG_FILE']))
    add("Dossier BACKUP_DIR", os.path.isdir(app_config['BACKUP_DIR']), app_config['BACKUP_DIR'])
    add("BACKUP_DIR inscriptible", is_writable(app_config['BACKUP_DIR']), app_config['BACKUP_DIR'])
    add("Dossier UPLOAD_DIR", os.path.isdir(app_config['UPLOAD_DIR']), app_config['UPLOAD_DIR'])
    add("UPLOAD_DIR inscriptible", is_writable(app_config['UPLOAD_DIR']), app_config['UPLOAD_DIR'])

    for path in ["/home/xavier/monitor_failover.py",
                 "/home/xavier/connect_4g.sh",
                 "/home/xavier/run_dashboard.py",
                 "/home/xavier/send_sms.py"]:
        if os.path.exists(path):
            add(f"Présence: {os.path.basename(path)}", True, path)
            if path.endswith((".sh", ".py")):
                add(f"Executable: {os.path.basename(path)}", is_executable(path), path)
        else:
            add(f"Présence: {os.path.basename(path)}", False, path)

    # Matériel / réseau
    add("Périphérique /dev/cdc-wdm0", os.path.exists("/dev/cdc-wdm0"), "/dev/cdc-wdm0")
    wwan_present = "wwan0" in (run("ip -o link") or "")
    add("Interface wwan0", wwan_present, run("ip -o link"))

    # Services systemd
    for svc in ["failover-dashboard.service", "failover-monitor.service"]:
        state = run(f"systemctl is-active {svc}")
        ok = state.strip() in ("active", "activating")
        add(f"Service {svc}", ok, state.strip() or "inconnu")

    # NOUVEAU : Vérification module SIM7600E
    add("Module SIM7600E (lsusb)", "1e0e" in run("lsusb") or "Simcom" in run("lsusb"), run("lsusb"))
    add("Port série (ttyUSB*)", any(os.path.exists(f"/dev/ttyUSB{i}") for i in range(5)), run("ls /dev/ttyUSB*"))

    # NOUVEAU : Vérification signal SIM7600E
    signal, _, color = get_signal()
    signal_ok = color != "gray" and color != "red"  # OK si green/orange (> -90 dBm)
    add("Signal SIM7600E", signal_ok, f"{signal} ({'OK' if signal_ok else 'Faible ou absent'})")

    return checks
