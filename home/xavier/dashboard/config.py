import os

def set_app_config(app):
    """
    Charge toutes les constantes essentielles du dashboard.
    Les chemins sont fixés pour correspondre au script d'installation.
    """

    # Secret key Flask (défini via systemd sinon auto-généré)
    app.secret_key = os.environ.get("DASH_SECRET_KEY") or os.urandom(32)

    # Fichiers du système
    app.config['SMS_SCRIPT'] = "/home/xavier/send_sms.py"
    app.config['LOG_FILE'] = "/home/xavier/monitor.log"
    app.config['CONFIG_FILE'] = "/home/xavier/config.json"
    app.config['USERS_DB'] = "/home/xavier/.dashboard_users.json"

    # Répertoires pour Backup & Restore
    app.config['BACKUP_DIR'] = "/home/xavier/backups"
    app.config['UPLOAD_DIR'] = "/home/xavier/restore_tmp"

    # Création automatique des dossiers si manquants
    os.makedirs(app.config['BACKUP_DIR'], exist_ok=True)
    os.makedirs(app.config['UPLOAD_DIR'], exist_ok=True)
