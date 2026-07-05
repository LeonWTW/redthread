"""Qdrant vector-store wrapper (design note 002).

One collection "posts" (cosine, dim 1536), created on first use. Writes are
upserts keyed by the post UUID, so re-embedding replaces the point and
duplicates are impossible. Payload carries {"post_id"} only.
"""

from __future__ import annotations

import os

from qdrant_client import QdrantClient
from qdrant_client import models as qmodels

COLLECTION_NAME = "posts"
VECTOR_DIMENSION = 1536

_client: QdrantClient | None = None


def get_client() -> QdrantClient:
    """Return the process-wide Qdrant client (URL from QDRANT_URL env)."""
    global _client
    if _client is None:
        _client = QdrantClient(url=os.environ.get("QDRANT_URL", "http://qdrant:6333"))
    return _client


def ensure_collection(dim: int = VECTOR_DIMENSION) -> None:
    """Create the posts collection if missing. Idempotent and race-tolerant:
    a concurrent worker may create it between our check and our create; that
    conflict counts as success."""
    client = get_client()
    if client.collection_exists(COLLECTION_NAME):
        return
    try:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=qmodels.VectorParams(
                size=dim, distance=qmodels.Distance.COSINE
            ),
        )
    except Exception:
        if not client.collection_exists(COLLECTION_NAME):
            raise


def upsert_post(post_id: str, vector: list[float]) -> None:
    """Upsert one post vector; point id == post UUID (write idempotency)."""
    ensure_collection()
    get_client().upsert(
        collection_name=COLLECTION_NAME,
        points=[
            qmodels.PointStruct(
                id=post_id, vector=vector, payload={"post_id": post_id}
            )
        ],
    )


def delete_post(post_id: str) -> None:
    """Delete one post's point (Library delete in M5; test cleanup now)."""
    client = get_client()
    if not client.collection_exists(COLLECTION_NAME):
        return
    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=qmodels.PointIdsList(points=[post_id]),
    )
