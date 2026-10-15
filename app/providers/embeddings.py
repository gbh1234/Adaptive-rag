"""Embedding providers: local BGE, hash fallback and OpenAI-compatible API."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import logging
import math
import struct
from threading import Lock
from typing import Any

import httpx

from app.config.settings import Settings
from app.core.exceptions import LLMProviderError
from app.core.retry import is_retryable_status, with_exponential_backoff
from app.providers.device import resolve_torch_device

logger = logging.getLogger(__name__)


def _l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def _local_backend_name(model_id: str) -> str:
    return model_id.rsplit("/", 1)[-1].lower()


class HashEmbeddingProvider:
    """Deterministic embedding used when local dense / embedding API is unavailable.

    Not semantically strong — CI and no-weight development only.
    """

    backend = "hash"

    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim

    async def ping(self) -> bool:
        return True

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        tokens = text.lower().split() or [text]
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            for offset in range(0, min(len(digest), self.dim * 4), 4):
                index = struct.unpack_from(">I", digest, offset)[0] % self.dim
                vector[index] += 1.0
        return _l2_normalize(vector)


class BgeM3EmbeddingProvider:
    """Local dense embeddings via sentence-transformers (bi-encoder recall).

    Default checkpoint is BAAI/bge-small-zh-v1.5. Documents and queries are
    encoded separately. Tests do not download weights: APP_ENV=testing uses hash
    unless a model is injected or LOCAL_EMBEDDING_FORCE=true.
    """

    def __init__(self, settings: Settings, model: Any | None = None) -> None:
        self._settings = settings
        self._model = model
        self._load_lock = Lock()
        self._load_error: str | None = None
        self._backend = _local_backend_name(settings.local_embedding_model)
        self.dim = settings.embedding_dim
        if model is not None:
            dim = getattr(model, "get_sentence_embedding_dimension", lambda: None)()
            if dim:
                self.dim = int(dim)

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def available(self) -> bool:
        return self._ensure_model() is not None

    @property
    def load_error(self) -> str | None:
        return self._load_error

    def _should_load(self) -> bool:
        if not self._settings.local_embedding_enabled:
            return False
        if self._settings.app_env == "testing" and not self._settings.local_embedding_force:
            return False
        return True

    def _ensure_model(self) -> Any | None:
        if self._model is not None:
            return self._model
        if not self._should_load():
            return None
        with self._load_lock:
            if self._model is not None:
                return self._model
            if self._load_error is not None:
                return None
            if importlib.util.find_spec("sentence_transformers") is None:
                self._load_error = "sentence-transformers missing; pip install -e '.[rerank]'"
                logger.warning("local_embedding_sdk_missing")
                return None
            device = resolve_torch_device(self._settings.local_embedding_device)
            try:
                logger.info(
                    "local_embedding_loading",
                    extra={"model": self._settings.local_embedding_model, "device": device},
                )
                self._model = self._load_sentence_transformer(device)
                dim = self._model.get_sentence_embedding_dimension()
                if dim:
                    self.dim = int(dim)
            except Exception as exc:  # model download / CUDA / Hub errors
                self._load_error = str(exc)
                logger.warning("local_embedding_load_failed", extra={"error": str(exc)})
                return None
            return self._model

    def _load_sentence_transformer(self, device: str) -> Any:
        from sentence_transformers import SentenceTransformer

        model_id = self._settings.local_embedding_model
        return SentenceTransformer(model_id, device=device, trust_remote_code=True)

    async def ping(self) -> bool:
        try:
            vectors = await self.embed(["ping"])
            return bool(vectors)
        except LLMProviderError:
            return False

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._ensure_model()
        if model is None:
            raise LLMProviderError(self._load_error or "local embedding unavailable")
        return await asyncio.to_thread(self._encode, model, texts)

    @staticmethod
    def _encode(model: Any, texts: list[str]) -> list[list[float]]:
        raw = model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        if hasattr(raw, "tolist"):
            raw = raw.tolist()
        if raw and isinstance(raw[0], int | float):
            return [[float(value) for value in raw]]
        return [[float(value) for value in row] for row in raw]


class OpenAICompatibleEmbeddingProvider:
    backend = "openai-compatible"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self.dim = settings.embedding_dim
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=settings.embedding_base_url.rstrip("/"),
            timeout=httpx.Timeout(connect=3.0, read=20.0, write=10.0, pool=5.0),
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def ping(self) -> bool:
        try:
            vectors = await self.embed(["ping"])
            return bool(vectors)
        except LLMProviderError:
            return False

    async def embed(self, texts: list[str]) -> list[list[float]]:
        api_key = self._settings.embedding_api_key.get_secret_value()

        async def _call() -> list[list[float]]:
            try:
                response = await self._client.post(
                    "/embeddings",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"model": self._settings.embedding_model, "input": texts},
                )
            except httpx.TimeoutException as exc:
                raise LLMProviderError("embedding request timed out", timeout=True) from exc
            except httpx.HTTPError as exc:
                raise LLMProviderError("embedding transport error") from exc
            if is_retryable_status(response.status_code):
                raise LLMProviderError(f"embedding HTTP {response.status_code}")
            if response.status_code >= 400:
                raise LLMProviderError(f"embedding HTTP {response.status_code}")
            data = response.json()["data"]
            ranked = sorted(data, key=lambda item: item["index"])
            return [item["embedding"] for item in ranked]

        return await with_exponential_backoff(_call, operation_name="embeddings.embed")


def build_embedding_provider(settings: Settings, *, model: Any | None = None) -> Any:
    """Prefer remote OpenAI-compatible API, then local dense model, then hash."""
    if settings.embedding_configured:
        return OpenAICompatibleEmbeddingProvider(settings)
    local = BgeM3EmbeddingProvider(settings, model=model)
    if local.available:
        return local
    logger.warning(
        "local_embedding_unavailable_using_hash",
        extra={"error": local.load_error or "disabled or testing"},
    )
    return HashEmbeddingProvider(dim=settings.embedding_dim)
