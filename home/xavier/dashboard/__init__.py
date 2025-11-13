from flask import Flask

# Création instance Flask
app = Flask(__name__)

# Chargement config
from .config import set_app_config
set_app_config(app)

# Authentification / gardes
from .auth import register_auth_guards
register_auth_guards(app)

# Routes principales
from .routes import register_routes
register_routes(app)
