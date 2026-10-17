"""Siron SQL Tracer - find which Oracle tables and columns a Siron AML screen
uses by reading the audit trail of the Siron database users, and turn that
into a migration mapping."""
from __future__ import annotations

import secrets
from typing import Optional

from flask import Flask, abort, request, session

from .config import Settings, load_settings
from .jobs import JobRunner
from .oracle import Oracle
from .store import Store

__version__ = "2.0.0"


def create_app(settings: Optional[Settings] = None, oracle=None, store=None, sync_jobs: bool = False) -> Flask:
    settings = settings or load_settings()
    app = Flask(__name__)
    app.config["SECRET_KEY"] = settings.secret_key
    app.config["SESSION_COOKIE_SAMESITE"] = "Strict"
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # Excel uploads
    store = store or Store(settings.sqlite_path)
    app.extensions["siron"] = {
        "settings": settings,
        "oracle": oracle or Oracle(settings),
        "store": store,
        "jobs": JobRunner(store, sync=sync_jobs),
        "cache": {},
    }

    @app.before_request
    def _csrf():
        """Reject cross-site form posts (another web page posting to localhost)."""
        if request.method != "POST" or app.testing:
            return
        token = session.get("_csrf")
        sent = request.form.get("_csrf") or request.headers.get("X-CSRF-Token")
        if not token or not sent or not secrets.compare_digest(token, sent):
            abort(400, "Oturum doğrulaması başarısız (CSRF). Sayfayı yenileyip tekrar deneyin.")

    def csrf_token() -> str:
        if "_csrf" not in session:
            session["_csrf"] = secrets.token_urlsafe(24)
        return session["_csrf"]

    app.jinja_env.globals["csrf_token"] = csrf_token
    app.jinja_env.globals["app_version"] = __version__

    from .views import bp
    app.register_blueprint(bp)
    return app
