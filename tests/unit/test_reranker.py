import pytest

from app.config.settings import Settings
from app.core.enums import DocumentCategory
from app.providers.reranker import CrossEncoderRerankProvider, LexicalRerankProvider
from app.retrieval.reranker import DocumentReranker
from app.schemas.retrieval import RetrievedChunk


class _FakeCrossEncoder:
    """Scores a document higher when it contains the query as a substring."""

    def predict(self, pairs, show_progress_bar=False):
        scores = []
        for query, document in pairs:
            scores.append(10.0 if query in document else 0.1)
        return scores


def _settings(**overrides) -> Settings:
    data = {
        "app_env": "development",
        "cross_encoder_enabled": True,
        "cross_encoder_force": False,
    }
    data.update(overrides)
    return Settings(**data)


def _chunk(chunk_id: str, content: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id="doc",
        title="t",
        content=content,
        score=0.0,
        rank=0,
        category=DocumentCategory.FAQ,
    )


@pytest.mark.asyncio
async def test_lexical_ranks_overlap() -> None:
    provider = LexicalRerankProvider()
    ranked = await provider.rerank(
        "退货",
        ["物流时效三日达", "七天无理由退货", "发票说明"],
        top_n=2,
    )
    assert ranked[0][0] == 1
    assert ranked[0][1] > ranked[1][1]


@pytest.mark.asyncio
async def test_cross_encoder_uses_injected_model() -> None:
    provider = CrossEncoderRerankProvider(_settings(), model=_FakeCrossEncoder())
    assert provider.available
    assert provider.backend == "cross-encoder"
    ranked = await provider.rerank(
        "定制退货",
        ["无关物流", "政策：定制退货需质检", "发票"],
        top_n=2,
    )
    assert ranked[0][0] == 1
    assert ranked[0][1] == 10.0


@pytest.mark.asyncio
async def test_testing_env_skips_download() -> None:
    provider = CrossEncoderRerankProvider(_settings(app_env="testing"))
    assert provider.available is False
    assert provider.backend == "lexical"
    ranked = await provider.rerank("退货", ["七天退货", "物流"], top_n=1)
    assert ranked[0][0] == 0


@pytest.mark.asyncio
async def test_document_reranker_rewrites_rank_and_source() -> None:
    provider = CrossEncoderRerankProvider(_settings(), model=_FakeCrossEncoder())
    reranker = DocumentReranker(provider)
    chunks = [
        _chunk("a", "无关"),
        _chunk("b", "问：七天无理由"),
    ]
    ranked = await reranker.rerank("七天无理由", chunks, top_n=1)
    assert len(ranked) == 1
    assert ranked[0].chunk_id == "b"
    assert ranked[0].source == "rerank"
    assert ranked[0].rank == 1
    assert ranked[0].score == 10.0


@pytest.mark.asyncio
async def test_disabled_cross_encoder_falls_back() -> None:
    provider = CrossEncoderRerankProvider(_settings(cross_encoder_enabled=False))
    assert provider.available is False
    ranked = await provider.rerank("a", ["a", "b"], top_n=1)
    assert ranked[0][0] == 0
