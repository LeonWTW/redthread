"""Authentication helpers.

Single analyst account seeded from env vars (no registration, no reset, no
user CRUD). Session cookie required on ALL routes including media; machine
clients use the long-lived API_TOKEN header on POST /api/capture only.
"""

from __future__ import annotations

import hmac
import os
from functools import wraps

from flask import jsonify, request, session


def verify_analyst(username: str, password: str) -> bool:
    expected_user = os.environ.get("ANALYST_USERNAME", "")
    expected_pass = os.environ.get("ANALYST_PASSWORD", "")
    if not expected_user or not expected_pass:
        return False
    return hmac.compare_digest(username, expected_user) and hmac.compare_digest(
        password, expected_pass
    )


def session_required(fn):
    """Analyst session required. Applied to every route except login/healthz."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("analyst"):
            return jsonify(error="authentication required"), 401
        return fn(*args, **kwargs)

    return wrapper


def session_or_token_required(fn):
    """Capture endpoint: analyst session OR X-API-Token header (machine clients)."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if session.get("analyst"):
            return fn(*args, **kwargs)
        token = request.headers.get("X-API-Token", "")
        expected = os.environ.get("API_TOKEN", "")
        if expected and token and hmac.compare_digest(token, expected):
            return fn(*args, **kwargs)
        return jsonify(error="authentication required"), 401

    return wrapper
