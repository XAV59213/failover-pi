from flask import render_template_string, send_file, request, redirect, url_for, session
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


def success_page(title, msg, color="#3fb950", btn_color="#58a6ff"):
    return f"""<div style="text-align:center;padding:40px;color:#fff;background:#0d1117;height:100vh">
        <h2 style="color:{color}">{title}</h2>
        <p style="color:#8b949e">{msg}</p>
        <button onclick="location.href='/'" style="background:{btn_color};color:#fff;padding:12px 24px;border:none;border-radius:8px;margin-top:20px;cursor:pointer">Retour</button></div>"""


def error_page(title, msg):
    return success_page(title, msg, color="#f85149", btn_color="#f85149")


def topbar_html(active=""):
    user = session.get("user", {})
    username = user.get("username", "")
    role = user.get("role", "")

    items = [
        ("/", "Dashboard"),
        ("/diagnostics", "Diagnostics"),
        ("/config", "Configuration") if role == "admin" else None,
        ("/account", "Mon compte"),
        ("/users", "Utilisateurs") if role == "admin" else None,
        ("/logout", "Déconnexion"),
    ]

    links = []
    for it in items:
        if not it:
            continue
        href, label = it
        style = "color:#58a6ff" if active == href else "color:#8b949e"
        links.append(f'<a href="{href}" style="{style};text-decoration:none;margin-left:12px">{label}</a>')

    return f"""
    <div class="topbar">
      <div>Connecté : <strong>{username}</strong></div>
      <div>{"".join(links)}</div>
    </div>
    """


