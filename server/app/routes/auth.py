"""Auth routes: single analyst login/logout/session check (M1 task 1.2)."""

from __future__ import annotations

from flask import Blueprint, jsonify, request, session

from app import limiter
from app.security import verify_analyst

auth_bp = Blueprint("auth", __name__, url_prefix="/api")


@auth_bp.post("/login")
@limiter.limit("5 per minute; 20 per hour")
def login():
    payload = request.get_json(silent=True) or {}
    username = payload.get("username")
    password = payload.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        return jsonify(error="username and password are required"), 401
    if not verify_analyst(username, password):
        return jsonify(error="invalid credentials"), 401
    session.clear()
    session["analyst"] = True
    session.permanent = True
    return "", 204


@auth_bp.post("/logout")
def logout():
    session.clear()
    return "", 204


@auth_bp.get("/me")
def me():
    return jsonify(authenticated=bool(session.get("analyst")))
