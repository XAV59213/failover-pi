#!/usr/bin/env python3
import os
from dashboard import app
from dashboard.utils import load_config, save_config

CONFIG_FILE = "/home/xavier/config.json"
LOG_FILE = "/home/xavier/monitor.log"


if __name__ == "__main__":
    # Création fichiers si absents
    if not os.path.exists(LOG_FILE):
        open(LOG_FILE, 'a').close()

    if not os.path.exists(CONFIG_FILE):
        save_config(load_config(CONFIG_FILE), CONFIG_FILE)

    config = load_config(CONFIG_FILE)

    # Port du dashboard (peut être surchargé par variable d'environnement)
    port = int(os.environ.get("DASH_PORT", config.get("port", 5123)))

    # Lancement serveur Flask
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False
    )
