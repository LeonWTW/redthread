"""RedThread Flask application factory."""

from __future__ import annotations

import os

from flask import Flask, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Shared limiter; attached to the app in create_app. routes/auth.py applies
# the per-endpoint login limit (CLAUDE.md §6: rate-limit the login endpoint).
limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")


def create_app(config_overrides: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("FLASK_SECRET_KEY", "dev-only-insecure"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30,  # 30 days (kickoff decision 11)
        MAX_CONTENT_LENGTH=15 * 1024 * 1024,  # 15 MB per file (kickoff decision 9)
    )
    if config_overrides:
        app.config.update(config_overrides)

    limiter.init_app(app)

    from . import db

    db.init_app(app)

    from .routes.auth import auth_bp
    from .routes.capture import capture_bp
    from .routes.media import media_bp
    from .routes.posts import posts_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(capture_bp)
    app.register_blueprint(posts_bp)
    app.register_blueprint(media_bp)

    @app.get("/healthz")
    def healthz():
        return jsonify(status="ok")

    return app
