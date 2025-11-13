#!/usr/bin/env python3
import os

from dashboard import app
from dashboard.utils import load_config, save_config

if __name__ == '__main__':
    config_file = "/home/xavier/config.json"
    log_file = "/home/xavier/monitor.log"
    if not os.path.exists(log_file):
        open(log_file, 'a').close()
    if not os.path.exists(config_file):
        save_config(load_config(config_file), config_file)

    config = load_config(config_file)
    port = config.get("port", 5123)
    port = int(os.environ.get("DASH_PORT", port))

    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
