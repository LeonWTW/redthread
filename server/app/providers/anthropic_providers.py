"""Anthropic-backed OCR, translation, and extraction providers.

Cost policy (locked): default to the cheapest vision-capable Haiku-class tier;
model IDs are overridable per step via env so eval-driven escalation never
requires a code change. The API key is read at call time, not import time, so
an unconfigured deployment fails with ProviderConfigError only when a step
actually runs.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

import anthropic

from .base import (
    Entity,
    ExtractionProvider,
    GlossaryTerm,
    OCRProvider,
    ProviderConfigError,
    ProviderParseError,
    ProviderRejectionError,
    TransientProviderError,
    TranslationProvider,
)

_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 4096

_ENTITY_TYPES = {"brand", "product", "ingredient", "other"}

_OCR_PROMPT = (
    "Transcribe ALL visible text in this image exactly as written.\n"
    "- Preserve Chinese characters as-is; do not translate.\n"
    "- Keep stickers and emoji as-is.\n"
    "- Read top to bottom, left to right.\n"
    "- Output the transcription only; no commentary, no headings."
)


def _get_client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ProviderConfigError("ANTHROPIC_API_KEY is not set")
    return anthropic.Anthropic(api_key=api_key)


def _create_message(client: anthropic.Anthropic, **kwargs: Any) -> Any:
    """Call messages.create, mapping SDK errors onto the ProviderError taxonomy."""
    try:
        return client.messages.create(**kwargs)
    except (
        anthropic.RateLimitError,
        anthropic.APITimeoutError,
        anthropic.APIConnectionError,
        anthropic.InternalServerError,
    ) as exc:
        raise TransientProviderError(str(exc)) from exc
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
        raise ProviderConfigError(str(exc)) from exc
    except anthropic.BadRequestError as exc:
        raise ProviderRejectionError(str(exc)) from exc


def _response_text(message: Any) -> str:
    parts = [
        block.text
        for block in message.content
        if getattr(block, "type", None) == "text"
    ]
    return "\n".join(parts).strip()


class AnthropicOCRProvider(OCRProvider):
    def __init__(self) -> None:
        self._model = os.environ.get("ANTHROPIC_OCR_MODEL", _DEFAULT_MODEL)

    def ocr_image(self, image_bytes: bytes, mime_type: str) -> str:
        client = _get_client()
        image_b64 = base64.standard_b64encode(image_bytes).decode("ascii")
        message = _create_message(
            client,
            model=self._model,
            max_tokens=_MAX_TOKENS,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime_type,
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": _OCR_PROMPT},
                    ],
                }
            ],
        )
        return _response_text(message)


def _render_glossary_block(glossary: list[GlossaryTerm]) -> str:
    if not glossary:
        return "(none)"
    lines = []
    for term in glossary:
        line = f"- {term.term_zh} -> {term.term_en}"
        if term.note:
            line += f" ({term.note})"
        lines.append(line)
    return "\n".join(lines)


class AnthropicTranslationProvider(TranslationProvider):
    def __init__(self) -> None:
        self._model = os.environ.get("ANTHROPIC_TRANSLATION_MODEL", _DEFAULT_MODEL)

    def translate(self, zh_text: str, glossary: list[GlossaryTerm]) -> str:
        client = _get_client()
        prompt = (
            "Translate the following Chinese social-media text into natural "
            "English for a beauty-industry strategy reader.\n\n"
            "Glossary (render these terms consistently using the English "
            "given; the note explains the connotation):\n"
            f"{_render_glossary_block(glossary)}\n\n"
            'Rules:\n'
            '- Any line starting with "---" is a section marker: preserve it '
            "verbatim, in place.\n"
            "- Output only the translation; no commentary.\n\n"
            "Text:\n"
            f"{zh_text}"
        )
        message = _create_message(
            client,
            model=self._model,
            max_tokens=_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        return _response_text(message)


def _strip_code_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        text = text[first_newline + 1 :] if first_newline != -1 else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def _parse_entities(raw: str) -> list[Entity]:
    try:
        parsed = json.loads(_strip_code_fences(raw))
    except (json.JSONDecodeError, ValueError) as exc:
        raise ProviderParseError(f"extraction output is not valid JSON: {exc}") from exc
    if not isinstance(parsed, list):
        raise ProviderParseError("extraction output is not a JSON array")
    entities: list[Entity] = []
    for item in parsed:
        if not isinstance(item, dict):
            raise ProviderParseError("extraction array item is not an object")
        text_zh = item.get("text_zh")
        text_en = item.get("text_en")
        entity_type = item.get("type")
        confidence = item.get("confidence")
        if not isinstance(text_zh, str) or not isinstance(text_en, str):
            raise ProviderParseError("entity text fields must be strings")
        if entity_type not in _ENTITY_TYPES:
            raise ProviderParseError(f"invalid entity type: {entity_type!r}")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise ProviderParseError("entity confidence must be a number")
        if not 0.0 <= float(confidence) <= 1.0:
            raise ProviderParseError(f"entity confidence out of range: {confidence}")
        entities.append(
            Entity(
                text_zh=text_zh,
                text_en=text_en,
                type=entity_type,
                confidence=float(confidence),
            )
        )
    return entities


class AnthropicExtractionProvider(ExtractionProvider):
    def __init__(self) -> None:
        self._model = os.environ.get("ANTHROPIC_EXTRACTION_MODEL", _DEFAULT_MODEL)

    def extract(self, zh_text: str, en_text: str) -> list[Entity]:
        client = _get_client()
        prompt = (
            "Extract the named entities (brands, products, ingredients) "
            "mentioned in this bilingual beauty post.\n\n"
            "Return a strict JSON array, nothing else. Each element:\n"
            '{"text_zh": "<Chinese surface form>", "text_en": "<English '
            'form>", "type": "brand|product|ingredient|other", '
            '"confidence": <your own confidence in this entity, 0 to 1>}\n'
            "If there are no entities, return [].\n\n"
            "Chinese text:\n"
            f"{zh_text}\n\n"
            "English translation:\n"
            f"{en_text}"
        )
        message = _create_message(
            client,
            model=self._model,
            max_tokens=_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        return _parse_entities(_response_text(message))
