from flask import (
    render_template,
    send_file,
    request,
    redirect,
    url_for,
    session,
)
import json
from datetime import datetime
import os
import subprocess
import time
import zipfile
import shutil

from .utils import (
    log,
    get_gateway,
    get_signal,
    get_logs,
    list_backups,
    get_freebox_history,
    check_dependencies,
    load_config,
    save_config,
)
from .auth import (
    login_required,
    admin_required,
    load_users,
    save_users,
    make_password,
    verify_credentials,
    count_admins,
    admin_exists,
)


# ------------------------------------------------------------------
# Petites pages de retour (succès / erreur)
# ------------------------------------------------------------------
def success_page(title, msg, color="#3fb950", btn_color="#58a6ff"):
    return f"""
    <html lang="fr">
    <head>
      <meta charset="utf-8">
      <title>{title}</title>
      <style>
        body {{
          background:#0d1117;
          color:#c9d1d9;
          font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif;
          display:flex;
          align-items:center;
          justify-content:center;
          height:100vh;
        }}
        .card {{
          background:#161b22;
          border:1px solid #30363d;
          border-radius:12px;
          padding:24px;
          max-width:600px;
          text-align:center;
        }}
        h2 {{ color:{color}; margin-bottom:12px; }}
        p  {{ color:#8b949e; font-size:.95em; }}
        button {{
          margin-top:18px;
          padding:10px 16px;
          border-radius:8px;
          border:none;
          background:{btn_color};
          color:#fff;
          font-weight:600;
          cursor:pointer;
        }}
      </style>
    </head>
    <body>
      <div class="card">
        <h2>{title}</h2>
        <p>{msg}</p>
        <button onclick="location.href='/'">Retour au dashboard</button>
      </div>
    </body>
    </html>
    """


def error_page(title, msg):
    return success_page(title, msg, color="#f85149", btn_color="#f85149")


