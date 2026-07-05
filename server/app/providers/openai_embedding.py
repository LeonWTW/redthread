"""OpenAI embedding provider (text-embedding-3-small, 1536 dims).

The API key is read at call time so an unconfigured deployment fails with
ProviderConfigError only when the embed step actually runs.
"""

from __future__ import annotations

import os

import openai

from .base import (
    EmbeddingProvider,
    ProviderConfigError,
    ProviderRejectionError,
    TransientProviderError,
)

_MODEL = "text-embedding-3-small"
_DIMENSION = 1536


def _get_client() -> openai.OpenAI:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ProviderConfigError("OPENAI_API_KEY is not set")
    return openai.OpenAI(api_key=api_key)


class OpenAIEmbeddingProvider(EmbeddingProvider):
    @property
    def dimension(self) -> int:
        return _DIMENSION

    def embed(self, text: str) -> list[float]:
        client = _get_client()
        try:
            response = client.embeddings.create(model=_MODEL, input=text)
        except (
            openai.RateLimitError,
            openai.APITimeoutError,
            openai.APIConnectionError,
            openai.InternalServerError,
        ) as exc:
            raise TransientProviderError(str(exc)) from exc
        except openai.AuthenticationError as exc:
            raise ProviderConfigError(str(exc)) from exc
        except openai.BadRequestError as exc:
            raise ProviderRejectionError(str(exc)) from exc
        return list(response.data[0].embedding)