def register_routes(app):

    # ----------------------------------------------------------------------
    # Helpers internes
    # ----------------------------------------------------------------------
    def _restore_from_zip(zip_path: str):
        base_home = "/home/xavier"
        if not os.path.exists(zip_path):
            raise FileNotFoundError(zip_path)

        with zipfile.ZipFile(zip_path, "r") as z:
            for member in z.namelist():
                if not member.startswith("home/xavier/"):
                    continue
                rel = member[len("home/xavier/"):]
                dest_path = os.path.join(base_home, rel)

                if member.endswith("/"):
                    os.makedirs(dest_path, exist_ok=True)
                    continue

                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                with z.open(member) as src, open(dest_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)

        # Remettre droits exécutables
        for f in ["connect_4g.sh", "monitor_failover.py", "run_dashboard.py", "send_sms.py"]:
            p = os.path.join(base_home, f)
            if os.path.exists(p):
                os.chmod(p, 0o755)

    # ----------------------------------------------------------------------
    # AUTH
    # ----------------------------------------------------------------------
    @app.route("/setup", methods=["GET", "POST"])
    def setup():
        users_db = app.config["USERS_DB"]
        if admin_exists(users_db):
            return redirect(url_for("login"))
        error = ""
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            confirm = request.form.get("confirm", "")
            if not username or not password:
                error = "Utilisateur et mot de passe requis."
            elif password != confirm:
                error = "Les mots de passe ne correspondent pas."
            else:
                data = load_users(users_db)
                data.setdefault("users", []).append({
                    "username": username,
                    "password": make_password(password),
                    "role": "admin"
                })
                if save_users(data, users_db):
                    log(f"[AUTH] Admin créé: {username}", app.config["LOG_FILE"])
                    return redirect(url_for("login"))
                error = "Impossible d'enregistrer l'utilisateur."
        return render_template_string(f"""
        <html><body>
        <div style="max-width:360px;margin:auto;margin-top:100px">
            <h3>Créer Admin</h3>
            {"<p style='color:red'>"+error+"</p>" if error else ""}
            <form method="post">
              <input name="username" placeholder="Nom"><br>
              <input name="password" type="password" placeholder="Mot de passe"><br>
              <input name="confirm" type="password" placeholder="Confirmer"><br>
              <button>Créer</button>
            </form>
        </div>
        </body></html>
        """)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        users_db = app.config["USERS_DB"]
        if not admin_exists(users_db):
            return redirect(url_for("setup"))
        error = ""
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = verify_credentials(username, password, users_db)
            if user:
                session["user"] = {"username": user["username"], "role": user["role"]}
                log(f"[AUTH] Login: {username}", app.config["LOG_FILE"])
                return redirect(url_for("index"))
            error = "Identifiants invalides."
        return render_template_string(f"""
        <html><body>
        <div style="max-width:360px;margin:auto;margin-top:100px">
            <h3>Connexion</h3>
            {"<p style='color:red'>"+error+"</p>" if error else ""}
            <form method="post">
              <input name="username" placeholder="Utilisateur"><br>
              <input name="password" type="password" placeholder="Mot de passe"><br>
              <button>Connexion</button>
            </form>
        </div>
        </body></html>
        """)

    @app.route("/logout")
    def logout():
        u = session.get("user", {}).get("username", "?")
        session.clear()
        log(f"[AUTH] Déconnexion: {u}", app.config["LOG_FILE"])
        return redirect(url_for("login"))

    # ----------------------------------------------------------------------
    # DASHBOARD PRINCIPAL
    # ----------------------------------------------------------------------
    @app.route("/")
    @login_required
    def index():
        gateway, color = get_gateway(app.config["CONFIG_FILE"])
        signal, percent, _ = get_signal()

        logs = get_logs(app.config["LOG_FILE"])
        backups = list_backups(app.config["BACKUP_DIR"])
        times, states = get_freebox_history(app.config["LOG_FILE"])
        now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        backups_html = "".join([
            f'<div><a href="/download_backup/{b}">{b}</a>'
            f' <a href="/restore_existing/{b}">Restaurer</a>'
            f' <a href="/delete_backup/{b}">Suppr.</a></div>'
            for b in backups
        ])

        return render_template_string(f"""
        <html><body>
        <div class="container">
          {topbar_html("/")}

          <h2>Failover Dashboard</h2>
          <p>Dernière mise à jour : {now}</p>

          <h3>État réseau</h3>
          <p>Gateway : {gateway}</p>
          <p>Signal 4G : {signal}</p>

          <h3>Actions</h3>
          <a href="/sms">SMS Test</a> |
          <a href="/reboot">Reboot 4G</a> |
          <a href="/test_failover">Test Failover</a>

          <h3>Système</h3>
          <a href="/reboot_pi">Reboot Pi</a> |
          <a href="/shutdown">Shutdown Pi</a>

          <h3>Backups</h3>
          <a href="/backup">Créer Backup</a><br>
          {backups_html}

          <h3>Logs</h3>
          <div style="background:#111;padding:10px">
            {"<br>".join(logs)}
          </div>

        </div></body></html>
        """)

    # ----------------------------------------------------------------------
    # ACTIONS
    # ----------------------------------------------------------------------
    @app.route("/sms")
    @login_required
    def sms():
        msg = f"Test dashboard OK ({datetime.now().strftime('%d/%m/%Y')})"
        try:
            subprocess.run(["python3", app.config["SMS_SCRIPT"], msg], timeout=10)
            log(f"[SMS] Test envoyé", app.config["LOG_FILE"])
            return success_page("SMS envoyé", msg)
        except Exception as e:
            log(f"[SMS] Erreur {e}", app.config["LOG_FILE"])
            return error_page("Erreur SMS", str(e))

    @app.route("/reboot")
    @login_required
    def reboot_4g():
        try:
            subprocess.Popen(["/home/xavier/connect_4g.sh"])
            log("[4G] Reboot demandé", app.config["LOG_FILE"])
            return success_page("Reboot 4G", "Commande exécutée.")
        except Exception as e:
            return error_page("Erreur reboot 4G", str(e))

    @app.route("/test_failover")
    @login_required
    def test_failover():
        gateway, _ = get_gateway(app.config["CONFIG_FILE"])
        msg = f"Test failover : {gateway}"
        subprocess.run(["python3", app.config["SMS_SCRIPT"], msg])
        log("[FAILOVER] Test exécuté", app.config["LOG_FILE"])
        return success_page("Test Failover", msg)

    @app.route("/clear_logs")
    @admin_required
    def clear_logs():
        open(app.config["LOG_FILE"], "w").close()
        log("[LOGS] Clear", app.config["LOG_FILE"])
        return success_page("Logs effacés", "OK")

    # ----------------------------------------------------------------------
    # BACKUP / RESTORE
    # ----------------------------------------------------------------------
    @app.route("/backup")
    @admin_required
    def backup():
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = f"failoverpi-{ts}.zip"
        path = os.path.join(app.config["BACKUP_DIR"], name)

        base = "/home/xavier"

        try:
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
                for f in [
                    "config.json",
                    "monitor_failover.py",
                    "run_dashboard.py",
                    "send_sms.py",
                    "connect_4g.sh",
                    "monitor.log",
                    "status_history.json",
                    ".dashboard_users.json",
                ]:
                    fp = os.path.join(base, f)
                    if os.path.exists(fp):
                        z.write(fp, f"home/xavier/{f}")

                # dashboard/
                for root, dirs, files in os.walk(os.path.join(base, "dashboard")):
                    for f in files:
                        full = os.path.join(root, f)
                        rel = os.path.relpath(full, base)
                        z.write(full, f"home/xavier/{rel}")

            log(f"[BACKUP] Créé : {name}", app.config["LOG_FILE"])
            return success_page("Backup créé", name)
        except Exception as e:
            return error_page("Erreur Backup", str(e))

    @app.route("/download_backup/<name>")
    @login_required
    def download_backup(name):
        path = os.path.join(app.config["BACKUP_DIR"], name)
        if not os.path.exists(path):
            return error_page("Introuvable", name)
        return send_file(path, as_attachment=True)

    @app.route("/delete_backup/<name>")
    @admin_required
    def delete_backup(name):
        path = os.path.join(app.config["BACKUP_DIR"], name)
        if not os.path.exists(path):
            return error_page("Introuvable", name)
        os.remove(path)
        log(f"[BACKUP] Supprimé : {name}", app.config["LOG_FILE"])
        return success_page("Backup supprimé", name)

    @app.route("/restore", methods=["POST"])
    @admin_required
    def restore():
        f = request.files.get("backup_file")
        if not f:
            return error_page("Aucun fichier", "Sélectionne un ZIP")
        if not f.filename.endswith(".zip"):
            return error_page("Format invalide", "Fichier .zip uniquement")

        dest = os.path.join(app.config["UPLOAD_DIR"], f"upload-{int(time.time())}.zip")
        f.save(dest)

        try:
            _restore_from_zip(dest)
        except Exception as e:
            return error_page("Erreur restauration", str(e))

        subprocess.Popen(["sudo", "reboot"])
        return success_page("Restauration OK", "Le Pi va redémarrer.")

    @app.route("/restore_existing/<name>")
    @admin_required
    def restore_existing(name):
        path = os.path.join(app.config["BACKUP_DIR"], name)
        if not os.path.exists(path):
            return error_page("Introuvable", name)

        try:
            _restore_from_zip(path)
        except Exception as e:
            return error_page("Erreur restauration", str(e))

        subprocess.Popen(["sudo", "reboot"])
        return success_page("Restauration OK", name)

    # ----------------------------------------------------------------------
    # REBOOT PI / SHUTDOWN
    # ----------------------------------------------------------------------
    @app.route("/reboot_pi")
    @admin_required
    def reboot_pi():
        subprocess.Popen(["sudo", "reboot"])
        log("[PI] Reboot demandé", app.config["LOG_FILE"])
        return success_page("Reboot Pi", "En cours...")

    @app.route("/shutdown")
    @admin_required
    def shutdown_pi():
        subprocess.Popen(["sudo", "shutdown", "-h", "now"])
        log("[PI] Shutdown demandé", app.config["LOG_FILE"])
        return success_page("Shutdown Pi", "En cours...")

    # ----------------------------------------------------------------------
    # DIAGNOSTICS
    # ----------------------------------------------------------------------
    @app.route("/diagnostics")
    @login_required
    def diagnostics():
        checks = check_dependencies(app.config)
        rows = []
        ok = 0
        for c in checks:
            if c["ok"]:
                ok += 1
                badge = "<span style='color:green'>OK</span>"
            else:
                badge = "<span style='color:red'>KO</span>"
            rows.append(f"<tr><td>{c['name']}</td><td>{badge}</td><td>{c['detail']}</td></tr>")

        return render_template_string(f"""
        <html><body>
        {topbar_html("/diagnostics")}
        <h2>Diagnostics</h2>
        <p>{ok}/{len(checks)} OK</p>
        <table border=1 cellpadding=5>
          {''.join(rows)}
        </table>
        </body></html>
        """)
