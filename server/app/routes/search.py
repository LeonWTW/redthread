"""Semantic search route (M5 task 5.1, plan 001).

GET /api/search embeds the query text with the SAME embedding provider used
for indexing, runs a cosine top-k search against the Qdrant "posts"
collection, joins the hits back to PostgreSQL, and returns Library cards in
Qdrant score order. Queries are embedded as-is; documents were embedded as
the pinned bilingual concat (see pipeline.tasks.embed_post), so zh and en
queries both land in the same space.

Posts present in Qdrant but missing in PostgreSQL (e.g. deleted mid-flight)
are skipped silently — the vector store is a derived index, never the truth.
"""

from __future__ import annotations

import uuid

from flask import Blueprint, jsonify, request
from sqlalchemy.orm import selectinload

from app import vectors
from app.db import SessionLocal, get_engine
from app.models import Post
from app.providers import registry
from app.providers.base import ProviderConfigError, ProviderError
from app.routes.posts import _annotation_json, _post_card
from app.security import session_required

search_bp = Blueprint("search", __name__, url_prefix="/api")

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 50


@search_bp.get("/search")
@session_required
def search_posts():
    q = request.args.get("q", default="")
    if not q.strip():
        return jsonify(error="q must be a non-empty query"), 400
    limit = request.args.get("limit", default=_DEFAULT_LIMIT, type=int)
    limit = max(1, min(limit if limit is not None else _DEFAULT_LIMIT, _MAX_LIMIT))

    try:
        vector = registry.get_embedding_provider().embed(q)
    except ProviderConfigError:
        return jsonify(error="embedding provider not configured — check .env"), 503
    except ProviderError:
        # Transient/rejection failures on the query embed: the analyst just
        # retries the search; never a 500.
        return jsonify(error="embedding provider temporarily unavailable — try again"), 503

    vectors.ensure_collection()  # an empty corpus searches to [], not a 404
    hits = vectors.get_client().query_points(
        collection_name=vectors.COLLECTION_NAME,
        query=vector,
        limit=limit,
        with_payload=True,
    ).points

    # Preserve Qdrant score order; point id == post UUID (payload is backup).
    ordered_ids: list[uuid.UUID] = []
    scores: dict[uuid.UUID, float] = {}
    for hit in hits:
        raw_id = (hit.payload or {}).get("post_id") or hit.id
        try:
            post_id = uuid.UUID(str(raw_id))
        except ValueError:
            continue
        if post_id not in scores:
            ordered_ids.append(post_id)
            scores[post_id] = hit.score

    get_engine()
    session = SessionLocal()
    posts_by_id: dict[uuid.UUID, Post] = {}
    if ordered_ids:
        rows = (
            session.query(Post)
            .options(selectinload(Post.images), selectinload(Post.annotation))
            .filter(Post.id.in_(ordered_ids))
            .all()
        )
        posts_by_id = {post.id: post for post in rows}

    results = []
    for post_id in ordered_ids:
        post = posts_by_id.get(post_id)
        if post is None:
            continue  # in Qdrant but not in PG: skip silently
        card = _post_card(post)
        card["annotation"] = _annotation_json(post)
        card["score"] = scores[post_id]
        results.append(card)
    return jsonify(results=results, query=q)
