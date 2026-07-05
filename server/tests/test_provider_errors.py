"""SDK exception -> ProviderError mapping and extraction parsing (no network)."""

import json
from types import SimpleNamespace
from unittest import mock

import anthropic
import httpx
import openai
import pytest

from app.providers.anthropic_providers import (
    AnthropicExtractionProvider,
    AnthropicOCRProvider,
    AnthropicTranslationProvider,
)
from app.providers.base import (
    Entity,
    GlossaryTerm,
    ProviderConfigError,
    ProviderParseError,
    ProviderRejectionError,
    TransientProviderError,
)
from app.providers.openai_embedding import OpenAIEmbeddingProvider

_REQUEST = httpx.Request("POST", "https://api.example.test/v1")


def _status_error(cls, status_code):
    response = httpx.Response(status_code, request=_REQUEST)
    return cls("boom", response=response, body=None)


ANTHROPIC_ERROR_CASES = [
    (_status_error(anthropic.RateLimitError, 429), TransientProviderError),
    (anthropic.APITimeoutError(request=_REQUEST), TransientProviderError),
    (anthropic.APIConnectionError(request=_REQUEST), TransientProviderError),
    (_status_error(anthropic.InternalServerError, 500), TransientProviderError),
    (_status_error(anthropic.AuthenticationError, 401), ProviderConfigError),
    (_status_error(anthropic.PermissionDeniedError, 403), ProviderConfigError),
    (_status_error(anthropic.BadRequestError, 400), ProviderRejectionError),
]

OPENAI_ERROR_CASES = [
    (_status_error(openai.RateLimitError, 429), TransientProviderError),
    (openai.APITimeoutError(request=_REQUEST), TransientProviderError),
    (openai.APIConnectionError(request=_REQUEST), TransientProviderError),
    (_status_error(openai.InternalServerError, 500), TransientProviderError),
    (_status_error(openai.AuthenticationError, 401), ProviderConfigError),
    (_status_error(openai.BadRequestError, 400), ProviderRejectionError),
]


def _text_response(text):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


def _call_ocr(provider):
    return provider.ocr_image(b"img", "image/png")


def _call_translate(provider):
    return provider.translate("避雷", [GlossaryTerm("避雷", "BiLei", "warning")])


def _call_extract(provider):
    return provider.extract("避雷", "BiLei warning")


ANTHROPIC_PROVIDERS = [
    (AnthropicOCRProvider, _call_ocr),
    (AnthropicTranslationProvider, _call_translate),
    (AnthropicExtractionProvider, _call_extract),
]


@pytest.fixture
def anthropic_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")


@pytest.fixture
def openai_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")


@pytest.mark.parametrize("provider_cls,call", ANTHROPIC_PROVIDERS)
@pytest.mark.parametrize("sdk_error,expected", ANTHROPIC_ERROR_CASES)
def test_anthropic_error_mapping(anthropic_key, provider_cls, call, sdk_error, expected):
    with mock.patch("anthropic.Anthropic") as client_cls:
        client_cls.return_value.messages.create.side_effect = sdk_error
        with pytest.raises(expected):
            call(provider_cls())


@pytest.mark.parametrize("provider_cls,call", ANTHROPIC_PROVIDERS)
def test_anthropic_missing_key_is_config_error(monkeypatch, provider_cls, call):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with mock.patch("anthropic.Anthropic") as client_cls:
        with pytest.raises(ProviderConfigError):
            call(provider_cls())
        client_cls.assert_not_called()


@pytest.mark.parametrize("sdk_error,expected", OPENAI_ERROR_CASES)
def test_openai_error_mapping(openai_key, sdk_error, expected):
    with mock.patch("openai.OpenAI") as client_cls:
        client_cls.return_value.embeddings.create.side_effect = sdk_error
        with pytest.raises(expected):
            OpenAIEmbeddingProvider().embed("text")


def test_openai_missing_key_is_config_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with mock.patch("openai.OpenAI") as client_cls:
        with pytest.raises(ProviderConfigError):
            OpenAIEmbeddingProvider().embed("text")
        client_cls.assert_not_called()


def test_embedding_dimension_is_1536():
    assert OpenAIEmbeddingProvider().dimension == 1536


@pytest.mark.parametrize(
    "bad_output",
    [
        "not json at all",
        '{"text_zh": "x"}',  # object, not array
        '[{"text_zh": "x", "text_en": "y", "type": "planet", "confidence": 0.5}]',
        '[{"text_zh": "x", "text_en": "y", "type": "brand", "confidence": 1.5}]',
        '[{"text_zh": "x", "text_en": "y", "type": "brand", "confidence": "high"}]',
        '[{"text_en": "y", "type": "brand", "confidence": 0.5}]',
        '["just a string"]',
    ],
)
def test_extraction_malformed_output_raises_parse_error(anthropic_key, bad_output):
    with mock.patch("anthropic.Anthropic") as client_cls:
        client_cls.return_value.messages.create.return_value = _text_response(bad_output)
        with pytest.raises(ProviderParseError):
            AnthropicExtractionProvider().extract("zh", "en")


def test_extraction_parses_fenced_json_array(anthropic_key):
    payload = [
        {"text_zh": "花西子", "text_en": "Florasis", "type": "brand", "confidence": 0.95},
        {"text_zh": "烟酰胺", "text_en": "niacinamide", "type": "ingredient", "confidence": 0.8},
    ]
    fenced = "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"
    with mock.patch("anthropic.Anthropic") as client_cls:
        client_cls.return_value.messages.create.return_value = _text_response(fenced)
        entities = AnthropicExtractionProvider().extract("zh", "en")
    assert entities == [
        Entity(text_zh="花西子", text_en="Florasis", type="brand", confidence=0.95),
        Entity(text_zh="烟酰胺", text_en="niacinamide", type="ingredient", confidence=0.8),
    ]
