"""Authenticated media serving. NEVER a public static directory (CLAUDE.md §6)."""

from __future__ import annotations

import mimetypes

from flask import Blueprint, Response, jsonify

from app.providers import registry
from app.security import session_required

media_bp = Blueprint("media", __name__)


@media_bp.get("/media/<path:relpath>")
@session_required
def serve_media(relpath: str):
    # Resolve the store at request time (late binding) so tests can monkeypatch
    # registry.get_media_store without re-importing this module.
    store = registry.get_media_store()
    try:
        if not store.exists(relpath):
            return jsonify(error="file not found"), 404
        file_bytes = store.open(relpath)
    except ValueError:
        # Path escaping the media root (traversal attempt) — indistinguishable
        # from a missing file to the client.
        return jsonify(error="file not found"), 404
    mimetype = mimetypes.guess_type(relpath)[0] or "application/octet-stream"
    response = Response(file_bytes, mimetype=mimetype)
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
