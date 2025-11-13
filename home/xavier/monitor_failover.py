#!/usr/bin/env python3
import subprocess
import time
from datetime import datetime
import os
import json

CONFIG_FILE = "/home/xavier/config.json"
LOG_FILE = "/home/xavier/monitor.log"
HISTORY_FILE = "/home/xavier/status_history.json"
SMS_SCRIPT = "/home/xavier/send_sms.py"
CONNECT_4G = "/home/xavier/connect_4g.sh"
PING_COUNT = 3
FAIL_THRESHOLD = 3
CHECK_INTERVAL = 30

def load_config():
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

config = load_config()
GATEWAY = config.get("gateway", "192.168.0.254")

def log(msg):
    entry = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    with open(LOG_FILE, "a") as f:
        f.write(entry + "\n")
    print(entry)
    return entry

def update_history(state):
    history = {"times": [], "states": []}
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            history = json.load(f)
    history["times"].append(datetime.now().strftime("%H:%M:%S"))
    history["states"].append(state)
    history["times"] = history["times"][-500:]
    history["states"] = history["states"][-500:]
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f)

def is_main_up():
    try:
        result = subprocess.run(["ping", "-c", "1", GATEWAY], capture_output=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False

def is_4g_connected():
    route = subprocess.run(["ip", "route", "show", "dev", "wwan0"], capture_output=True, text=True).stdout
    return "default" in route

def switch_to_4g():
    if not is_4g_connected():
        log("Connexion 4G...")
        subprocess.run(["sudo", CONNECT_4G])
    log("Bascule sur 4G")
    subprocess.run(["ip", "route", "del", "default", "via", GATEWAY, "dev", "eth0"])
    gw_4g = subprocess.run(["ip", "route", "show", "dev", "wwan0"], capture_output=True, text=True).stdout.splitlines()[0].split()[2]
    subprocess.run(["ip", "route", "add", "default", "via", gw_4g, "dev", "wwan0"])
    subprocess.run(["python3", SMS_SCRIPT, "Failover: Bascule sur 4G !"])
    update_history(0)

def switch_to_main():
    log("Retour sur Freebox")
    gw_4g = subprocess.run(["ip", "route", "show", "dev", "wwan0"], capture_output=True, text=True).stdout.splitlines()[0].split()[2] if is_4g_connected() else ""
    if gw_4g:
        subprocess.run(["ip", "route", "del", "default", "via", gw_4g, "dev", "wwan0"])
    subprocess.run(["ip", "route", "add", "default", "via", GATEWAY, "dev", "eth0"])
    subprocess.run(["python3", SMS_SCRIPT, "Failover: Retour sur Freebox OK !"])
    update_history(1)

fail_count = 0
current_state = 1

while True:
    if is_main_up():
        fail_count = 0
        if current_state == 0:
            switch_to_main()
            current_state = 1
    else:
        fail_count += 1
        log(f"Échec ping {fail_count}/{FAIL_THRESHOLD}")
        if fail_count >= FAIL_THRESHOLD and current_state == 1:
            switch_to_4g()
            current_state = 0
    time.sleep(CHECK_INTERVAL)
