from flask import Flask

app = Flask(__name__)

from .config import set_app_config
set_app_config(app)

from .auth import register_auth_guards
register_auth_guards(app)

from .routes import register_routes
register_routes(app)