# ------------------------------------------------------------------
# Enregistrement des routes
# ------------------------------------------------------------------
def register_routes(app):
    LOG_FILE = app.config["LOG_FILE"]
    CONFIG_FILE = app.config["CONFIG_FILE"]
    BACKUP_DIR = app.config["BACKUP_DIR"]
    UPLOAD_DIR = app.config["UPLOAD_DIR"]
    USERS_DB = app.config["USERS_DB"]

    # ==============================================================
    #  AUTH / SETUP
    # ==============================================================
    @app.route("/setup", methods=["GET", "POST"])
    def setup():
        # Si un admin existe déjà -> on renvoie vers /login
        if admin_exists(USERS_DB):
            return redirect(url_for("login"))

        error = ""
        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""

            if not username or not password:
                error = "Utilisateur et mot de passe requis."
            else:
                data = load_users(USERS_DB)
                data.setdefault("users", []).append(
                    {
                        "username": username,
                        "password": make_password(password),
                        "role": "admin",
                    }
                )
                if save_users(data, USERS_DB):
                    log(f"[AUTH] Admin créé: {username}", LOG_FILE)
                    return redirect(url_for("login"))
                error = "Impossible d'enregistrer l'utilisateur."

        # Tu peux ajouter l'affichage de error dans setup.html si tu veux
        return render_template("setup.html", error=error)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        # Tant qu'il n'y a pas d'admin -> forcer /setup
        if not admin_exists(USERS_DB):
            return redirect(url_for("setup"))

        error = ""

        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            user = verify_credentials(username, password, USERS_DB)

            if user:
                session["user"] = {
                    "username": user["username"],
                    "role": user.get("role", "admin"),
                }
                log(f"[AUTH] Connexion: {username}", LOG_FILE)
                return redirect(url_for("index"))
            else:
                error = "Identifiants invalides."

        return render_template("login.html", error=error)

    @app.route("/logout")
    def logout():
        u = session.get("user", {}).get("username", "?")
        session.clear()
        log(f"[AUTH] Déconnexion: {u}", LOG_FILE)
        return redirect(url_for("login"))

    # ==============================================================
    #  DASHBOARD PRINCIPAL
    # ==============================================================
    @app.route("/")
    @login_required
    def index():
        gw_text, _ = get_gateway(CONFIG_FILE)
        signal_text, signal_percent, _ = get_signal()
        logs = get_logs(LOG_FILE)

        # Historique Freebox / 4G (pour plus tard si tu veux un graphique)
        times, states = get_freebox_history(LOG_FILE)

        return render_template(
            "index.html",
            gw_text=gw_text,
            signal_text=signal_text,
            signal_percent=signal_percent,
            logs=logs,
            history_times=json.dumps(times),
            history_states=json.dumps(states),
        )

    # ==============================================================
    #  SMS / ACTIONS 4G & FAILOVER
    # ==============================================================
    @app.route("/sms")
    @login_required
    def sms():
        msg = f"Test dashboard OK ! ({datetime.now().strftime('%d/%m/%Y')})"
        log_entry = log(f"[DASHBOARD] SMS Test → {msg}", LOG_FILE)
        try:
            subprocess.run(
                ["python3", app.config["SMS_SCRIPT"], msg],
                cwd="/home/xavier",
                timeout=30,
            )
            return success_page("SMS envoyé", log_entry)
        except Exception as e:
            error = log(f"[DASHBOARD] Erreur SMS: {e}", LOG_FILE)
            return error_page("Erreur SMS", error)

    @app.route("/reboot")
    @login_required
    def reboot():
        log_entry = log("[ACTION] Reboot 4G demandé via dashboard", LOG_FILE)
        try:
            subprocess.Popen(["/home/xavier/connect_4g.sh"])
            return success_page(
                "Redémarrage 4G",
                f"Commande lancée.<br><small>{log_entry}</small>",
            )
        except Exception as e:
            error = log(f"[ERROR] Reboot 4G: {e}", LOG_FILE)
            return error_page("Erreur Reboot 4G", error)

    @app.route("/test_failover")
    @login_required
    def test_failover():
        gw_text, _ = get_gateway(CONFIG_FILE)
        msg = (
            "Test failover manuel - état: "
            f"{gw_text} ({datetime.now().strftime('%d/%m/%Y %H:%M:%S')})"
        )
        log_entry = log(f"[TEST] {msg}", LOG_FILE)
        try:
            subprocess.run(
                ["python3", app.config["SMS_SCRIPT"], msg],
                cwd="/home/xavier",
                timeout=30,
            )
            return success_page(
                "Test Failover",
                f"SMS envoyé.<br><small>{log_entry}</small>",
            )
        except Exception as e:
            error = log(f"[TEST] Erreur test failover: {e}", LOG_FILE)
            return error_page("Erreur Test Failover", error)

    @app.route("/clear_logs")
    @admin_required
    def clear_logs():
        try:
            # Vide monitor.log
            open(LOG_FILE, "w").close()

            # Remise à zéro de l'historique structuré
            history_file = "/home/xavier/status_history.json"
            try:
                with open(history_file, "w") as f:
                    f.write('{"times":[],"states":[]}')
            except Exception:
                pass

            log_entry = log("[ACTION] Logs effacés via dashboard", LOG_FILE)
            return success_page("Logs effacés", log_entry)
        except Exception as e:
            error = log(f"[ERROR] Clear logs: {e}", LOG_FILE)
            return error_page("Erreur Clear Logs", error)

    # ==============================================================
    #  BACKUP / RESTORE
    # ==============================================================
    def _restore_from_zip(zip_path: str):
        """
        Restaure les fichiers home/xavier/ depuis un ZIP créé par /backup.
        """
        base_home = "/home/xavier"
        if not os.path.exists(zip_path):
            raise FileNotFoundError(zip_path)

        with zipfile.ZipFile(zip_path, "r") as z:
            for member in z.namelist():
                if not member.startswith("home/xavier/"):
                    continue
                rel = member[len("home/xavier/"):].lstrip("/")
                if not rel:
                    continue

                dest_path = os.path.join(base_home, rel)

                if member.endswith("/"):
                    os.makedirs(dest_path, exist_ok=True)
                    continue

                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                with z.open(member) as src, open(dest_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)

        # Remettre les exécutables
        for f in ["connect_4g.sh", "monitor_failover.py", "run_dashboard.py", "send_sms.py"]:
            p = os.path.join(base_home, f)
            if os.path.exists(p):
                os.chmod(p, 0o755)

    @app.route("/backup")
    @admin_required
    def backup():
        backups = list_backups(BACKUP_DIR)
        return render_template("backup.html", backups=backups)

    @app.route("/backup/create")
    @admin_required
    def backup_create():
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_name = f"failoverpi-backup-{ts}.zip"
        backup_path = os.path.join(BACKUP_DIR, backup_name)
        base_home = "/home/xavier"

        try:
            with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as z:

                def add_if_exists(path, arcname=None):
                    if os.path.exists(path):
                        z.write(path, arcname or path)

                # Fichiers principaux
                add_if_exists(os.path.join(base_home, "config.json"), "home/xavier/config.json")
                add_if_exists(os.path.join(base_home, "monitor_failover.py"), "home/xavier/monitor_failover.py")
                add_if_exists(os.path.join(base_home, "run_dashboard.py"), "home/xavier/run_dashboard.py")
                add_if_exists(os.path.join(base_home, "send_sms.py"), "home/xavier/send_sms.py")
                add_if_exists(os.path.join(base_home, "connect_4g.sh"), "home/xavier/connect_4g.sh")
                add_if_exists(os.path.join(base_home, "status_history.json"), "home/xavier/status_history.json")
                add_if_exists(os.path.join(base_home, "monitor.log"), "home/xavier/monitor.log")
                add_if_exists(os.path.join(base_home, ".dashboard_users.json"), "home/xavier/.dashboard_users.json")

                # Dossier dashboard complet
                dash_dir = os.path.join(base_home, "dashboard")
                if os.path.isdir(dash_dir):
                    for root, dirs, files in os.walk(dash_dir):
                        for f in files:
                            full = os.path.join(root, f)
                            rel = os.path.relpath(full, base_home)
                            arc = os.path.join("home/xavier", rel)
                            z.write(full, arc)

            log_entry = log(f"[BACKUP] Backup créé: {backup_name}", LOG_FILE)
            return success_page(
                "Backup créé",
                f"Fichier : {backup_name}<br><small>{log_entry}</small>",
            )

        except Exception as e:
            error = log(f"[BACKUP] Erreur backup: {e}", LOG_FILE)
            return error_page("Erreur Backup", error)

    @app.route("/backup/download/<name>")
    @login_required
    def backup_download(name):
        safe_name = os.path.basename(name)
        path = os.path.join(BACKUP_DIR, safe_name)
        if not os.path.exists(path):
            return error_page("Backup introuvable", safe_name)
        return send_file(path, as_attachment=True)

    @app.route("/delete_backup/<name>")
    @admin_required
    def delete_backup(name):
        safe_name = os.path.basename(name)
        path = os.path.join(BACKUP_DIR, safe_name)
        if not os.path.exists(path):
            return error_page("Backup introuvable", safe_name)
        try:
            os.remove(path)
            log_entry = log(f"[BACKUP] Backup supprimé: {safe_name}", LOG_FILE)
            return success_page("Backup supprimé", log_entry)
        except Exception as e:
            error = log(f"[BACKUP] Erreur suppression backup: {e}", LOG_FILE)
            return error_page("Erreur Suppression Backup", error)

    @app.route("/restore", methods=["POST"])
    @admin_required
    def restore():
        # compat : zipfile (backup.html) ou backup_file (ancienne version)
        file = request.files.get("zipfile") or request.files.get("backup_file")
        if not file:
            return error_page("Aucun fichier", "Aucun fichier de backup fourni.")
        if not file.filename.lower().endswith(".zip"):
            return error_page("Format invalide", "Le fichier doit être un .zip")

        os.makedirs(UPLOAD_DIR, exist_ok=True)
        dest_path = os.path.join(UPLOAD_DIR, f"upload-{int(time.time())}.zip")
        file.save(dest_path)

        try:
            _restore_from_zip(dest_path)
            log_entry = log(
                f"[RESTORE] Backup restauré depuis upload: {os.path.basename(dest_path)}",
                LOG_FILE,
            )
        except Exception as e:
            error = log(f"[RESTORE] Erreur restauration: {e}", LOG_FILE)
            return error_page("Erreur Restauration", error)

        try:
            subprocess.Popen(["sudo", "reboot"])
        except Exception as e:
            log(f"[RESTORE] Erreur lors du reboot: {e}", LOG_FILE)

        return success_page(
            "Restauration en cours",
            f"Backup restauré, le Pi va redémarrer.<br><small>{log_entry}</small>",
        )

    @app.route("/restore_existing/<name>")
    @admin_required
    def restore_existing(name):
        safe_name = os.path.basename(name)
        path = os.path.join(BACKUP_DIR, safe_name)
        if not os.path.exists(path):
            return error_page("Backup introuvable", safe_name)

        try:
            _restore_from_zip(path)
            log_entry = log(f"[RESTORE] Backup restauré: {safe_name}", LOG_FILE)
        except Exception as e:
            error = log(f"[RESTORE] Erreur restauration: {e}", LOG_FILE)
            return error_page("Erreur Restauration", error)

        try:
            subprocess.Popen(["sudo", "reboot"])
        except Exception as e:
            log(f"[RESTORE] Erreur lors du reboot: {e}", LOG_FILE)

        return success_page(
            "Restauration en cours",
            f"Backup {safe_name} restauré, le Pi va redémarrer.<br><small>{log_entry}</small>",
        )

    # ==============================================================
    #  REBOOT / SHUTDOWN PI
    # ==============================================================
    @app.route("/reboot_pi")
    @admin_required
    def reboot_pi():
        log_entry = log("[ACTION] Reboot Pi demandé via dashboard", LOG_FILE)
        try:
            subprocess.Popen(["sudo", "reboot"])
            return success_page(
                "Reboot Pi",
                f"Redémarrage en cours...<br><small>{log_entry}</small>",
            )
        except Exception as e:
            error = log(f"[ERROR] Reboot Pi: {e}", LOG_FILE)
            return error_page("Erreur Reboot Pi", error)

    @app.route("/shutdown_pi")
    @admin_required
    def shutdown_pi():
        log_entry = log("[ACTION] Shutdown Pi demandé via dashboard", LOG_FILE)
        try:
            subprocess.Popen(["sudo", "shutdown", "-h", "now"])
            return success_page(
                "Shutdown Pi",
                f"Arrêt en cours...<br><small>{log_entry}</small>",
            )
        except Exception as e:
            error = log(f"[ERROR] Shutdown Pi: {e}", LOG_FILE)
            return error_page("Erreur Shutdown Pi", error)

    # ==============================================================
    #  DIAGNOSTICS
    # ==============================================================
    @app.route("/diagnostics")
    @admin_required
    def diagnostics():
        checks = check_dependencies(app.config)
        return render_template("diagnostics.html", checks=checks)

    # ==============================================================
    #  /config : édition APN, gateway, serial, PIN, port, téléphones
    # ==============================================================
    @app.route("/config", methods=["GET", "POST"])
    @admin_required
    def edit_config():
        cfg = load_config(CONFIG_FILE)
        message = ""
        error = ""

        if request.method == "POST":
            try:
                cfg["apn"] = request.form.get("apn", cfg.get("apn", "free")).strip()
                cfg["sim_pin"] = request.form.get("sim_pin", cfg.get("sim_pin", "")).strip()
                cfg["sms_phone"] = request.form.get("sms_phone", cfg.get("sms_phone", "")).strip()
                cfg["gateway"] = request.form.get("gateway", cfg.get("gateway", "192.168.0.254")).strip()
                cfg["serial_port"] = request.form.get("serial_port", cfg.get("serial_port", "/dev/ttyUSB3")).strip()

                # Liste de numéros SMS (un par ligne)
                raw_list = request.form.get("sms_recipients", "")
                recipients = []
                for line in raw_list.splitlines():
                    line = line.strip()
                    if line:
                        recipients.append(line)

                cfg["sms_recipients"] = recipients

                # Si on a une liste, on peut utiliser le premier comme "principal"
                if recipients:
                    cfg["sms_phone"] = recipients[0]

                port_str = request.form.get("port", str(cfg.get("port", 5123))).strip()
                try:
                    cfg["port"] = int(port_str)
                except ValueError:
                    pass  # on garde l'ancien port si invalide

                if save_config(cfg, CONFIG_FILE):
                    message = "Configuration sauvegardée. Un redémarrage du service dashboard peut être nécessaire."
                    log("[CONFIG] config.json mise à jour via /config", LOG_FILE)
                else:
                    error = "Impossible d'enregistrer la configuration."

            except Exception as e:
                error = f"Erreur lors de la mise à jour : {e}"

        # Pour l’instant, config.html ne montre pas message/error, mais ils sont dispo
        recipients_preview = "\n".join(
            cfg.get("sms_recipients", [])
            or ([cfg.get("sms_phone")] if cfg.get("sms_phone") else [])
        )

        return render_template(
            "config.html",
            cfg=cfg,
            message=message,
            error=error,
            recipients_preview=recipients_preview,
        )

    # ==============================================================
    #  /account : changer son mot de passe
    # ==============================================================
    @app.route("/account", methods=["GET", "POST"])
    @login_required
    def account():
        current_user = session.get("user", {})
        username = current_user.get("username")
        message = ""
        error = ""

        if request.method == "POST":
            current_password = request.form.get("old_pass", "") or request.form.get("current_password", "")
            new_password = request.form.get("new_pass", "") or request.form.get("new_password", "")

            if not new_password:
                error = "Nouveau mot de passe requis."
            else:
                if not verify_credentials(username, current_password, USERS_DB):
                    error = "Mot de passe actuel incorrect."
                else:
                    data = load_users(USERS_DB)
                    for u in data.get("users", []):
                        if u.get("username") == username:
                            u["password"] = make_password(new_password)
                            break
                    if save_users(data, USERS_DB):
                        message = "Mot de passe mis à jour."
                        log(f"[AUTH] Mot de passe changé pour {username}", LOG_FILE)
                    else:
                        error = "Impossible de sauvegarder le nouveau mot de passe."

        return render_template("account.html", msg=message, error=error)

    # ==============================================================
    #  /users : gestion multi-comptes (ADMIN uniquement)
    # ==============================================================
    @app.route("/users", methods=["GET", "POST"])
    @admin_required
    def users():
        data = load_users(USERS_DB)
        users_list = data.get("users", [])
        message = ""
        error = ""

        if request.method == "POST":
            action = request.form.get("action")

            # Ajout utilisateur
            if action == "add":
                new_username = (request.form.get("username") or "").strip() or (request.form.get("new_username") or "").strip()
                new_password = request.form.get("password") or request.form.get("new_password") or ""
                role = request.form.get("role") or "user"
                if not new_username or not new_password:
                    error = "Nom et mot de passe requis."
                elif role not in ("admin", "user"):
                    error = "Rôle invalide."
                elif any(u.get("username") == new_username for u in users_list):
                    error = "Cet utilisateur existe déjà."
                else:
                    users_list.append(
                        {
                            "username": new_username,
                            "password": make_password(new_password),
                            "role": role,
                        }
                    )
                    data["users"] = users_list
                    if save_users(data, USERS_DB):
                        message = f"Utilisateur {new_username} créé."
                        log(f"[USERS] Création utilisateur {new_username} ({role})", LOG_FILE)
                    else:
                        error = "Erreur lors de l'enregistrement."

            # Suppression utilisateur
            elif action == "delete":
                username = request.form.get("username") or ""
                if not username:
                    error = "Utilisateur non spécifié."
                else:
                    tgt = next((u for u in users_list if u.get("username") == username), None)
                    if not tgt:
                        error = "Utilisateur introuvable."
                    else:
                        if tgt.get("role") == "admin" and count_admins(USERS_DB) <= 1:
                            error = "Impossible de supprimer le dernier admin."
                        else:
                            users_list = [u for u in users_list if u.get("username") != username]
                            data["users"] = users_list
                            if save_users(data, USERS_DB):
                                message = f"Utilisateur {username} supprimé."
                                log(f"[USERS] Suppression utilisateur {username}", LOG_FILE)
                            else:
                                error = "Erreur lors de la suppression."

        # Recharger après modifs
        data = load_users(USERS_DB)
        users_list = data.get("users", [])

        return render_template("users.html", users=users_list, msg=message, error=error)
