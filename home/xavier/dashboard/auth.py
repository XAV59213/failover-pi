import json
import hashlib
import secrets
import base64
import os
from functools import wraps
from flask import redirect, url_for, session, request

# Routes publiques
ALLOWED_ENDPOINTS_NO_AUTH = {"setup", "login", "static"}


# ============================================================
#  Gestion des utilisateurs
# ============================================================

def load_users(users_db: str):
    if not os.path.exists(users_db):
        return {"users": []}
    try:
        with open(users_db, "r") as f:
            return json.load(f)
    except Exception:
        return {"users": []}


def save_users(data, users_db: str):
    try:
        tmp = users_db + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, users_db)
        return True
    except Exception:
        return False


# ============================================================
#  Sécurité des mots de passe
# ============================================================

def make_password(plain: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.sha256(salt + plain.encode("utf-8")).hexdigest()
    return "sha256$" + base64.b64encode(salt).decode() + "$" + h


def check_password(stored: str, plain: str) -> bool:
    try:
        algo, salt_b64, h_hex = stored.split("$", 2)
        if algo != "sha256":
            return False
        salt = base64.b64decode(salt_b64.encode())
        h2 = hashlib.sha256(salt + plain.encode("utf-8")).hexdigest()
        return h2 == h_hex
    except Exception:
        return False


# ============================================================
#  Vérifications comptes / rôles
# ============================================================

def admin_exists(users_db: str):
    data = load_users(users_db)
    return any(u.get("role") == "admin" for u in data.get("users", []))


def verify_credentials(username, password, users_db: str):
    data = load_users(users_db)
    for u in data.get("users", []):
        if u.get("username") == username and check_password(u.get("password", ""), password):
            return u
    return None


def count_admins(users_db: str):
    data = load_users(users_db)
    return sum(1 for u in data.get("users", []) if u.get("role") == "admin")


# ============================================================
#  Décorateurs simples
# ============================================================

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = session.get("user")
        if not user or user.get("role") != "admin":
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return wrapper


# ============================================================
#  Garde globale (before_request)
# ============================================================

def register_auth_guards(app):

    @app.before_request
    def enforce_auth():
        endpoint = (request.endpoint or "")
        path = request.path or "/"

        # 1) Routes publiques
        if endpoint in ALLOWED_ENDPOINTS_NO_AUTH:
            return

        # 2) Tant qu'il n'y a pas d'admin → forcer /setup
        if not admin_exists(app.config["USERS_DB"]):
            if endpoint != "setup":
                return redirect(url_for("setup"))
            return

        # 3) Si pas connecté → login
        if not session.get("user"):
            return redirect(url_for("login"))

        # 4) Restrictions pour le rôle "user"
        user = session.get("user", {})
        if user.get("role") == "user":
            # Endpoints sensibles à bloquer pour les users simples
            blocked_endpoints = {
                # Diagnostics avancés
                "diagnostics",

                # Backups / restore
                "backup",
                "restore",
                "restore_existing",
                "delete_backup",

                # Gestion utilisateurs
                "users",

                # Config réseau / modem
                "edit_config",

                # Actions système (Pi)
                "reboot_pi",
                "shutdown_pi",

                # Logs
                "clear_logs",
            }

            # Patterns d'URL sensibles (sécurité supplémentaire)
            blocked_paths_prefix = (
                "/backup",
                "/restore",
                "/delete_backup",
                "/users",
                "/config",
                "/reboot_pi",
                "/shutdown",
                "/clear_logs",
            )

            # 4.a – endpoint explicitement bloqué
            if endpoint in blocked_endpoints:
                return redirect(url_for("index"))

            # 4.b – ou chemin qui commence par un préfixe sensible
            for pref in blocked_paths_prefix:
                if path.startswith(pref):
                    return redirect(url_for("index"))
