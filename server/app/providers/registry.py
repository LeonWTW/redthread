"""Provider selection via environment (CLAUDE.md §6: selection via config/env).

Imports are lazy so an unconfigured provider only fails when actually used,
raising ProviderConfigError (error_type=config_error) for the Inbox to surface.
"""

from __future__ import annotations

import os
from functools import lru_cache

from .base import (
    EmbeddingProvider,
    ExtractionProvider,
    MediaStore,
    OCRProvider,
    ProviderConfigError,
    TranslationProvider,
)


@lru_cache(maxsize=None)
def get_ocr_provider() -> OCRProvider:
    name = os.environ.get("OCR_PROVIDER", "anthropic")
    if name == "anthropic":
        from .anthropic_providers import AnthropicOCRProvider

        return AnthropicOCRProvider()
    raise ProviderConfigError(f"unknown OCR_PROVIDER: {name}")


@lru_cache(maxsize=None)
def get_translation_provider() -> TranslationProvider:
    name = os.environ.get("TRANSLATION_PROVIDER", "anthropic")
    if name == "anthropic":
        from .anthropic_providers import AnthropicTranslationProvider

        return AnthropicTranslationProvider()
    raise ProviderConfigError(f"unknown TRANSLATION_PROVIDER: {name}")


@lru_cache(maxsize=None)
def get_extraction_provider() -> ExtractionProvider:
    name = os.environ.get("EXTRACTION_PROVIDER", "anthropic")
    if name == "anthropic":
        from .anthropic_providers import AnthropicExtractionProvider

        return AnthropicExtractionProvider()
    raise ProviderConfigError(f"unknown EXTRACTION_PROVIDER: {name}")


@lru_cache(maxsize=None)
def get_embedding_provider() -> EmbeddingProvider:
    name = os.environ.get("EMBEDDING_PROVIDER", "openai")
    if name == "openai":
        from .openai_embedding import OpenAIEmbeddingProvider

        return OpenAIEmbeddingProvider()
    raise ProviderConfigError(f"unknown EMBEDDING_PROVIDER: {name}")


@lru_cache(maxsize=None)
def get_media_store() -> MediaStore:
    from .media_local import LocalMediaStore

    return LocalMediaStore(os.environ.get("MEDIA_ROOT", "/data/media"))
