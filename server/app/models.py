"""SQLAlchemy 2.0 declarative models.

schema.sql at the repo root is the single source of truth; these models conform
to it exactly. The app never creates or migrates tables — enum types and
server-side defaults already exist in the database, so ENUM columns use
create_type=False and defaults are mirrored as server_default text.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# ---------------------------------------------------------------------------
# Enum types (already created by schema.sql; never created from code)
# ---------------------------------------------------------------------------

step_status_enum = ENUM(
    "pending", "running", "success", "failed", "skipped",
    name="step_status", create_type=False,
)
error_type_enum = ENUM(
    "transient", "provider_error", "parse_error", "config_error", "storage_error",
    name="error_type", create_type=False,
)
image_type_enum = ENUM(
    "note_content", "comments", "other",
    name="image_type", create_type=False,
)
category_enum = ENUM(
    "skincare", "makeup", "haircare", "wellness",
    name="category", create_type=False,
)
trend_type_enum = ENUM(
    "ingredient", "routine", "pain_point", "product_format",
    "creator_format", "brand_move",
    name="trend_type", create_type=False,
)
consumer_signal_enum = ENUM(
    "bilei", "pingti", "chengfen_dang", "zhongcao", "qiuzhen",
    name="consumer_signal", create_type=False,
)
recommended_action_enum = ENUM(
    "monitor", "test_content", "seed_koc", "avoid",
    name="recommended_action", create_type=False,
)
origin_enum = ENUM(
    "china_native", "west_to_china", "pan_asian", "unclear",
    name="origin", create_type=False,
)
report_section_enum = ENUM(
    "brand_watch", "trend_radar", "not_crossing", "decoder", "seen_in_china",
    name="report_section", create_type=False,
)
crossover_verdict_enum = ENUM(
    "will_cross", "wont_cross", "watch",
    name="crossover_verdict", create_type=False,
)
report_status_enum = ENUM(
    "draft", "final",
    name="report_status", create_type=False,
)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# posts
# ---------------------------------------------------------------------------


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    platform: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'xhs'")
    )
    xhs_note_id: Mapped[Optional[str]] = mapped_column(Text)
    source_url: Mapped[Optional[str]] = mapped_column(Text)
    captured_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    caption_raw: Mapped[Optional[str]] = mapped_column(Text)

    # Post-level aggregates. Machine outputs (full_ocr_text, machine_translation)
    # are never overwritten; corrections live in corrected_text / final_translation.
    full_ocr_text: Mapped[Optional[str]] = mapped_column(Text)
    corrected_text: Mapped[Optional[str]] = mapped_column(Text)
    machine_translation: Mapped[Optional[str]] = mapped_column(Text)
    final_translation: Mapped[Optional[str]] = mapped_column(Text)

    entities: Mapped[Optional[Any]] = mapped_column(JSONB)

    ocr_status: Mapped[str] = mapped_column(
        step_status_enum, nullable=False, server_default=text("'pending'")
    )
    translate_status: Mapped[str] = mapped_column(
        step_status_enum, nullable=False, server_default=text("'pending'")
    )
    extract_status: Mapped[str] = mapped_column(
        step_status_enum, nullable=False, server_default=text("'pending'")
    )
    embed_status: Mapped[str] = mapped_column(
        step_status_enum, nullable=False, server_default=text("'pending'")
    )

    ocr_error_type: Mapped[Optional[str]] = mapped_column(error_type_enum)
    ocr_error_message: Mapped[Optional[str]] = mapped_column(Text)
    translate_error_type: Mapped[Optional[str]] = mapped_column(error_type_enum)
    translate_error_message: Mapped[Optional[str]] = mapped_column(Text)
    extract_error_type: Mapped[Optional[str]] = mapped_column(error_type_enum)
    extract_error_message: Mapped[Optional[str]] = mapped_column(Text)
    embed_error_type: Mapped[Optional[str]] = mapped_column(error_type_enum)
    embed_error_message: Mapped[Optional[str]] = mapped_column(Text)

    embedded_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        TIMESTAMP(timezone=True)
    )

    created_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )

    images: Mapped[list["PostImage"]] = relationship(
        back_populates="post",
        order_by="PostImage.sort_order",
        cascade="all, delete-orphan",
    )
    annotation: Mapped[Optional["Annotation"]] = relationship(
        back_populates="post", uselist=False, cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# post_images
# ---------------------------------------------------------------------------


class PostImage(Base):
    __tablename__ = "post_images"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    post_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    image_type: Mapped[str] = mapped_column(
        image_type_enum, nullable=False, server_default=text("'note_content'")
    )
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    # raw_ocr is the machine output and is never overwritten; corrections
    # belong to corrected_ocr (iron law #2).
    raw_ocr: Mapped[Optional[str]] = mapped_column(Text)
    corrected_ocr: Mapped[Optional[str]] = mapped_column(Text)
    perceptual_hash: Mapped[Optional[int]] = mapped_column(BigInteger)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )

    post: Mapped["Post"] = relationship(back_populates="images")


# ---------------------------------------------------------------------------
# annotations
# ---------------------------------------------------------------------------


class Annotation(Base):
    __tablename__ = "annotations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    post_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    category: Mapped[Optional[str]] = mapped_column(category_enum)
    trend_type: Mapped[Optional[str]] = mapped_column(trend_type_enum)
    consumer_signal: Mapped[Optional[str]] = mapped_column(consumer_signal_enum)
    recommended_action: Mapped[Optional[str]] = mapped_column(recommended_action_enum)
    origin: Mapped[Optional[str]] = mapped_column(origin_enum)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )

    post: Mapped["Post"] = relationship(back_populates="annotation")


# ---------------------------------------------------------------------------
# glossary
# ---------------------------------------------------------------------------


class GlossaryTerm(Base):
    __tablename__ = "glossary"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    term_zh: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    term_en: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )


# ---------------------------------------------------------------------------
# reports / report_blocks / report_citations
# ---------------------------------------------------------------------------


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    week_of: Mapped[Optional[datetime.date]] = mapped_column(Date)
    status: Mapped[str] = mapped_column(
        report_status_enum, nullable=False, server_default=text("'draft'")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )

    blocks: Mapped[list["ReportBlock"]] = relationship(
        back_populates="report",
        order_by="ReportBlock.sort_order",
        cascade="all, delete-orphan",
    )


class ReportBlock(Base):
    __tablename__ = "report_blocks"
    __table_args__ = (
        CheckConstraint("block_type IN ('claim', 'trend')"),
        CheckConstraint(
            "block_type <> 'claim' OR text_content IS NOT NULL",
            name="claim_has_text",
        ),
        CheckConstraint(
            "block_type <> 'trend' OR trend_title IS NOT NULL",
            name="trend_has_title",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("reports.id", ondelete="CASCADE"),
        nullable=False,
    )
    section: Mapped[str] = mapped_column(report_section_enum, nullable=False)
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    block_type: Mapped[str] = mapped_column(Text, nullable=False)
    parent_block_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("report_blocks.id", ondelete="CASCADE"),
    )
    text_content: Mapped[Optional[str]] = mapped_column(Text)
    trend_title: Mapped[Optional[str]] = mapped_column(Text)
    crossover: Mapped[Optional[Any]] = mapped_column(JSONB)
    crossover_verdict: Mapped[Optional[str]] = mapped_column(crossover_verdict_enum)
    created_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )

    report: Mapped["Report"] = relationship(back_populates="blocks")
    parent_block: Mapped[Optional["ReportBlock"]] = relationship(
        remote_side="ReportBlock.id"
    )
    citations: Mapped[list["ReportCitation"]] = relationship(
        back_populates="block", cascade="all, delete-orphan"
    )


class ReportCitation(Base):
    __tablename__ = "report_citations"
    __table_args__ = (UniqueConstraint("block_id", "post_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    block_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("report_blocks.id", ondelete="CASCADE"),
        nullable=False,
    )
    post_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("posts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )

    block: Mapped["ReportBlock"] = relationship(back_populates="citations")
    post: Mapped["Post"] = relationship()
