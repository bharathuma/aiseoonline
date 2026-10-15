"""Replaceable, bounded embedding transport; no live API calls in CI."""

import hashlib
import logging
import math
import time
from collections.abc import Sequence
from typing import Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from aiseoonline_api.ai_core.contracts import (
    BudgetExceeded,
    CredentialsUnavailable,
    InvalidModelOutput,
    LLMTimeout,
    ProviderRateLimited,
    ProviderUnavailable,
)
from aiseoonline_api.config import Settings

logger = logging.getLogger("aiseoonline.rag")
DIMENSIONS = 384
_MAX_BATCH = 8


class EmbeddingSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: str = Field(min_length=2, max_length=32)
    model: str = Field(min_length=2, max_length=120)
    version: str = Field(min_length=1, max_length=48)
    dimensions: int = DIMENSIONS

    @model_validator(mode="after")
    def storage_dimensions(self) -> "EmbeddingSpec":
        if self.dimensions != DIMENSIONS:
            raise ValueError("This vector index accepts 384 dimensions; migrate before changing")
        return self


class EmbeddingProvider(Protocol):
    @property
    def spec(self) -> EmbeddingSpec: ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def validate_vectors(vectors: list[list[float]], count: int) -> None:
    if len(vectors) != count:
        raise InvalidModelOutput("Embedding provider returned wrong batch size")
    for vector in vectors:
        if len(vector) != DIMENSIONS or not all(math.isfinite(v) for v in vector):
            raise InvalidModelOutput("Embedding dimensions or values are invalid")
        if not any(v != 0 for v in vector):
            raise InvalidModelOutput("Embedding vector must not be zero")


class OpenAIEmbeddingProvider:
    def __init__(
        self,
        api_key: str,
        *,
        model: str = "text-embedding-3-small",
        version: str = "v1",
        client: httpx.Client | None = None,
        max_retries: int = 2,
        timeout: float = 15.0,
    ) -> None:
        if not api_key.strip():
            raise CredentialsUnavailable("Embedding API key is not configured")
        if not 0 <= max_retries <= 2 or not 1 <= timeout <= 30:
            raise ValueError("Embedding retry or timeout exceeds allowed limits")
        self.spec = EmbeddingSpec(provider="openai", model=model, version=version)
        self._client = client or httpx.Client(trust_env=False, follow_redirects=False)
        self._owned = client is None
        self._key = api_key
        self.max_retries = max_retries
        self.timeout = timeout

    def close(self) -> None:
        if self._owned:
            self._client.close()

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not 1 <= len(texts) <= _MAX_BATCH or any(not t or len(t) > 2000 for t in texts):
            raise BudgetExceeded("Embedding batch exceeds configured limits")
        payload = {
            "model": self.spec.model,
            "input": list(texts),
            "dimensions": DIMENSIONS,
            "encoding_format": "float",
        }
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.post(
                    "https://api.openai.com/v1/embeddings",
                    json=payload,
                    headers={"Authorization": f"Bearer {self._key}"},
                    timeout=self.timeout,
                    follow_redirects=False,
                )
            except httpx.TimeoutException:
                if attempt == self.max_retries:
                    raise LLMTimeout("Embedding provider timed out") from None
            except httpx.TransportError:
                if attempt == self.max_retries:
                    raise ProviderUnavailable("Embedding provider unreachable") from None
            else:
                if response.status_code == 429 and attempt == self.max_retries:
                    raise ProviderRateLimited("Embedding provider rate limited") from None
                if response.status_code not in (429, 500, 502, 503, 504):
                    if response.status_code >= 400:
                        raise ProviderUnavailable("Embedding provider rejected request")
                    break
                if attempt == self.max_retries:
                    raise ProviderUnavailable("Embedding provider exhausted retries") from None
            time.sleep(min(2.0, 0.25 * (2**attempt)))
        try:
            raw = response.json()
            rows = raw["data"]
            if not isinstance(rows, list) or len(rows) != len(texts):
                raise ValueError
            ordered: list[list[float] | None] = [None] * len(texts)
            for row in rows:
                position = row["index"]
                values = row["embedding"]
                if not isinstance(position, int) or not 0 <= position < len(texts):
                    raise ValueError
                if ordered[position] is not None or not isinstance(values, list):
                    raise ValueError
                ordered[position] = [float(n) for n in values]
            if any(vector is None for vector in ordered):
                raise ValueError
            result = [vector for vector in ordered if vector is not None]
            validate_vectors(result, len(texts))
        except (KeyError, TypeError, ValueError, OverflowError):
            raise InvalidModelOutput("Embedding provider returned an invalid payload") from None
        logger.info("Embedding batch complete model=%s count=%d", self.spec.model, len(texts))
        return result


class FixtureEmbeddingProvider:
    """Deterministic local embeddings for tests only; never substitute for real vectors."""

    def __init__(self, version: str = "fixture-v1") -> None:
        self.spec = EmbeddingSpec(provider="fixture", model="token-hash", version=version)
        self.calls = 0

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not 1 <= len(texts) <= _MAX_BATCH:
            raise BudgetExceeded("Embedding batch exceeds limits")
        self.calls += 1
        result: list[list[float]] = []
        for text in texts:
            if not text or len(text) > 2000:
                raise BudgetExceeded("Text outside fixture embedding limits")
            values = [0.0] * DIMENSIONS
            for word in text.casefold().split():
                i = int.from_bytes(hashlib.sha256(word.encode()).digest()[:4], "big") % DIMENSIONS
                values[i] += 1.0
            scale = math.sqrt(sum(v * v for v in values))
            if not scale:
                raise InvalidModelOutput("Empty fixture vector")
            result.append([v / scale for v in values])
        validate_vectors(result, len(texts))
        return result


def make_openai_embedding_provider(
    settings: Settings, *, client: httpx.Client | None = None
) -> OpenAIEmbeddingProvider:
    """Backend-only factory; no implicit fixture or unconfigured provider fallback."""
    key = settings.openai_api_key
    if key is None:
        raise CredentialsUnavailable("AISEO_OPENAI_API_KEY is needed for embedding calls")
    return OpenAIEmbeddingProvider(
        key.get_secret_value(),
        model=settings.rag_embedding_model,
        version=settings.rag_embedding_version,
        client=client,
    )
