from app.core.enums import DocumentCategory
from app.retrieval.bm25 import BM25Retriever
from app.retrieval.chunking import chunk_markdown, stable_chunk_id


def test_chunk_ids_are_stable() -> None:
    text = "## A\n\nhello world\n\n## B\n\nsecond section about returns"
    once = chunk_markdown(
        text,
        document_id="return_policy",
        title="t",
        category=DocumentCategory.RETURN_POLICY,
        source="x",
    )
    twice = chunk_markdown(
        text,
        document_id="return_policy",
        title="t",
        category=DocumentCategory.RETURN_POLICY,
        source="x",
    )
    assert [c.chunk_id for c in once] == [c.chunk_id for c in twice]
    assert once[0].chunk_id == stable_chunk_id("return_policy", 0)


def test_bm25_ranks_lexical_match() -> None:
    chunks = chunk_markdown(
        "## 退货\n\n定制商品不适用7天无理由。质量问题仍可退货。\n\n## 包邮\n\n满59包邮。",
        document_id="doc",
        title="policy",
        category=DocumentCategory.RETURN_POLICY,
        source="x",
    )
    retriever = BM25Retriever(chunks)
    hits = retriever.search("定制商品 7天无理由", top_k=2)
    assert hits
    assert "定制" in hits[0].content or "无理由" in hits[0].content
