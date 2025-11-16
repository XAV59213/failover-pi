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
# Pages génériques
# ------------------------------------------------------------------
def success_page(title, msg, color="#3fb950", btn_color="#58a6ff"):
    return f"""
    <html lang="fr">
    <head><meta charset="utf-8"><title>{title}</title>
    <style>
      body {{background:#0d1117;color:#c9d1d9;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;}}
      .card {{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:24px;max-width:600px;text-align:center;}}
      h2 {{color:{color};margin-bottom:12px;}}
      p {{color:#8b949e;font-size:.95em;}}
      button {{margin-top:18px;padding:10px 16px;border-radius:8px;border:none;background:{btn_color};color:#fff;font-weight:600;cursor:pointer;}}
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
# Page de confirmation générique (comme backup, sans bouton)
# ------------------------------------------------------------------
def confirm_page(title, message, log_entry, redirect_url, delay=4):
    return f"""
    <html lang="fr"><head><meta charset="utf-8"><title>{title}</title>
    <meta http-equiv="refresh" content="{delay};url={redirect_url}">
    <style>body{{background:#0d1117;color:#c9d1d9;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;}}
    .card{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:28px;max-width:600px;text-align:center;}}
    h2{{color:#3fb950;margin-bottom:16px;}}
    .msg{{margin:12px 0;font-size:1.05em;}}
    .file{{font-family:monospace;background:#0d1117;padding:6px 12px;border-radius:6px;display:inline-block;margin:8px 0;}}
    .log{{color:#8b949e;font-size:0.9em;margin-top:10px;}}
    .redirect{{margin-top:20px;color:#58a6ff;font-weight:600;}}
    </style></head><body><div class="card">
      <h2>{title}</h2>
      <p class="msg">{message}</p>
      <p class="log">{log_entry}</p>
      <p class="redirect">Redirection dans {delay} seconde{'s' if delay > 1 else ''}...</p>
    </div></body></html>
    """

# ------------------------------------------------------------------
# Page de restauration avec compte à rebours
# ------------------------------------------------------------------
def restore_wait_page(log_entry, backup_name):
    return f"""
    <html lang="fr">
    <head>
      <meta charset="utf-8">
      <title>Restauration en cours</title>
      <meta http-equiv="refresh" content="10;url={url_for('backup')}" />
      <style>
        body {{background:#0d1117;color:#c9d1d9;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;}}
        .card {{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:32px;max-width:650px;text-align:center;}}
        h2 {{color:#58a6ff;margin-bottom:16px;}}
        .file {{font-family:monospace;background:#0d1117;padding:6px 12px;border-radius:6px;display:inline-block;margin:8px 0;}}
        .log {{color:#8b949e;font-size:0.9em;margin-top:10px;}}
        .countdown {{margin-top:20px;color:#58a6ff;font-weight:600;font-size:1.1em;}}
        .spinner {{margin:20px auto;width:40px;height:40px;border:4px solid #30363d;border-top:4px solid #58a6ff;border-radius:50%;animation:spin 1s linear infinite;}}
        @keyframes spin {{to{{transform:rotate(360deg)}}}}
      </style>
      <script>
        let timeLeft = 10;
        const countdownEl = document.getElementById('countdown');
        const interval = setInterval(() => {{
          timeLeft--;
          countdownEl.innerText = `Redirection dans ${{timeLeft}} seconde${{timeLeft > 1 ? 's' : ''}}...`;
          if (timeLeft <= 0) clearInterval(interval);
        }}, 1000);
      </script>
    </head>
    <body>
      <div class="card">
        <h2>Restauration en cours</h2>
        <div class="spinner"></div>
        <p><strong>Veuillez patienter</strong>, la restauration nécessite un redémarrage du Pi.</p>
        <p>Vous serez redirigé et recevrez une <strong>notification SMS</strong> du redémarrage.</p>
        <p>Fichier : <span class="file">{backup_name}</span></p>
        <p class="log">{log_entry}</p>
        <p class="countdown" id="countdown">Redirection dans 10 secondes...</p>
      </div>
    </body>
    </html>
    """

# ------------------------------------------------------------------
# Enregistrement des routes
# ------------------------------------------------------------------
def register_routes(app):
    LOG_FILE = app.config["LOG_FILE"]
    CONFIG_FILE = app.config["CONFIG_FILE"]
    BACKUP_DIR = app.config["BACKUP_DIR"]
    UPLOAD_DIR = app.config["UPLOAD_DIR"]
    USERS_DB = app.config["USERS_DB"]

    # AUTH
    @app.route("/setup", methods=["GET", "POST"])
    def setup():
        if admin_exists(USERS_DB): return redirect(url_for("login"))
        error = ""
        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            if not username or not password: error = "Utilisateur et mot de passe requis."
            else:
                data = load_users(USERS_DB)
                data.setdefault("users", []).append({"username": username, "password": make_password(password), "role": "admin"})
                if save_users(data, USERS_DB):
                    log(f"[AUTH] Admin créé: {username}", LOG_FILE)
                    return redirect(url_for("login"))
                error = "Impossible d'enregistrer l'utilisateur."
        return render_template("setup.html", error=error)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if not admin_exists(USERS_DB): return redirect(url_for("setup"))
        error = ""
        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            user = verify_credentials(username, password, USERS_DB)
            if user:
                session["user"] = {"username": user["username"], "role": user.get("role", "admin")}
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

    # DASHBOARD
    @app.route("/")
    @login_required
    def index():
        gw_text, _ = get_gateway(CONFIG_FILE)
        signal_text, signal_percent, _ = get_signal()
        logs = get_logs(LOG_FILE)
        times, states = get_freebox_history(LOG_FILE)
        return render_template("index.html", gw_text=gw_text, signal_text=signal_text, signal_percent=signal_percent,
                               logs=logs, history_times=json.dumps(times), history_states=json.dumps(states))

    # ACTIONS RÉSEAU (style backup)
    @app.route("/sms")
    @login_required
    def sms():
        msg = f"Test dashboard OK ! ({datetime.now().strftime('%d/%m/%Y')})"
        log_entry = log(f"[DASHBOARD] SMS Test → {msg}", LOG_FILE)
        try:
            subprocess.run(["python3", app.config["SMS_SCRIPT"], msg], cwd="/home/xavier", timeout=30, check=True)
            return confirm_page(
                title="SMS envoyé",
                message="Le test SMS a été envoyé avec succès.",
                log_entry=log_entry,
                redirect_url=url_for('index')
            )
        except Exception as e:
            error = log(f"[DASHBOARD] Erreur SMS: {e}", LOG_FILE)
            return error_page("Erreur SMS", error)

    @app.route("/reboot")
    @login_required
    def reboot():
        log_entry = log("[ACTION] Reboot 4G demandé via dashboard", LOG_FILE)
        subprocess.Popen(["/home/xavier/connect_4g.sh"])
        return confirm_page(
            title="Reboot 4G",
            message="La commande de redémarrage du modem 4G a été lancée.",
            log_entry=log_entry,
            redirect_url=url_for('index')
        )

    @app.route("/test_failover")
    @login_required
    def test_failover():
        gw_text, _ = get_gateway(CONFIG_FILE)
        msg = f"Test failover manuel - état: {gw_text} ({datetime.now().strftime('%d/%m/%Y %H:%M:%S')})"
        log_entry = log(f"[TEST] {msg}", LOG_FILE)
        try:
            subprocess.run(["python3", app.config["SMS_SCRIPT"], msg], cwd="/home/xavier", timeout=30, check=True)
            return confirm_page(
                title="Test Failover",
                message=f"SMS envoyé : <strong>{gw_text}</strong>",
                log_entry=log_entry,
                redirect_url=url_for('index')
            )
        except Exception as e:
            error = log(f"[TEST] Erreur envoi SMS: {e}", LOG_FILE)
            return error_page("Erreur Test Failover", error)

    @app.route("/clear_logs")
    @admin_required
    def clear_logs():
        open(LOG_FILE, "w").close()
        with open("/home/xavier/status_history.json", "w") as f: f.write('{"times":[],"states":[]}')
        log_entry = log("[ACTION] Logs effacés via dashboard", LOG_FILE)
        return success_page("Logs effacés", log_entry)

    # BACKUP
    @app.route("/backup")
    @admin_required
    def backup():
        backups = list_backups(BACKUP_DIR)
        return render_template("backup.html", backups=backups)

    @app.route("/backup/create")
    @admin_required
    def create_backup():
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_name = f"failoverpi-backup-{ts}.zip"
        backup_path = os.path.join(BACKUP_DIR, backup_name)
        base_home = "/home/xavier"
        try:
            with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as z:
                def add_if_exists(p, a=None): os.path.exists(p) and z.write(p, a or p)
                add_if_exists(os.path.join(base_home, "config.json"), "home/xavier/config.json")
                add_if_exists(os.path.join(base_home, "monitor_failover.py"), "home/xavier/monitor_failover.py")
                add_if_exists(os.path.join(base_home, "run_dashboard.py"), "home/xavier/run_dashboard.py")
                add_if_exists(os.path.join(base_home, "send_sms.py"), "home/xavier/send_sms.py")
                add_if_exists(os.path.join(base_home, "connect_4g.sh"), "home/xavier/connect_4g.sh")
                add_if_exists(os.path.join(base_home, "status_history.json"), "home/xavier/status_history.json")
                add_if_exists(os.path.join(base_home, "monitor.log"), "home/xavier/monitor.log")
                add_if_exists(os.path.join(base_home, ".dashboard_users.json"), "home/xavier/.dashboard_users.json")
                dash_dir = os.path.join(base_home, "dashboard")
                if os.path.isdir(dash_dir):
                    for root, _, files in os.walk(dash_dir):
                        if ".git" in root: continue
                        for f in files:
                            full = os.path.join(root, f)
                            arc = os.path.join("home/xavier", os.path.relpath(full, base_home))
                            z.write(full, arc)

            # Envoi SMS
            sms_msg = f"Backup créé : {backup_name} ({datetime.now().strftime('%d/%m/%Y %H:%M')})"
            log_entry = log(f"[BACKUP] Backup + SMS → {sms_msg}", LOG_FILE)
            try:
                subprocess.run(["python3", app.config["SMS_SCRIPT"], sms_msg], cwd="/home/xavier", timeout=30, check=True)
            except Exception as e:
                log(f"[BACKUP] Erreur envoi SMS: {e}", LOG_FILE)

            return confirm_page(
                title="Backup créé",
                message=f"Fichier : <span class='file'>{backup_name}</span><br><strong>SMS envoyé !</strong>",
                log_entry=log_entry,
                redirect_url=url_for('backup')
            )
        except Exception as e:
            error = log(f"[BACKUP] Erreur backup: {e}", LOG_FILE)
            return error_page("Erreur Backup", error)

    @app.route("/backup/delete/<name>")
    @admin_required
    def delete_backup(name):
        safe_name = os.path.basename(name)
        path = os.path.join(BACKUP_DIR, safe_name)
        if not os.path.exists(path): return error_page("Backup introuvable", safe_name)
        try:
            os.remove(path)
            log_entry = log(f"[BACKUP] Backup supprimé: {safe_name}", LOG_FILE)
            return confirm_page(
                title="Backup supprimé",
                message=f"Fichier : <span class='file'>{safe_name}</span>",
                log_entry=log_entry,
                redirect_url=url_for('backup')
            )
        except Exception as e:
            error = log(f"[BACKUP] Erreur suppression: {e}", LOG_FILE)
            return error_page("Erreur Suppression Backup", error)

    @app.route("/backup/download/<name>")
    @login_required
    def download_backup(name):
        path = os.path.join(BACKUP_DIR, os.path.basename(name))
        return send_file(path, as_attachment=True) if os.path.exists(path) else error_page("Introuvable", name)

    # Fonction de restauration
    def _restore_from_zip(zip_path):
        base_home = "/home/xavier"
        extract_dir = "/tmp/restore_temp"
        if os.path.exists(extract_dir): shutil.rmtree(extract_dir)
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as z: z.extractall(extract_dir)
        for root, _, files in os.walk(extract_dir):
            for f in files:
                src = os.path.join(root, f)
                rel = os.path.relpath(src, extract_dir)
                dest = os.path.join(base_home, rel.replace("home/xavier/", "", 1))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(src, dest)
        shutil.rmtree(extract_dir)

    # Restauration via upload
    @app.route("/restore", methods=["POST"])
    @admin_required
    def restore():
        file = request.files.get("backup_file")
        if not file or not file.filename.lower().endswith(".zip"):
            return error_page("Erreur", "Fichier .zip requis.")
        dest_path = os.path.join(UPLOAD_DIR, f"upload-{int(time.time())}.zip")
        file.save(dest_path)
        try:
            _restore_from_zip(dest_path)
            log_entry = log(f"[RESTORE] Restauration depuis upload: {os.path.basename(dest_path)}", LOG_FILE)
            subprocess.Popen(["sudo", "reboot"])
            return restore_wait_page(log_entry, os.path.basename(dest_path))
        except Exception as e:
            error = log(f"[RESTORE] Erreur: {e}", LOG_FILE)
            return error_page("Erreur Restauration", error)

    # Restauration depuis backup existant
    @app.route("/backup/restore_existing/<name>")
    @admin_required
    def restore_existing(name):
        path = os.path.join(BACKUP_DIR, os.path.basename(name))
        if not os.path.exists(path): return error_page("Backup introuvable", name)
        try:
            _restore_from_zip(path)
            log_entry = log(f"[RESTORE] Restauration: {os.path.basename(name)}", LOG_FILE)
            subprocess.Popen(["sudo", "reboot"])
            return restore_wait_page(log_entry, os.path.basename(name))
        except Exception as e:
            error = log(f"[RESTORE] Erreur: {e}", LOG_FILE)
            return error_page("Erreur Restauration", error)

    # REBOOT / SHUTDOWN
    @app.route("/reboot_pi")
    @admin_required
    def reboot_pi():
        log_entry = log("[ACTION] Reboot Pi demandé", LOG_FILE)
        subprocess.Popen(["sudo", "reboot"])
        return f"""
        <html lang="fr">
        <head>
          <meta charset="utf-8">
          <title>Reboot Pi</title>
          <meta http-equiv="refresh" content="20;url={url_for('index')}">
          <style>
            body {{background:#0d1117;color:#c9d1d9;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;}}
            .card {{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:32px;max-width:650px;text-align:center;}}
            h2 {{color:#3fb950;margin-bottom:16px;}}
            .msg {{margin:12px 0;font-size:1.05em;}}
            .log {{color:#8b949e;font-size:0.9em;margin-top:10px;}}
            .countdown {{margin-top:20px;color:#58a6ff;font-weight:600;font-size:1.1em;}}
            .spinner {{margin:20px auto;width:40px;height:40px;border:4px solid #30363d;border-top:4px solid #58a6ff;border-radius:50%;animation:spin 1s linear infinite;}}
            @keyframes spin {{to{{transform:rotate(360deg)}}}}
          </style>
          <script>
            let timeLeft = 20;
            const countdownEl = document.getElementById('countdown');
            const interval = setInterval(() => {{
              timeLeft--;
              countdownEl.innerText = `Redirection dans ${{timeLeft}} seconde${{timeLeft > 1 ? 's' : ''}}...`;
              if (timeLeft <= 0) clearInterval(interval);
            }}, 1000);
          </script>
        </head>
        <body>
          <div class="card">
            <h2>Reboot Pi</h2>
            <div class="spinner"></div>
            <p class="msg">Le Raspberry Pi va redémarrer dans quelques instants.</p>
            <p class="log">{log_entry}</p>
            <p class="countdown" id="countdown">Redirection dans 20 secondes...</p>
          </div>
        </body>
        </html>
        """
    # CONFIG / USERS
    @app.route("/diagnostics")
    @admin_required
    def diagnostics():
        return render_template("diagnostics.html", checks=check_dependencies(app.config))

    @app.route("/config", methods=["GET", "POST"])
    @admin_required
    def edit_config():
        cfg = load_config(CONFIG_FILE)
        message = error = ""
        if request.method == "POST":
            cfg["apn"] = request.form.get("apn", cfg.get("apn", "free")).strip()
            cfg["sim_pin"] = request.form.get("sim_pin", cfg.get("sim_pin", "")).strip()
            cfg["sms_phone"] = request.form.get("sms_phone", cfg.get("sms_phone", "")).strip()
            cfg["gateway"] = request.form.get("gateway", cfg.get("gateway", "192.168.0.254")).strip()
            cfg["serial_port"] = request.form.get("serial_port", cfg.get("serial_port", "/dev/ttyUSB3")).strip()
            recipients = [l.strip() for l in request.form.get("sms_recipients", "").splitlines() if l.strip()]
            cfg["sms_recipients"] = recipients
            if recipients: cfg["sms_phone"] = recipients[0]
            try: cfg["port"] = int(request.form.get("port", str(cfg.get("port", 5123))))
            except: pass
            if save_config(cfg, CONFIG_FILE):
                message = "Configuration sauvegardée."
                log("[CONFIG] Mise à jour via /config", LOG_FILE)
            else:
                error = "Échec sauvegarde."
        recipients_preview = "\n".join(cfg.get("sms_recipients", []) or [cfg.get("sms_phone", "")])
        logo_exists = os.path.isfile(os.path.join(app.static_folder, 'img', 'logo.png'))
        return render_template("config.html", cfg=cfg, message=message, error=error, recipients_preview=recipients_preview, logo_exists=logo_exists)

    @app.route('/config/template', methods=['POST'])
    @admin_required
    def config_template():
        if 'logo' not in request.files: return redirect(url_for('edit_config'))
        file = request.files['logo']
        if file.filename and file.filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            logo_path = os.path.join(app.static_folder, 'img', 'logo.png')
            os.makedirs(os.path.dirname(logo_path), exist_ok=True)
            file.save(logo_path)
            log("[CONFIG] Logo mis à jour", LOG_FILE)
        return redirect(url_for('edit_config'))

    @app.route("/account", methods=["GET", "POST"])
    @login_required
    def account():
        username = session["user"]["username"]
        message = error = ""
        if request.method == "POST":
            old = request.form.get("old_pass") or request.form.get("current_password", "")
            new = request.form.get("new_pass") or request.form.get("new_password", "")
            if not new: error = "Nouveau mot de passe requis."
            elif not verify_credentials(username, old, USERS_DB): error = "Mot de passe actuel incorrect."
            else:
                data = load_users(USERS_DB)
                for u in data["users"]:
                    if u["username"] == username:
                        u["password"] = make_password(new)
                        break
                if save_users(data, USERS_DB):
                    message = "Mot de passe mis à jour."
                    log(f"[AUTH] MDP changé: {username}", LOG_FILE)
                else:
                    error = "Échec sauvegarde."
        return render_template("account.html", msg=message, error=error)

    @app.route("/users", methods=["GET", "POST"])
    @admin_required
    def users():
        data = load_users(USERS_DB)
        users_list = data.get("users", [])
        message = error = ""
        if request.method == "POST":
            action = request.form.get("action")
            if action == "add":
                uname = (request.form.get("username") or request.form.get("new_username") or "").strip()
                pwd = request.form.get("password") or request.form.get("new_password") or ""
                role = request.form.get("role") or "user"
                if not uname or not pwd: error = "Nom et mot de passe requis."
                elif role not in ("admin", "user"): error = "Rôle invalide."
                elif any(u["username"] == uname for u in users_list): error = "Utilisateur existe déjà."
                else:
                    users_list.append({"username": uname, "password": make_password(pwd), "role": role})
                    data["users"] = users_list
                    if save_users(data, USERS_DB):
                        message = f"Utilisateur {uname} créé."
                        log(f"[USERS] Création: {uname} ({role})", LOG_FILE)
                    else:
                        error = "Échec enregistrement."
            elif action == "delete":
                uname = request.form.get("username") or ""
                if not uname: error = "Utilisateur non spécifié."
                else:
                    tgt = next((u for u in users_list if u["username"] == uname), None)
                    if not tgt: error = "Utilisateur introuvable."
                    elif tgt["role"] == "admin" and count_admins(USERS_DB) <= 1: error = "Impossible de supprimer le dernier admin."
                    else:
                        users_list = [u for u in users_list if u["username"] != uname]
                        data["users"] = users_list
                        if save_users(data, USERS_DB):
                            message = f"Utilisateur {uname} supprimé."
                            log(f"[USERS] Suppression: {uname}", LOG_FILE)
                        else:
                            error = "Échec suppression."
        return render_template("users.html", users=load_users(USERS_DB).get("users", []), msg=message, error=error)
