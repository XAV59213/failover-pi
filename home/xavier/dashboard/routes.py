from flask import render_template_string, send_file, request, redirect, url_for, session
import json
from datetime import datetime
import os
import subprocess
import time
import zipfile
import shutil

from .utils import (log, get_gateway, get_signal, get_logs, list_backups, get_freebox_history, check_dependencies, load_config, save_config)
from .auth import login_required, admin_required, load_users, save_users, make_password, check_password, verify_credentials, count_admins

def success_page(title, msg, color="#3fb950", btn_color="#58a6ff"):
    return f"""<div style="text-align:center;padding:40px;color:#fff;background:#0d1117;height:100vh">
        <h2 style="color:{color}">{title}</h2>
        <p style="color:#8b949e">{msg}</p>
        <button onclick="location.href='/'" style="background:{btn_color};color:#fff;padding:12px 24px;border:none;border-radius:8px;margin-top:20px;cursor:pointer">Retour</button></div>"""

def error_page(title, msg):
    return success_page(title, msg, color="#f85149", btn_color="#f85149")

def topbar_html(active=""):
    username = session.get("user", {}).get("username", "")
    items = [
        ('/', 'Dashboard'),
        ('/diagnostics', 'Diagnostics'),
        ('/config', 'Configuration'),
        ('/account', 'Mon compte'),
        ('/users', 'Utilisateurs') if session.get("user",{}).get("role")=="admin" else None,
        ('/logout', 'Déconnexion')
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
    @app.route("/setup", methods=["GET", "POST"])
    def setup():
        users_db = app.config['USERS_DB']
        if admin_exists(users_db):
            return redirect(url_for("login"))
        error = ""
        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            confirm  = request.form.get("confirm") or ""
            if not username or not password:
                error = "Utilisateur et mot de passe requis."
            elif password != confirm:
                error = "Les mots de passe ne correspondent pas."
            else:
                data = load_users(users_db)
                if any(u.get("username") == username for u in data.get("users", [])):
                    error = "Ce nom d'utilisateur existe déjà."
                else:
                    data.setdefault("users", []).append({
                        "username": username,
                        "password": make_password(password),
                        "role": "admin"
                    })
                    if save_users(data, users_db):
                        log(f"[AUTH] Admin créé: {username}", app.config['LOG_FILE'])
                        return redirect(url_for("login"))
                    error = "Impossible d'enregistrer l'utilisateur."
        html = f"""
        <html lang="fr"><head><meta charset="utf-8"><title>Créer admin</title>
        <style>
        body {{ background:#0d1117; color:#c9d1d9; font-family:system-ui; display:flex; align-items:center; justify-content:center; height:100vh; }}
        .card {{ background:#161b22; border:1px solid #30363d; border-radius:12px; padding:24px; width:360px; }}
        input {{ width:100%; padding:10px; margin:8px 0; border-radius:8px; border:1px solid #30363d; background:#0d1117; color:#c9d1d9; }}
        button {{ width:100%; padding:12px; background:#58a6ff; color:#fff; border:none; border-radius:8px; font-weight:700; cursor:pointer; }}
        .title {{ text-align:center; color:#58a6ff; margin-bottom:14px; }}
        .error {{ color:#f85149; margin:8px 0; font-size:.9em; }}
        </style></head><body>
        <div class="card">
          <div class="title">Créer un compte admin</div>
          {"<div class='error'>"+error+"</div>" if error else ""}
          <form method="post">
            <input name="username" placeholder="Nom d'utilisateur (ex: admin)" autocomplete="username" required>
            <input name="password" type="password" placeholder="Mot de passe" autocomplete="new-password" required>
            <input name="confirm" type="password" placeholder="Confirmer le mot de passe" autocomplete="new-password" required>
            <button type="submit">Créer l'admin</button>
          </form>
        </div></body></html>
        """
        return render_template_string(html)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        users_db = app.config['USERS_DB']
        if not admin_exists(users_db):
            return redirect(url_for("setup"))
        error = ""
        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            user = verify_credentials(username, password, users_db)
            if user:
                session["user"] = {"username": user["username"], "role": user.get("role", "admin")}
                log(f"[AUTH] Connexion: {user['username']}", app.config['LOG_FILE'])
                return redirect(url_for("index"))
            else:
                error = "Identifiants invalides."
        html = f"""
        <html lang="fr"><head><meta charset="utf-8"><title>Connexion</title>
        <style>
        body {{ background:#0d1117; color:#c9d1d9; font-family:system-ui; display:flex; align-items:center; justify-content:center; height:100vh; }}
        .card {{ background:#161b22; border:1px solid #30363d; border-radius:12px; padding:24px; width:360px; }}
        input {{ width:100%; padding:10px; margin:8px 0; border-radius:8px; border:1px solid #30363d; background:#0d1117; color:#c9d1d9; }}
        button {{ width:100%; padding:12px; background:#58a6ff; color:#fff; border:none; border-radius:8px; font-weight:700; cursor:pointer; }}
        .title {{ text-align:center; color:#58a6ff; margin-bottom:14px; }}
        .error {{ color:#f85149; margin:8px 0; font-size:.9em; }}
        .hint {{ font-size:.85em; color:#8b949e; text-align:center; margin-top:8px; }}
        </style></head><body>
        <div class="card">
          <div class="title">Connexion au Dashboard</div>
          {"<div class='error'>"+error+"</div>" if error else ""}
          <form method="post">
            <input name="username" placeholder="Nom d'utilisateur" autocomplete="username" required>
            <input name="password" type="password" placeholder="Mot de passe" autocomplete="current-password" required>
            <button type="submit">Se connecter</button>
          </form>
          <div class="hint"><a href="/setup" style="color:#58a6ff">Créer un admin</a> (si aucun compte).</div>
        </div></body></html>
        """
        return render_template_string(html)

    @app.route("/logout")
    def logout():
        u = session.get("user", {}).get("username", "?")
        session.clear()
        log(f"[AUTH] Déconnexion: {u}", app.config['LOG_FILE'])
        return redirect(url_for("login"))

    @app.route('/')
    @login_required
    def index():
        gateway, color = get_gateway(app.config['CONFIG_FILE'])
        log(f"[DASHBOARD] {gateway}", app.config['LOG_FILE'])
        signal, percent, _ = get_signal()
        logs = get_logs(app.config['LOG_FILE'])
        backups = list_backups(app.config['BACKUP_DIR'])
        times, states = get_freebox_history(app.config['LOG_FILE'])
        current_time = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        backups_html = ''.join([
            f'<div class="backup-item">'
            f'<a href="/download_backup/{b}" style="color:#58a6ff">{b}</a> '
            f'<button onclick="if(confirm('Restaurer {b} et redémarrer Pi ?')) location.href='/restore_existing/{b}'" '
            f'style="background:#3fb950;color:#fff;padding:4px 8px;border:none;border-radius:4px;margin-left:10px;cursor:pointer">Restaurer</button> '
            f'<button onclick="if(confirm('Supprimer {b} ?')) location.href='/delete_backup/{b}'" '
            f'style="background:#f85149;color:#fff;padding:4px 8px;border:none;border-radius:4px;margin-left:10px;cursor:pointer">Supprimer</button>'
            f'</div>'
            for b in backups
        ])

        html = f"""
        <!DOCTYPE html>
        <html lang="fr">
        <head>
          <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
          <title>Failover Pi - Dashboard</title>
          <style>
            :root {{ --bg:#0d1117; --card:#161b22; --text:#c9d1d9; --accent:#58a6ff; --danger:#f85149; --warning:#f0883e; --success:#3fb950; }}
            * {{ margin:0; padding:0; box-sizing:border-box; }}
            body {{ background:var(--bg); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif; padding:16px; }}
            .container {{ max-width:980px; margin:auto; }}
            h1 {{ text-align:center; color:var(--accent); font-size:1.8em; margin:20px 0; }}
            .topbar {{ display:flex; justify-content:space-between; align-items:center; font-size:.9em; color:#8b949e; margin-bottom:8px; }}
            .card {{ background:var(--card); border:1px solid #30363d; border-radius:12px; padding:16px; margin:12px 0; }}
            .status {{ font-size:1.4em; text-align:center; padding:12px; }}
            .led {{ width:20px; height:20px; border-radius:50%; display:inline-block; margin-right:10px; background:{color}; box-shadow:0 0 10px {color}; }}
            .signal {{ margin:10px 0; }}
            .bar {{ height:18px; background:#21262d; border-radius:9px; overflow:hidden; }}
            .fill {{ height:100%; background:linear-gradient(90deg,#f85149,#f0883e,#3fb950); width:{percent}%; transition:width .6s; }}
            .btn {{ border:none; padding:12px 18px; margin:6px; border-radius:8px; cursor:pointer; font-weight:600; width:100%; transition:.2s; }}
            .btn:hover {{ opacity:.9; transform:translateY(-1px); }}
            .btn-primary {{ background:var(--accent); color:#fff; }}
            .btn-danger {{ background:var(--danger); color:#fff; }}
            .btn-warning {{ background:var(--warning); color:#fff; }}
            .btn-success {{ background:var(--success); color:#fff; }}
            .btn-secondary {{ background:#30363d; color:#c9d1d9; }}
            .log {{ background:#010409; padding:8px; border-radius:6px; font-family:monospace; font-size:.85em; margin:4px 0; color:#8b949e; }}
            .log strong {{ color:#58a6ff; }}
            .time {{ font-size:.75em; color:#8b949e; text-align:center; margin-top:20px; }}
            .backup-list {{ max-height:150px; overflow-y:auto; }}
            .backup-item {{ padding:8px; border-bottom:1px solid #30363d; font-size:.9em; }}
            @media (min-width:600px) {{ .btn {{ width:auto; }} }}
          </style>
          <script> setInterval(()=>location.reload(),10000) </script>
        </head>
        <body><div class="container">
          {topbar_html(active="/")}
          <h1>Failover Dashboard Pro</h1>
          <div class="time">Mise à jour : {current_time}</div>
          <div class="card"><div class="status"><div class="led"></div> <strong>{gateway}</strong></div></div>
          <div class="card"><div class="signal"><strong>Signal 4G :</strong> {signal}</div><div class="bar"><div class="fill"></div></div></div>
          <div class="card">
            <button class="btn btn-primary" onclick="fetch('/sms').then(r=>r.text()).then(t=>document.body.innerHTML=t)">Envoyer SMS Test</button>
            <button class="btn btn-warning" onclick="fetch('/reboot').then(r=>r.text()).then(t=>document.body.innerHTML=t)">Redémarrer 4G</button>
          </div>
          <div class="card">
            <button class="btn btn-danger" onclick="if(confirm('Confirmer REBOOT Pi ?')) fetch('/reboot_pi').then(r=>r.text()).then(t=>document.body.innerHTML=t)">Reboot Pi</button>
            <button class="btn btn-danger" onclick="if(confirm('Confirmer ARRET Pi ?')) fetch('/shutdown').then(r=>r.text()).then(t=>document.body.innerHTML=t)">Shutdown Pi</button>
          </div>
          <div class="card">
            <button class="btn btn-success" onclick="fetch('/backup').then(r=>r.text()).then(t=>document.body.innerHTML=t)">Backup Système</button>
            <button class="btn btn-success" onclick="document.getElementById('restore-form').style.display='block'">Restaurer Backup</button>
          </div>
          <div class="card" id="restore-form" style="display:none">
            <form action="/restore" method="post" enctype="multipart/form-data">
              <input type="file" name="backup_file" accept=".zip" required style="margin:10px 0; color:#c9d1d9">
              <button type="submit" class="btn btn-success" onclick="return confirm('Restaurer et redémarrer le Pi ?')">Restaurer & Reboot</button>
            </form>
            <div class="backup-list"><strong>Derniers backups :</strong>
              {backups_html}
            </div>
          </div>
          <div class="card">
            <button class="btn btn-secondary" onclick="fetch('/test_failover').then(r=>r.text()).then(t=>document.body.innerHTML=t)">Test Failover</button>
            <button class="btn btn-secondary" onclick="fetch('/clear_logs').then(r=>r.text()).then(t=>document.body.innerHTML=t)">Clear Logs</button>
          </div>
          <div class="card">
            <strong>Logs en direct</strong>
            <div>{''.join([f'<div class="log"><strong>{l.split("] ")[0][1:]}</strong> {l.split("] ",1)[1] if "] " in l else l}</div>' for l in logs])}</div>
          </div>
          <div class="card">
            <h3 style="text-align:center;color:#58a6ff">État Freebox (24 h)</h3>
            <canvas id="freeboxChart" height="120"></canvas>
          </div>
          <div class="time">Auto-refresh toutes les 10 sec</div>
        </div>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <script>
          const fbCtx = document.getElementById('freeboxChart').getContext('2d');
          const fbTimes = {json.dumps(times)};
          const fbStates = {json.dumps(states)};
          new Chart(fbCtx, {{
            type: 'line',
            data: {{ labels: fbTimes, datasets: [{{ label:'État réseau (1=Freebox,0=4G)', data: fbStates, fill:true, borderColor:'#58a6ff', backgroundColor:'rgba(88,166,255,0.2)', tension:0.3, pointRadius:0 }}] }},
            options: {{ responsive:true,
              scales: {{
                y: {{ beginAtZero:true, suggestedMax:1, ticks: {{ stepSize:1, callback:v=>v===1?'Freebox':(v===0?'4G':v) }} }},
                x: {{ ticks: {{ maxRotation:90, minRotation:45, autoSkip:true, maxTicksLimit:12 }} }}
              }},
              plugins: {{ legend: {{ display:false }} }}
            }}
          }});
        </script>
        </body></html>
        """
        return render_template_string(html)

    @app.route('/sms')
    @login_required
    def sms():
        msg = f"Test dashboard OK ! ({datetime.now().strftime('%d/%m/%Y')})"
        log_entry = log(f"[DASHBOARD] SMS Test → {msg}", app.config['LOG_FILE'])
        try:
            subprocess.run(["python3", app.config['SMS_SCRIPT'], msg], cwd="/home/xavier", timeout=10)
            return success_page("SMS Envoyé !", log_entry, color="#3fb950", btn_color="#58a6ff")
        except Exception as e:
            error = log(f"[DASHBOARD] Erreur SMS: {e}", app.config['LOG_FILE'])
            return error_page("Échec SMS", error)

    @app.route('/diagnostics')
    @login_required
    def diagnostics():
        checks = check_dependencies(app.config)
        ok_count = sum(1 for c in checks if c["ok"])
        total = len(checks)
        html_rows = []
        for c in checks:
            badge = "<span style='color:#3fb950'>OK</span>" if c["ok"] else "<span style='color:#f85149'>KO</span>"
            detail = c["detail"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") if c["detail"] else ""
            html_rows.append(f"""
                <tr>
                  <td style="padding:8px 12px;border-bottom:1px solid #30363d">{c['name']}</td>
                  <td style="padding:8px 12px;border-bottom:1px solid #30363d;text-align:center">{badge}</td>
                  <td style="padding:8px 12px;border-bottom:1px solid #30363d;font-family:monospace;color:#8b949e">{detail}</td>
                </tr>
            """)
        html = f"""
        <html lang="fr"><head><meta charset="utf-8">
        <title>Diagnostics</title>
        <style>
          :root {{ --bg:#0d1117; --card:#161b22; --text:#c9d1d9; --accent:#58a6ff; }}
          body {{ background:var(--bg); color:var(--text); font-family:-apple-system,Segoe UI,Arial; padding:16px; }}
          .container {{ max-width:980px; margin:auto; }}
          .card {{ background:#161b22; border:1px solid #30363d; border-radius:12px; padding:16px; margin:12px 0; }}
          h1 {{ color:var(--accent); font-size:1.6em; margin:8px 0 12px; }}
          table {{ width:100%; border-collapse:collapse; }}
          .topbar {{ display:flex; justify-content:space-between; align-items:center; font-size:.9em; color:#8b949e; margin-bottom:8px; }}
          .btn {{ padding:10px 14px; background:#58a6ff; color:#fff; border:none; border-radius:8px; font-weight:700; cursor:pointer; text-decoration:none; }}
        </style></head>
        <body><div class="container">
          {topbar_html(active="/diagnostics")}
          <div class="card">
            <h1>Diagnostics</h1>
            <div style="margin-bottom:10px">Résumé : <strong>{ok_count}/{total} OK</strong></div>
            <div style="margin-bottom:12px"><a class="btn" href="/diagnostics">Rafraîchir</a></div>
            <div style="overflow:auto">
              <table>
                <thead>
                  <tr>
                    <th style="text-align:left;padding:8px 12px;border-bottom:1px solid #30363d">Vérification</th>
                    <th style="text-align:center;padding:8px 12px;border-bottom:1px solid #30363d">État</th>
                    <th style="text-align:left;padding:8px 12px;border-bottom:1px solid #30363d">Détails</th>
                  </tr>
                </thead>
                <tbody>
                  {"".join(html_rows)}
                </tbody>
              </table>
            </div>
          </div>
        </div></body></html>
        """
        return render_template_string(html)

    # Ajoutez les autres routes ici, en utilisant les codes fournis dans les messages précédents pour compléter.
