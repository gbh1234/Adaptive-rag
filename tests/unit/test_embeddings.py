import pytest

from app.config.settings import Settings
from app.core.exceptions import LLMProviderError
from app.providers.embeddings import (
    BgeM3EmbeddingProvider,
    HashEmbeddingProvider,
    build_embedding_provider,
)


class _FakeSentenceTransformer:
    def get_sentence_embedding_dimension(self) -> int:
        return 4

    def encode(self, texts, normalize_embeddings=True, show_progress_bar=False):
        vectors = []
        for text in texts:
            hit = 1.0 if "退货" in text else 0.0
            vectors.append([hit, 0.0, 0.0, 0.0])
        return vectors


def _settings(**overrides) -> Settings:
    data = {
        "app_env": "development",
        "local_embedding_enabled": True,
        "local_embedding_force": False,
        "embedding_dim": 512,
    }
    data.update(overrides)
    return Settings(**data)


@pytest.mark.asyncio
async def test_injected_bge_m3_encodes() -> None:
    provider = BgeM3EmbeddingProvider(_settings(), model=_FakeSentenceTransformer())
    assert provider.available
    assert provider.backend == "bge-small-zh-v1.5"
    assert provider.dim == 4
    vectors = await provider.embed(["七天退货", "物流"])
    assert vectors[0][0] == 1.0
    assert vectors[1][0] == 0.0


@pytest.mark.asyncio
async def test_testing_env_skips_bge_m3_download() -> None:
    provider = BgeM3EmbeddingProvider(_settings(app_env="testing"))
    assert provider.available is False
    with pytest.raises(LLMProviderError):
        await provider.embed(["ping"])


@pytest.mark.asyncio
async def test_factory_uses_injected_bge_m3() -> None:
    provider = build_embedding_provider(_settings(), model=_FakeSentenceTransformer())
    assert provider.backend == "bge-small-zh-v1.5"


@pytest.mark.asyncio
async def test_factory_falls_back_to_hash_in_testing() -> None:
    provider = build_embedding_provider(_settings(app_env="testing"))
    assert isinstance(provider, HashEmbeddingProvider)
    assert provider.backend == "hash"
    vectors = await provider.embed(["定制退货"])
    assert len(vectors[0]) == 512


@pytest.mark.asyncio
async def test_backend_follows_local_model_id() -> None:
    provider = BgeM3EmbeddingProvider(
        _settings(local_embedding_model="BAAI/bge-m3"),
        model=_FakeSentenceTransformer(),
    )
    assert provider.backend == "bge-m3"
