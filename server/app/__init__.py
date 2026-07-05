"""RedThread Flask application factory.

M0 scaffold: health check only. M1 adds auth, capture, media, and display routes.
"""

import os

from flask import Flask, jsonify


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

    @app.get("/healthz")
    def healthz():
        return jsonify(status="ok")

    return app
