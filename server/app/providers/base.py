"""Provider interfaces and error hierarchy (iron rule: interfaces before implementations).

Every external AI capability sits behind one of these interfaces, selected via
config/env in registry.py, so a provider can be swapped without touching
pipeline code. Provider errors map 1:1 onto the step error taxonomy stored in
posts.*_error_type (schema.sql: error_type enum).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


# --- Error hierarchy → error_type enum ---------------------------------------


class ProviderError(Exception):
    """Base for all provider failures. `error_type` matches the DB enum."""

    error_type = "provider_error"


class TransientProviderError(ProviderError):
    """Timeout / rate limit / 5xx. Auto-retried by the pipeline before surfacing."""

    error_type = "transient"


class ProviderRejectionError(ProviderError):
    """Provider 4xx or content refusal. Not auto-retried."""

    error_type = "provider_error"


class ProviderParseError(ProviderError):
    """Model output did not match the expected format."""

    error_type = "parse_error"


class ProviderConfigError(ProviderError):
    """Missing/invalid key or configuration. Retry is futile; the UI says so."""

    error_type = "config_error"


# --- Data shapes ---------------------------------------------------------------


@dataclass(frozen=True)
class GlossaryTerm:
    """A community term injected into translation prompts (e.g. 避雷, 平替)."""

    term_zh: str
    term_en: str
    note: str | None = None


@dataclass(frozen=True)
class Entity:
    """Extraction output (kickoff decision 15). Stored as JSONB on posts.

    `confidence` is a model self-reported heuristic in [0, 1], not a
    calibrated probability; displayed for entities only.
    """

    text_zh: str
    text_en: str
    type: str  # brand | product | ingredient | other
    confidence: float


# --- Interfaces ------------------------------------------------------------------


class OCRProvider(ABC):
    @abstractmethod
    def ocr_image(self, image_bytes: bytes, mime_type: str) -> str:
        """Return the raw text content of one screenshot image (Chinese preserved)."""


class TranslationProvider(ABC):
    @abstractmethod
    def translate(self, zh_text: str, glossary: list[GlossaryTerm]) -> str:
        """Translate aggregated post text to English.

        `zh_text` may contain a comment-section marker line; the translation
        must preserve that structure. Glossary terms must be rendered
        consistently per their term_en.
        """


class ExtractionProvider(ABC):
    @abstractmethod
    def extract(self, zh_text: str, en_text: str) -> list[Entity]:
        """Extract entities from the bilingual post record."""


class EmbeddingProvider(ABC):
    @property
    @abstractmethod
    def dimension(self) -> int:
        """Vector dimension; fixed per collection."""

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Embed one document (bilingual concat) or query string."""


class MediaStore(ABC):
    """Private media storage. Files are served ONLY through authenticated routes."""

    @abstractmethod
    def save(self, file_bytes: bytes, suggested_name: str) -> str:
        """Persist bytes; return the stable relative path stored in post_images.file_path."""

    @abstractmethod
    def open(self, relative_path: str) -> bytes:
        """Return file bytes for an authenticated response."""

    @abstractmethod
    def exists(self, relative_path: str) -> bool: ...

    @abstractmethod
    def delete(self, relative_path: str) -> None:
        """Remove one stored file. A missing file is a no-op (delete is
        idempotent so post deletion can be retried safely)."""
