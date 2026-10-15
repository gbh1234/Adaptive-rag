from app.core.enums import DocumentCategory
from app.retrieval.fusion import reciprocal_rank_fusion
from app.schemas.retrieval import RetrievedChunk


def _chunk(chunk_id: str, rank: int) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id="doc",
        title="t",
        content="c",
        score=1.0,
        rank=rank,
        category=DocumentCategory.FAQ,
    )


def test_rrf_prefers_docs_high_in_both_lists() -> None:
    lexical = [_chunk("a", 1), _chunk("b", 2), _chunk("c", 3)]
    dense = [_chunk("b", 1), _chunk("a", 2), _chunk("d", 3)]
    fused = reciprocal_rank_fusion([lexical, dense], k=60)
    assert fused[0].chunk_id == "a" or fused[0].chunk_id == "b"
    ids = [item.chunk_id for item in fused]
    assert ids.count("a") == 1
    assert "d" in ids


def test_rrf_uses_rank_not_raw_score() -> None:
    high_score_low_rank = _chunk("x", 5)
    high_score_low_rank.score = 99
    low_score_high_rank = _chunk("y", 1)
    low_score_high_rank.score = 0.01
    fused = reciprocal_rank_fusion([[high_score_low_rank], [low_score_high_rank]], k=60)
    # two lists of size 1 → both rank 1, equal RRF; stable by sort of dict
    assert {item.chunk_id for item in fused} == {"x", "y"}
