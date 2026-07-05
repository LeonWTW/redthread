"""Perceptual-hash helpers (M2 capture hardening).

post_images.perceptual_hash is a Postgres BIGINT (signed 64-bit), so the
unsigned 64-bit pHash is stored two's-complement: values >= 2**63 have 2**64
subtracted. Near-duplicate detection is an app-side scan over all existing
hashes with a Hamming-distance threshold; warnings are SOFT — capture always
succeeds and the analyst decides.
"""

from __future__ import annotations

import io

import imagehash
from PIL import Image

HAMMING_THRESHOLD = 8


class UnreadableImageError(ValueError):
    """Raised when image bytes cannot be decoded by PIL."""


def to_signed_64(value: int) -> int:
    """Map an unsigned 64-bit int onto the signed BIGINT range."""
    return value - 2**64 if value >= 2**63 else value


def to_unsigned_64(value: int) -> int:
    """Inverse of to_signed_64."""
    return value + 2**64 if value < 0 else value


def compute_phash_signed(image_bytes: bytes) -> int:
    """Compute the 64-bit imagehash.phash of image bytes as a signed 64-bit int."""
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            unsigned = int(str(imagehash.phash(image)), 16)
    except Exception as exc:
        raise UnreadableImageError(f"could not decode image: {exc}") from exc
    return to_signed_64(unsigned)


def hamming_distance(a: int, b: int) -> int:
    """Hamming distance between two signed-64 stored hashes."""
    return bin(to_unsigned_64(a) ^ to_unsigned_64(b)).count("1")


def find_near_duplicates(
    session, signed_hash: int, threshold: int = HAMMING_THRESHOLD
) -> list[dict]:
    """Scan ALL existing post_images hashes; return matches within threshold.

    Returns [{"post_id", "image_id", "distance"}, ...] sorted by distance.
    Call BEFORE inserting the new image row so it never matches itself.
    """
    from app.models import PostImage

    rows = (
        session.query(PostImage.id, PostImage.post_id, PostImage.perceptual_hash)
        .filter(PostImage.perceptual_hash.isnot(None))
        .all()
    )
    matches = [
        {"post_id": str(post_id), "image_id": str(image_id), "distance": distance}
        for image_id, post_id, stored in rows
        if (distance := hamming_distance(signed_hash, stored)) <= threshold
    ]
    matches.sort(key=lambda m: m["distance"])
    return matches
