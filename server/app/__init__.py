"""RedThread Flask application factory."""

from __future__ import annotations

import os

from flask import Flask, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Shared limiter; attached to the app in create_app. routes/auth.py applies
# the per-endpoint login limit (CLAUDE.md §6: rate-limit the login endpoint).
# Backed by Redis when available so the limit is shared across gunicorn
# workers and survives restarts (M8 security finding 6).
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=os.environ.get("REDIS_URL", "memory://"),
)


def create_app(config_overrides: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("FLASK_SECRET_KEY"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30,  # 30 days (kickoff decision 11)
        # Flask enforces this per REQUEST, not per file; the sequential mobile
        # uploader sends one file per request so this equals the 15 MB/file
        # limit of kickoff decision 9 (batch multipart captures share it —
        # conservative direction).
        MAX_CONTENT_LENGTH=15 * 1024 * 1024,
    )
    if config_overrides:
        app.config.update(config_overrides)

    # A forgeable session cookie is a full auth bypass: refuse to boot without
    # a real secret outside of tests (M8 security finding 1).
    if not app.config["SECRET_KEY"]:
        if not app.config.get("TESTING"):
            raise RuntimeError(
                "FLASK_SECRET_KEY is not set; refusing to start with a "
                "forgeable session secret. Set it in .env."
            )
        app.config["SECRET_KEY"] = "test-only-secret"

    limiter.init_app(app)

    from . import db

    db.init_app(app)

    from .routes.auth import auth_bp
    from .routes.capture import capture_bp
    from .routes.export import export_bp
    from .routes.media import media_bp
    from .routes.posts import posts_bp
    from .routes.reports import reports_bp
    from .routes.search import search_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(capture_bp)
    app.register_blueprint(posts_bp)
    app.register_blueprint(media_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(export_bp)
    app.register_blueprint(search_bp)

    @app.get("/healthz")
    def healthz():
        return jsonify(status="ok")

    return app
