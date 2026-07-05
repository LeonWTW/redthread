"""Post read routes (M1 task 1.5): full post record for the bilingual display."""

from __future__ import annotations

import uuid

from flask import Blueprint, jsonify

from app.db import SessionLocal, get_engine
from app.models import Post
from app.security import session_required

posts_bp = Blueprint("posts", __name__, url_prefix="/api")


@posts_bp.get("/posts/<uuid:post_id>")
@session_required
def get_post(post_id: uuid.UUID):
    get_engine()
    session = SessionLocal()
    post = session.get(Post, post_id)
    if post is None:
        return jsonify(error="post not found"), 404

    return jsonify(
        id=str(post.id),
        platform=post.platform,
        captured_at=post.captured_at.isoformat() if post.captured_at else None,
        caption_raw=post.caption_raw,
        full_ocr_text=post.full_ocr_text,
        corrected_text=post.corrected_text,
        machine_translation=post.machine_translation,
        final_translation=post.final_translation,
        entities=post.entities,
        ocr_status=post.ocr_status,
        translate_status=post.translate_status,
        extract_status=post.extract_status,
        embed_status=post.embed_status,
        ocr_error_type=post.ocr_error_type,
        ocr_error_message=post.ocr_error_message,
        translate_error_type=post.translate_error_type,
        translate_error_message=post.translate_error_message,
        extract_error_type=post.extract_error_type,
        extract_error_message=post.extract_error_message,
        embed_error_type=post.embed_error_type,
        embed_error_message=post.embed_error_message,
        images=[
            {
                "id": str(image.id),
                "sort_order": image.sort_order,
                "image_type": image.image_type,
                "url": "/media/" + image.file_path,
            }
            for image in post.images
        ],
    )
