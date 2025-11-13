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


# ----------------------------------------------------------------------
# Helpers HTML
# ----------------------------------------------------------------------
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

    is_admin = (role == "admin")

    items = [
        ("/", "Dashboard"),
        ("/diagnostics", "Diagnostics") if is_admin else None,
        ("/config", "Configuration") if is_admin else None,
        ("/account", "Mon compte"),
        ("/users", "Utilisateurs") if is_admin else None,
        ("/logout", "Déconnexion"),
    ]

    links = []
    for it in items:
        if not it:
            continue
        href, label = it
        style = "color:#58a6ff" if active == href else "color:#8b949e"
        links.append(
            f'<a href="{href}" style="{style};text-decoration:none;margin-left:12px">{label}</a>'
        )

    return f"""
    <div class="topbar" style="display:flex;justify-content:space-between;align-items:center;font-size:.9em;color:#8b949e;margin-bottom:8px;">
      <div>Connecté : <strong>{username}</strong> ({role})</div>
      <div>{"".join(links)}</div>
    </div>
    """


# ----------------------------------------------------------------------
# Enregistrement des routes
# ----------------------------------------------------------------------
def register_routes(app):

    # ==============================================================
    #  RESTORE HELPER
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
                rel = member[len("home/xavier/") :].lstrip("/")
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

    # ==============================================================
    #  AUTH / SETUP
    # ==============================================================
    @app.route("/setup", methods=["GET", "POST"])
    def setup():
        users_db = app.config["USERS_DB"]
        if admin_exists(users_db):
            return redirect(url_for("login"))

        error = ""
        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            confirm = request.form.get("confirm") or ""

            if not username or not password:
                error = "Utilisateur et mot de passe requis."
            elif password != confirm:
                error = "Les mots de passe ne correspondent pas."
            else:
                data = load_users(users_db)
                data.setdefault("users", []).append(
                    {
                        "username": username,
                        "password": make_password(password),
                        "role": "admin",
                    }
                )
                if save_users(data, users_db):
                    log(f"[AUTH] Admin créé: {username}", app.config["LOG_FILE"])
                    return redirect(url_for("login"))
                error = "Impossible d'enregistrer l'utilisateur."

        html = f"""
        <html lang="fr">
        <head>
          <meta charset="utf-8">
          <title>Créer Admin</title>
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
              width:360px;
            }}
            h1 {{
              text-align:center;
              color:#58a6ff;
              font-size:1.4em;
              margin-bottom:16px;
            }}
            input {{
              width:100%;
              padding:10px;
              margin:6px 0;
              border-radius:8px;
              border:1px solid #30363d;
              background:#0d1117;
              color:#c9d1d9;
            }}
            button {{
              width:100%;
              padding:12px;
              margin-top:10px;
              border-radius:8px;
              border:none;
              background:#58a6ff;
              color:#fff;
              font-weight:600;
              cursor:pointer;
            }}
            .error {{ color:#f85149; font-size:.9em; margin-bottom:6px; }}
          </style>
        </head>
        <body>
          <div class="card">
            <h1>Créer un compte admin</h1>
            {"<div class='error'>"+error+"</div>" if error else ""}
            <form method="post">
              <input name="username" placeholder="Nom d'utilisateur" required>
              <input name="password" type="password" placeholder="Mot de passe" required>
              <input name="confirm" type="password" placeholder="Confirmer le mot de passe" required>
              <button type="submit">Créer l'admin</button>
            </form>
          </div>
        </body>
        </html>
        """
        return render_template_string(html)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        users_db = app.config["USERS_DB"]

        if not admin_exists(users_db):
            return redirect(url_for("setup"))

        error = ""

        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            user = verify_credentials(username, password, users_db)

            if user:
                session["user"] = {
                    "username": user["username"],
                    "role": user.get("role", "admin"),
                }
                log(f"[AUTH] Connexion: {username}", app.config["LOG_FILE"])
                return redirect(url_for("index"))
            else:
                error = "Identifiants invalides."

        html = f"""
        <html lang="fr">
        <head>
          <meta charset="utf-8">
          <title>Connexion</title>
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
              width:360px;
            }}
            h1 {{
              text-align:center;
              color:#58a6ff;
              font-size:1.4em;
              margin-bottom:16px;
            }}
            input {{
              width:100%;
              padding:10px;
              margin:6px 0;
              border-radius:8px;
              border:1px solid #30363d;
              background:#0d1117;
              color:#c9d1d9;
            }}
            button {{
              width:100%;
              padding:12px;
              margin-top:10px;
              border-radius:8px;
              border:none;
              background:#58a6ff;
              color:#fff;
              font-weight:600;
              cursor:pointer;
            }}
            .error {{ color:#f85149; font-size:.9em; margin-bottom:6px; }}
            .hint  {{ font-size:.8em; text-align:center; color:#8b949e; margin-top:10px; }}
          </style>
        </head>
        <body>
          <div class="card">
            <h1>Connexion</h1>
            {"<div class='error'>"+error+"</div>" if error else ""}
            <form method="post">
              <input name="username" placeholder="Nom d'utilisateur" autocomplete="username" required>
              <input name="password" type="password" placeholder="Mot de passe" autocomplete="current-password" required>
              <button type="submit">Se connecter</button>
            </form>
            <div class="hint">Pas encore d'admin ? <a href="/setup" style="color:#58a6ff">Créer un compte admin</a></div>
          </div>
        </body>
        </html>
        """
        return render_template_string(html)

    @app.route("/logout")
    def logout():
        u = session.get("user", {}).get("username", "?")
        session.clear()
        log(f"[AUTH] Déconnexion: {u}", app.config["LOG_FILE"])
        return redirect(url_for("login"))

    # ==============================================================
    #  DASHBOARD PRINCIPAL
    # ==============================================================
    @app.route("/")
    @login_required
    def index():
        gateway, color = get_gateway(app.config["CONFIG_FILE"])
        signal, percent, _ = get_signal()

        logs = get_logs(app.config["LOG_FILE"])
        backups = list_backups(app.config["BACKUP_DIR"])
        times, states = get_freebox_history(app.config["LOG_FILE"])
        now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        user = session.get("user", {})
        is_admin = (user.get("role") == "admin")

        backups_html = "".join(
            [
                (
                    f'<div class="backup-item">'
                    f'<a href="/download_backup/{b}" style="color:#58a6ff">{b}</a>'
                    + (
                        f' <button onclick="if(confirm(\'Restaurer {b} et redémarrer le Pi ?\')) '
                        f'location.href=\'/restore_existing/{b}\'" '
                        f'style="background:#3fb950;color:#fff;padding:4px 8px;border:none;border-radius:4px;'
                        f'margin-left:8px;cursor:pointer">Restaurer</button>'
                        f' <button onclick="if(confirm(\'Supprimer {b} ?\')) '
                        f'location.href=\'/delete_backup/{b}\'" '
                        f'style="background:#f85149;color:#fff;padding:4px 8px;border:none;border-radius:4px;'
                        f'margin-left:8px;cursor:pointer">Supprimer</button>'
                        if is_admin
                        else ""
                    )
                    + "</div>"
                )
                for b in backups
            ]
        )

        html = f"""
        <!DOCTYPE html>
        <html lang="fr">
        <head>
          <meta charset="UTF-8">
          <meta name="viewport" content="width=device-width, initial-scale=1.0">
          <title>Failover Pi - Dashboard</title>
          <style>
            :root {{
              --bg:#0d1117;
              --card:#161b22;
              --text:#c9d1d9;
              --accent:#58a6ff;
              --danger:#f85149;
              --warning:#f0883e;
              --success:#3fb950;
            }}
            * {{ margin:0; padding:0; box-sizing:border-box; }}
            body {{
              background:var(--bg);
              color:var(--text);
              font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif;
              padding:16px;
            }}
            .container {{ max-width:980px; margin:auto; }}
            h1 {{
              text-align:center;
              color:var(--accent);
              font-size:1.8em;
              margin:16px 0 4px;
            }}
            .subtitle {{
              text-align:center;
              font-size:.85em;
              color:#8b949e;
              margin-bottom:16px;
            }}
            .card {{
              background:var(--card);
              border:1px solid #30363d;
              border-radius:12px;
              padding:16px;
              margin:10px 0;
            }}
            .status {{
              font-size:1.3em;
              text-align:center;
              padding:8px 0;
            }}
            .led {{
              width:18px;
              height:18px;
              border-radius:50%;
              display:inline-block;
              margin-right:8px;
              background:{color};
              box-shadow:0 0 10px {color};
            }}
            .signal {{ margin:8px 0; }}
            .bar {{
              height:18px;
              background:#21262d;
              border-radius:9px;
              overflow:hidden;
            }}
            .fill {{
              height:100%;
              background:linear-gradient(90deg,#f85149,#f0883e,#3fb950);
              width:{percent}%;
              transition:width .6s;
            }}
            .btn {{
              border:none;
              padding:10px 14px;
              margin:6px;
              border-radius:8px;
              cursor:pointer;
              font-weight:600;
              font-size:.95em;
            }}
            .btn-primary {{ background:var(--accent); color:#fff; }}
            .btn-danger {{ background:var(--danger); color:#fff; }}
            .btn-warning {{ background:var(--warning); color:#fff; }}
            .btn-success {{ background:var(--success); color:#fff; }}
            .btn-secondary {{ background:#30363d; color:#c9d1d9; }}
            .btn[disabled] {{
              opacity:.45;
              cursor:not-allowed;
            }}
            .btn-row {{
              display:flex;
              flex-wrap:wrap;
              gap:8px;
            }}
            .log {{
              background:#010409;
              padding:6px 8px;
              border-radius:6px;
              font-family:monospace;
              font-size:.82em;
              margin:3px 0;
              color:#8b949e;
            }}
            .log strong {{ color:#58a6ff; }}
            .backup-list {{
              max-height:150px;
              overflow-y:auto;
              font-size:.9em;
            }}
            .backup-item {{ padding:4px 0; border-bottom:1px solid #30363d; }}
            .time-footer {{
              font-size:.75em;
              color:#8b949e;
              text-align:center;
              margin-top:8px;
            }}
            @media (max-width:600px) {{
              .btn-row {{ flex-direction:column; }}
              .btn {{ width:100%; text-align:center; }}
            }}
          </style>
          <script>
            // Auto-refresh toutes les 10 secondes
            setInterval(()=>location.reload(), 10000);
          </script>
        </head>
        <body>
          <div class="container">
            {topbar_html(active="/")}
            <h1>Failover Pi Dashboard</h1>
            <div class="subtitle">Surveillance Freebox ↔ 4G (SIM7600E) — Dernière mise à jour : {now}</div>

            <div class="card">
              <div class="status">
                <span class="led"></span>
                <strong>{gateway}</strong>
              </div>
            </div>

            <div class="card">
              <div class="signal"><strong>Signal 4G :</strong> {signal}</div>
              <div class="bar"><div class="fill"></div></div>
            </div>

            <div class="card">
              <h3>Actions réseau</h3>
              <div class="btn-row">
                <button class="btn btn-primary" onclick="location.href='/sms'">Envoyer SMS Test</button>
                <button class="btn btn-warning" onclick="location.href='/reboot'">Redémarrer 4G</button>
              </div>
            </div>

            <div class="card">
              <h3>Actions système</h3>
              <div class="btn-row">
                <button class="btn btn-danger" onclick="if(confirm('Reboot du Raspberry Pi ?')) location.href='/reboot_pi';" {"disabled" if not is_admin else ""}>Reboot Pi</button>
                <button class="btn btn-danger" onclick="if(confirm('Arrêt COMPLET du Raspberry Pi ?')) location.href='/shutdown';" {"disabled" if not is_admin else ""}>Shutdown Pi</button>
              </div>
            </div>

            <div class="card">
              <h3>Backup & Restore</h3>
              <div class="btn-row">
                <button class="btn btn-success" onclick="location.href='/backup';" {"disabled" if not is_admin else ""}>Créer un backup</button>
                <button class="btn btn-success" onclick="document.getElementById('restore-form').style.display='block';" {"disabled" if not is_admin else ""}>Restaurer un backup</button>
              </div>
              <div id="restore-form" style="display:none;margin-top:10px;">
                <form action="/restore" method="post" enctype="multipart/form-data">
                  <input type="file" name="backup_file" accept=".zip" required style="margin:8px 0;color:#c9d1d9">
                  <button type="submit" class="btn btn-success" onclick="return confirm('Restaurer ce backup et redémarrer le Pi ?')">Restaurer & Reboot</button>
                </form>
              </div>
              <div class="backup-list" style="margin-top:8px;">
                <strong>Backups récents :</strong>
                {backups_html if backups_html else "<div style='margin-top:4px;color:#8b949e'>Aucun backup pour l'instant.</div>"}
              </div>
            </div>

            <div class="card">
              <h3>Outils</h3>
              <div class="btn-row">
                <button class="btn btn-secondary" onclick="location.href='/test_failover'">Test failover (SMS)</button>
                <button class="btn btn-secondary" onclick="if(confirm('Effacer tous les logs ?')) location.href='/clear_logs';" {"disabled" if not is_admin else ""}>Effacer les logs</button>
              </div>
            </div>

            <div class="card">
              <h3>Logs récents</h3>
              <div>
                {''.join([f'<div class="log"><strong>{l.split("] ")[0][1:]}</strong> {l.split("] ",1)[1] if "] " in l else l}</div>' for l in logs])}
              </div>
            </div>

            <div class="card">
              <h3 style="text-align:center;color:#58a6ff">État Freebox / 4G (historique)</h3>
              <canvas id="freeboxChart" height="120"></canvas>
            </div>

            <div class="time-footer">Auto-refresh toutes les 10 secondes</div>
          </div>

          <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
          <script>
            const fbCtx = document.getElementById('freeboxChart').getContext('2d');
            const fbTimes = {json.dumps(times)};
            const fbStates = {json.dumps(states)};
            new Chart(fbCtx, {{
              type: 'line',
              data: {{
                labels: fbTimes,
                datasets: [{{
                  label: 'État réseau (1 = Freebox, 0 = 4G)',
                  data: fbStates,
                  fill: true,
                  borderColor: '#58a6ff',
                  backgroundColor: 'rgba(88,166,255,0.2)',
                  tension: 0.2,
                  pointRadius: 0
                }}]
              }},
              options: {{
                responsive: true,
                scales: {{
                  y: {{
                    beginAtZero: true,
                    suggestedMax: 1,
                    ticks: {{
                      stepSize: 1,
                      callback: v => v === 1 ? 'Freebox' : (v === 0 ? '4G' : v)
                    }}
                  }},
                  x: {{
                    ticks: {{
                      autoSkip: true,
                      maxTicksLimit: 16
                    }}
                  }}
                }},
                plugins: {{
                  legend: {{ display: false }}
                }}
              }}
            }});
          </script>
        </body>
        </html>
        """
        return render_template_string(html)

    # ==============================================================
    #  ACTIONS SIMPLES : SMS / REBOOT 4G / TEST / CLEAR LOGS
    # ==============================================================
    @app.route("/sms")
    @login_required
    def sms():
        msg = f"Test dashboard OK ! ({datetime.now().strftime('%d/%m/%Y')})"
        log_entry = log(f"[DASHBOARD] SMS Test → {msg}", app.config["LOG_FILE"])
        try:
            subprocess.run(
                ["python3", app.config["SMS_SCRIPT"], msg],
                cwd="/home/xavier",
                timeout=15,
            )
            return success_page("SMS envoyé", log_entry)
        except Exception as e:
            error = log(f"[DASHBOARD] Erreur SMS: {e}", app.config["LOG_FILE"])
            return error_page("Erreur SMS", error)

    @app.route("/reboot")
    @login_required
    def reboot_4g():
        log_entry = log("[ACTION] Reboot 4G demandé via dashboard", app.config["LOG_FILE"])
        try:
            subprocess.Popen(["/home/xavier/connect_4g.sh"])
            return success_page("Redémarrage 4G", f"Commande lancée.<br><small>{log_entry}</small>")
        except Exception as e:
            error = log(f"[ERROR] Reboot 4G: {e}", app.config["LOG_FILE"])
            return error_page("Erreur Reboot 4G", error)

    @app.route("/test_failover")
    @login_required
    def test_failover():
        gateway, _ = get_gateway(app.config["CONFIG_FILE"])
        msg = f"Test failover manuel - état: {gateway} ({datetime.now().strftime('%d/%m/%Y %H:%M:%S')})"
        log_entry = log(f"[TEST] {msg}", app.config["LOG_FILE"])
        try:
            subprocess.run(
                ["python3", app.config["SMS_SCRIPT"], msg],
                cwd="/home/xavier",
                timeout=15,
            )
            return success_page("Test Failover", f"SMS envoyé.<br><small>{log_entry}</small>")
        except Exception as e:
            error = log(f"[TEST] Erreur test failover: {e}", app.config["LOG_FILE"])
            return error_page("Erreur Test Failover", error)

    @app.route("/clear_logs")
    @admin_required
    def clear_logs():
        try:
            open(app.config["LOG_FILE"], "w").close()
            # Optionnel : réinitialiser fichier d'historique structuré
            history_file = "/home/xavier/status_history.json"
            try:
                with open(history_file, "w") as f:
                    f.write('{"times":[],"states":[]}')
            except Exception:
                pass
            log_entry = log("[ACTION] Logs effacés via dashboard", app.config["LOG_FILE"])
            return success_page("Logs effacés", log_entry)
        except Exception as e:
            error = log(f"[ERROR] Clear logs: {e}", app.config["LOG_FILE"])
            return error_page("Erreur Clear Logs", error)

    # ==============================================================
    #  BACKUP / RESTORE
    # ==============================================================
    @app.route("/backup")
    @admin_required
    def backup():
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_name = f"failoverpi-backup-{ts}.zip"
        backup_path = os.path.join(app.config["BACKUP_DIR"], backup_name)
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

            log_entry = log(f"[BACKUP] Backup créé: {backup_name}", app.config["LOG_FILE"])
            return success_page("Backup créé", f"Fichier : {backup_name}<br><small>{log_entry}</small>")

        except Exception as e:
            error = log(f"[BACKUP] Erreur backup: {e}", app.config["LOG_FILE"])
            return error_page("Erreur Backup", error)

    @app.route("/download_backup/<name>")
    @login_required
    def download_backup(name):
        safe_name = os.path.basename(name)
        path = os.path.join(app.config["BACKUP_DIR"], safe_name)
        if not os.path.exists(path):
            return error_page("Backup introuvable", safe_name)
        return send_file(path, as_attachment=True)

    @app.route("/delete_backup/<name>")
    @admin_required
    def delete_backup(name):
        safe_name = os.path.basename(name)
        path = os.path.join(app.config["BACKUP_DIR"], safe_name)
        if not os.path.exists(path):
            return error_page("Backup introuvable", safe_name)
        try:
            os.remove(path)
            log_entry = log(f"[BACKUP] Backup supprimé: {safe_name}", app.config["LOG_FILE"])
            return success_page("Backup supprimé", log_entry)
        except Exception as e:
            error = log(f"[BACKUP] Erreur suppression backup: {e}", app.config["LOG_FILE"])
            return error_page("Erreur Suppression Backup", error)

    @app.route("/restore", methods=["POST"])
    @admin_required
    def restore():
        file = request.files.get("backup_file")
        if not file:
            return error_page("Aucun fichier", "Aucun fichier de backup fourni.")
        if not file.filename.lower().endswith(".zip"):
            return error_page("Format invalide", "Le fichier doit être un .zip")

        upload_dir = app.config["UPLOAD_DIR"]
        os.makedirs(upload_dir, exist_ok=True)
        dest_path = os.path.join(upload_dir, f"upload-{int(time.time())}.zip")
        file.save(dest_path)

        try:
            _restore_from_zip(dest_path)
            log_entry = log(
                f"[RESTORE] Backup restauré depuis upload: {os.path.basename(dest_path)}",
                app.config["LOG_FILE"],
            )
        except Exception as e:
            error = log(f"[RESTORE] Erreur restauration: {e}", app.config["LOG_FILE"])
            return error_page("Erreur Restauration", error)

        try:
            subprocess.Popen(["sudo", "reboot"])
        except Exception as e:
            log(f"[RESTORE] Erreur lors du reboot: {e}", app.config["LOG_FILE"])

        return success_page(
            "Restauration en cours",
            f"Backup restauré, le Pi va redémarrer.<br><small>{log_entry}</small>",
        )

    @app.route("/restore_existing/<name>")
    @admin_required
    def restore_existing(name):
        safe_name = os.path.basename(name)
        path = os.path.join(app.config["BACKUP_DIR"], safe_name)
        if not os.path.exists(path):
            return error_page("Backup introuvable", safe_name)

        try:
            _restore_from_zip(path)
            log_entry = log(f"[RESTORE] Backup restauré: {safe_name}", app.config["LOG_FILE"])
        except Exception as e:
            error = log(f"[RESTORE] Erreur restauration: {e}", app.config["LOG_FILE"])
            return error_page("Erreur Restauration", error)

        try:
            subprocess.Popen(["sudo", "reboot"])
        except Exception as e:
            log(f"[RESTORE] Erreur lors du reboot: {e}", app.config["LOG_FILE"])

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
        log_entry = log("[ACTION] Reboot Pi demandé via dashboard", app.config["LOG_FILE"])
        try:
            subprocess.Popen(["sudo", "reboot"])
            return success_page("Reboot Pi", f"Redémarrage en cours...<br><small>{log_entry}</small>")
        except Exception as e:
            error = log(f"[ERROR] Reboot Pi: {e}", app.config["LOG_FILE"])
            return error_page("Erreur Reboot Pi", error)

    @app.route("/shutdown")
    @admin_required
    def shutdown_pi():
        log_entry = log("[ACTION] Shutdown Pi demandé via dashboard", app.config["LOG_FILE"])
        try:
            subprocess.Popen(["sudo", "shutdown", "-h", "now"])
            return success_page("Shutdown Pi", f"Arrêt en cours...<br><small>{log_entry}</small>")
        except Exception as e:
            error = log(f"[ERROR] Shutdown Pi: {e}", app.config["LOG_FILE"])
            return error_page("Erreur Shutdown Pi", error)

    # ==============================================================
    #  DIAGNOSTICS
    # ==============================================================
    @app.route("/diagnostics")
    @admin_required
    def diagnostics():
        checks = check_dependencies(app.config)
        ok_count = sum(1 for c in checks if c["ok"])
        total = len(checks)

        rows = []
        for c in checks:
            badge = (
                "<span style='color:#3fb950;font-weight:600'>OK</span>"
                if c["ok"]
                else "<span style='color:#f85149;font-weight:600'>KO</span>"
            )
            detail = (
                c["detail"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                if c["detail"]
                else ""
            )
            rows.append(
                f"""
                <tr>
                  <td style="padding:8px 12px;border-bottom:1px solid #30363d">{c['name']}</td>
                  <td style="padding:8px 12px;border-bottom:1px solid #30363d;text-align:center">{badge}</td>
                  <td style="padding:8px 12px;border-bottom:1px solid #30363d;font-family:monospace;color:#8b949e">{detail}</td>
                </tr>
            """
            )

        html = f"""
        <html lang="fr">
        <head>
          <meta charset="utf-8">
          <title>Diagnostics</title>
          <style>
            :root {{
              --bg:#0d1117;
              --card:#161b22;
              --text:#c9d1d9;
              --accent:#58a6ff;
            }}
            body {{
              background:var(--bg);
              color:var(--text);
              font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif;
              padding:16px;
            }}
            .container {{ max-width:980px; margin:auto; }}
            .card {{
              background:var(--card);
              border:1px solid #30363d;
              border-radius:12px;
              padding:16px;
              margin-top:12px;
            }}
            h1 {{
              font-size:1.6em;
              color:var(--accent);
              margin-bottom:8px;
            }}
            table {{ width:100%; border-collapse:collapse; margin-top:10px; }}
            th {{
              text-align:left;
              padding:8px 12px;
              border-bottom:1px solid #30363d;
              font-weight:600;
            }}
            .btn {{
              display:inline-block;
              padding:8px 12px;
              border-radius:8px;
              background:#58a6ff;
              color:#fff;
              text-decoration:none;
              font-weight:600;
              margin-top:8px;
            }}
          </style>
        </head>
        <body>
          <div class="container">
            {topbar_html(active="/diagnostics")}
            <div class="card">
              <h1>Diagnostics système</h1>
              <div>Résumé : <strong>{ok_count}/{total} OK</strong></div>
              <a class="btn" href="/diagnostics">Rafraîchir</a>
              <div style="overflow:auto;margin-top:10px;">
                <table>
                  <thead>
                    <tr>
                      <th>Vérification</th>
                      <th style="text-align:center;">État</th>
                      <th>Détails</th>
                    </tr>
                  </thead>
                  <tbody>
                    {"".join(rows)}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </body>
        </html>
        """
        return render_template_string(html)

    # ==============================================================
    #  /config : édition APN, gateway, serial, PIN, port, téléphone
    # ==============================================================
    @app.route("/config", methods=["GET", "POST"])
    @admin_required
    def edit_config():
        config_file = app.config["CONFIG_FILE"]
        cfg = load_config(config_file)
        message = ""
        error = ""

        if request.method == "POST":
            try:
                cfg["apn"] = request.form.get("apn", cfg.get("apn", "free")).strip()
                cfg["sim_pin"] = request.form.get("sim_pin", cfg.get("sim_pin", "")).strip()
                cfg["sms_phone"] = request.form.get("sms_phone", cfg.get("sms_phone", "")).strip()
                cfg["gateway"] = request.form.get("gateway", cfg.get("gateway", "192.168.0.254")).strip()
                cfg["serial_port"] = request.form.get("serial_port", cfg.get("serial_port", "/dev/ttyUSB3")).strip()

                port_str = request.form.get("port", str(cfg.get("port", 5123))).strip()
                try:
                    cfg["port"] = int(port_str)
                except ValueError:
                    # On garde l'ancien port si non valide
                    pass

                if save_config(cfg, config_file):
                    message = "Configuration sauvegardée. Un redémarrage du service dashboard peut être nécessaire."
                    log("[CONFIG] config.json mise à jour via /config", app.config["LOG_FILE"])
                else:
                    error = "Impossible d'enregistrer la configuration."

            except Exception as e:
                error = f"Erreur lors de la mise à jour : {e}"

        html = f"""
        <html lang="fr">
        <head>
          <meta charset="utf-8">
          <title>Configuration réseau</title>
          <style>
            body {{
              background:#0d1117;
              color:#c9d1d9;
              font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif;
              padding:16px;
            }}
            .container {{ max-width:700px; margin:auto; }}
            .card {{
              background:#161b22;
              border:1px solid #30363d;
              border-radius:12px;
              padding:16px;
              margin-top:12px;
            }}
            h1 {{
              color:#58a6ff;
              font-size:1.6em;
              margin-bottom:8px;
            }}
            label {{
              display:block;
              margin-top:10px;
              font-size:.9em;
              color:#8b949e;
            }}
            input {{
              width:100%;
              padding:8px;
              margin-top:4px;
              border-radius:8px;
              border:1px solid #30363d;
              background:#0d1117;
              color:#c9d1d9;
            }}
            .btn {{
              margin-top:14px;
              padding:10px 16px;
              border-radius:8px;
              border:none;
              background:#58a6ff;
              color:#fff;
              font-weight:600;
              cursor:pointer;
            }}
            .msg-ok {{
              color:#3fb950;
              margin-top:8px;
              font-size:.9em;
            }}
            .msg-err {{
              color:#f85149;
              margin-top:8px;
              font-size:.9em;
            }}
          </style>
        </head>
        <body>
          <div class="container">
            {topbar_html(active="/config")}
            <div class="card">
              <h1>Configuration réseau & modem</h1>
              {"<div class='msg-ok'>"+message+"</div>" if message else ""}
              {"<div class='msg-err'>"+error+"</div>" if error else ""}
              <form method="post">
                <label>APN (Free Mobile)</label>
                <input name="apn" value="{cfg.get("apn","free")}">

                <label>PIN de la carte SIM (laisser vide si désactivé)</label>
                <input name="sim_pin" value="{cfg.get("sim_pin","")}">

                <label>Numéro SMS de notification</label>
                <input name="sms_phone" value="{cfg.get("sms_phone","+33XXXXXXXXX")}">

                <label>Gateway Freebox</label>
                <input name="gateway" value="{cfg.get("gateway","192.168.0.254")}">

                <label>Port Dashboard</label>
                <input name="port" value="{cfg.get("port",5123)}">

                <label>Port série modem (SIM7600E)</label>
                <input name="serial_port" value="{cfg.get("serial_port","/dev/ttyUSB3")}">

                <button type="submit" class="btn">Enregistrer</button>
              </form>
            </div>
          </div>
        </body>
        </html>
        """
        return render_template_string(html)

    # ==============================================================
    #  /account : changer son mot de passe
    # ==============================================================
    @app.route("/account", methods=["GET", "POST"])
    @login_required
    def account():
        users_db = app.config["USERS_DB"]
        current_user = session.get("user", {})
        username = current_user.get("username")

        message = ""
        error = ""

        if request.method == "POST":
            current_password = request.form.get("current_password", "")
            new_password = request.form.get("new_password", "")
            confirm = request.form.get("confirm", "")

            if not new_password:
                error = "Nouveau mot de passe requis."
            elif new_password != confirm:
                error = "Les mots de passe ne correspondent pas."
            else:
                # Vérifie le mot de passe actuel
                if not verify_credentials(username, current_password, users_db):
                    error = "Mot de passe actuel incorrect."
                else:
                    data = load_users(users_db)
                    for u in data.get("users", []):
                        if u.get("username") == username:
                            u["password"] = make_password(new_password)
                            break
                    if save_users(data, users_db):
                        message = "Mot de passe mis à jour."
                        log(f"[AUTH] Mot de passe changé pour {username}", app.config["LOG_FILE"])
                    else:
                        error = "Impossible de sauvegarder le nouveau mot de passe."

        html = f"""
        <html lang="fr">
        <head>
          <meta charset="utf-8">
          <title>Mon compte</title>
          <style>
            body {{
              background:#0d1117;
              color:#c9d1d9;
              font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif;
              padding:16px;
            }}
            .container {{ max-width:600px; margin:auto; }}
            .card {{
              background:#161b22;
              border:1px solid #30363d;
              border-radius:12px;
              padding:16px;
              margin-top:12px;
            }}
            h1 {{ color:#58a6ff; font-size:1.5em; margin-bottom:8px; }}
            label {{
              display:block;
              margin-top:10px;
              font-size:.9em;
              color:#8b949e;
            }}
            input {{
              width:100%;
              padding:8px;
              margin-top:4px;
              border-radius:8px;
              border:1px solid #30363d;
              background:#0d1117;
              color:#c9d1d9;
            }}
            .btn {{
              margin-top:14px;
              padding:10px 16px;
              border-radius:8px;
              border:none;
              background:#58a6ff;
              color:#fff;
              font-weight:600;
              cursor:pointer;
            }}
            .msg-ok {{ color:#3fb950; margin-top:8px; font-size:.9em; }}
            .msg-err {{ color:#f85149; margin-top:8px; font-size:.9em; }}
          </style>
        </head>
        <body>
          <div class="container">
            {topbar_html(active="/account")}
            <div class="card">
              <h1>Mon compte</h1>
              <p>Utilisateur connecté : <strong>{username}</strong></p>
              {"<div class='msg-ok'>"+message+"</div>" if message else ""}
              {"<div class='msg-err'>"+error+"</div>" if error else ""}
              <form method="post">
                <label>Mot de passe actuel</label>
                <input type="password" name="current_password" required>

                <label>Nouveau mot de passe</label>
                <input type="password" name="new_password" required>

                <label>Confirmer le nouveau mot de passe</label>
                <input type="password" name="confirm" required>

                <button type="submit" class="btn">Mettre à jour</button>
              </form>
            </div>
          </div>
        </body>
        </html>
        """
        return render_template_string(html)

    # ==============================================================
    #  /users : gestion multi-comptes (ADMIN uniquement)
    # ==============================================================
    @app.route("/users", methods=["GET", "POST"])
    @admin_required
    def users():
        users_db = app.config["USERS_DB"]
        data = load_users(users_db)
        users_list = data.get("users", [])
        message = ""
        error = ""

        if request.method == "POST":
            action = request.form.get("action")

            # Ajout utilisateur
            if action == "add":
                new_username = (request.form.get("new_username") or "").strip()
                new_password = request.form.get("new_password") or ""
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
                    if save_users(data, users_db):
                        message = f"Utilisateur {new_username} créé."
                        log(f"[USERS] Création utilisateur {new_username} ({role})", app.config["LOG_FILE"])
                    else:
                        error = "Erreur lors de l'enregistrement."

            # Suppression utilisateur
            elif action == "delete":
                username = request.form.get("username") or ""
                if not username:
                    error = "Utilisateur non spécifié."
                else:
                    # Interdit de supprimer le dernier admin
                    tgt = next((u for u in users_list if u.get("username") == username), None)
                    if not tgt:
                        error = "Utilisateur introuvable."
                    else:
                        if tgt.get("role") == "admin" and count_admins(users_db) <= 1:
                            error = "Impossible de supprimer le dernier admin."
                        else:
                            users_list = [u for u in users_list if u.get("username") != username]
                            data["users"] = users_list
                            if save_users(data, users_db):
                                message = f"Utilisateur {username} supprimé."
                                log(f"[USERS] Suppression utilisateur {username}", app.config["LOG_FILE"])
                            else:
                                error = "Erreur lors de la suppression."

        # Recharger après modifications
        data = load_users(users_db)
        users_list = data.get("users", [])

        rows = []
        for u in users_list:
            rows.append(
                f"""
                <tr>
                  <td style="padding:6px 8px;border-bottom:1px solid #30363d">{u.get("username")}</td>
                  <td style="padding:6px 8px;border-bottom:1px solid #30363d">{u.get("role")}</td>
                  <td style="padding:6px 8px;border-bottom:1px solid #30363d;text-align:right">
                    <form method="post" style="display:inline" onsubmit="return confirm('Supprimer {u.get("username")} ?');">
                      <input type="hidden" name="action" value="delete">
                      <input type="hidden" name="username" value="{u.get("username")}">
                      <button style="background:#f85149;color:#fff;border:none;border-radius:6px;padding:4px 8px;cursor:pointer;font-size:.85em;">Supprimer</button>
                    </form>
                  </td>
                </tr>
            """
            )

        html = f"""
        <html lang="fr">
        <head>
          <meta charset="utf-8">
          <title>Utilisateurs</title>
          <style>
            body {{
              background:#0d1117;
              color:#c9d1d9;
              font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif;
              padding:16px;
            }}
            .container {{ max-width:800px; margin:auto; }}
            .card {{
              background:#161b22;
              border:1px solid #30363d;
              border-radius:12px;
              padding:16px;
              margin-top:12px;
            }}
            h1 {{ color:#58a6ff; font-size:1.6em; margin-bottom:8px; }}
            table {{ width:100%; border-collapse:collapse; margin-top:10px; }}
            th {{
              text-align:left;
              padding:6px 8px;
              border-bottom:1px solid #30363d;
              font-weight:600;
            }}
            label {{
              display:block;
              margin-top:10px;
              font-size:.9em;
              color:#8b949e;
            }}
            input, select {{
              width:100%;
              padding:8px;
              margin-top:4px;
              border-radius:8px;
              border:1px solid #30363d;
              background:#0d1117;
              color:#c9d1d9;
            }}
            .btn {{
              margin-top:12px;
              padding:10px 14px;
              border-radius:8px;
              border:none;
              background:#58a6ff;
              color:#fff;
              font-weight:600;
              cursor:pointer;
            }}
            .msg-ok {{ color:#3fb950; margin-top:8px; font-size:.9em; }}
            .msg-err {{ color:#f85149; margin-top:8px; font-size:.9em; }}
          </style>
        </head>
        <body>
          <div class="container">
            {topbar_html(active="/users")}
            <div class="card">
              <h1>Gestion des utilisateurs</h1>
              {"<div class='msg-ok'>"+message+"</div>" if message else ""}
              {"<div class='msg-err'>"+error+"</div>" if error else ""}
              <h3>Utilisateurs existants</h3>
              <table>
                <thead>
                  <tr>
                    <th>Nom</th>
                    <th>Rôle</th>
                    <th style="text-align:right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {"".join(rows) if rows else "<tr><td colspan='3' style='padding:8px 0;color:#8b949e'>Aucun utilisateur.</td></tr>"}
                </tbody>
              </table>
            </div>

            <div class="card">
              <h3>Ajouter un utilisateur</h3>
              <form method="post">
                <input type="hidden" name="action" value="add">
                <label>Nom d'utilisateur</label>
                <input name="new_username" required>

                <label>Mot de passe</label>
                <input type="password" name="new_password" required>

                <label>Rôle</label>
                <select name="role">
                  <option value="user">user (limité)</option>
                  <option value="admin">admin (complet)</option>
                </select>

                <button type="submit" class="btn">Ajouter</button>
              </form>
            </div>
          </div>
        </body>
        </html>
        """
        return render_template_string(html)
