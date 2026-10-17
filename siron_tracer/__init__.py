"""Siron SQL Tracer - find which Oracle tables a Siron AML screen uses by
reading the audit trail of the Siron database user."""
from __future__ import annotations

from typing import Optional

from flask import Flask

from .config import Settings, load_settings
from .oracle import Oracle
from .store import Store


def create_app(settings: Optional[Settings] = None, oracle=None, store=None) -> Flask:
    settings = settings or load_settings()
    app = Flask(__name__)
    app.config["SECRET_KEY"] = settings.secret_key
    app.extensions["siron"] = {
        "settings": settings,
        "oracle": oracle or Oracle(settings),
        "store": store or Store(settings.sqlite_path),
    }
    from .views import bp
    app.register_blueprint(bp)
    return app
