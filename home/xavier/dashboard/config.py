import os

def set_app_config(app):
    app.secret_key = os.environ.get("DASH_SECRET_KEY") or os.urandom(32)
    app.config['SMS_SCRIPT'] = "/home/xavier/send_sms.py"
    app.config['LOG_FILE'] = "/home/xavier/monitor.log"
    app.config['BACKUP_DIR'] = "/home/xavier/backups"
    app.config['UPLOAD_DIR'] = "/home/xavier/restore_tmp"
    app.config['USERS_DB'] = "/home/xavier/.dashboard_users.json"
    app.config['CONFIG_FILE'] = "/home/xavier/config.json"

    os.makedirs(app.config['BACKUP_DIR'], exist_ok=True)
    os.makedirs(app.config['UPLOAD_DIR'], exist_ok=True)
