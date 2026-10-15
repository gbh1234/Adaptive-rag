import logging
from pathlib import Path

from app.core.constants import PII_MASK
from app.core.enums import DocumentCategory
from app.retrieval.chunking import chunk_markdown
from app.retrieval.cleaning import (
    NEAR_DUP_HAMMING,
    dedupe_chunks,
    hamming64,
    normalize_text,
    simhash64,
)
from app.retrieval.unstructured_parser import elements_to_chunks, parse_path
from app.schemas.retrieval import RetrievedChunk
from tests.unit.test_unstructured_parser import _FakeElement, _settings


def _chunk(chunk_id: str, document_id: str, content: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        title=document_id,
        content=content,
        score=0.0,
        category=DocumentCategory.FAQ,
    )


def test_strips_bom_and_zero_width() -> None:
    raw = "\ufeff无\u200b理由\u00ad退货"
    assert normalize_text(raw) == "无理由退货"


def test_nfkc_fullwidth_digits_not_chinese_numerals() -> None:
    assert normalize_text("７天无理由") == "7天无理由"
    assert "7天" not in normalize_text("七天无理由")
    assert normalize_text("七天无理由") == "七天无理由"


def test_joins_cjk_hard_breaks_but_not_tables() -> None:
    assert normalize_text("无理\n由", join_hard_breaks=True) == "无理由"
    assert "\n" in normalize_text("无理\n由", join_hard_breaks=False)
    chunks = elements_to_chunks(
        [_FakeElement("Table", "无理\n由", table_html="<table>无理\n由</table>")],
        document_id="shipping",
        title="shipping",
        category=DocumentCategory.SHIPPING,
        source="t.pdf",
    )
    assert "\n" in chunks[0].content


def test_collapses_inline_space_and_extra_blank_lines() -> None:
    text = "满59\t包邮。\n\n\n\n偏远除外。"
    cleaned = normalize_text(text)
    assert "\t" not in cleaned
    assert "满59 包邮。" in cleaned
    assert "\n\n\n" not in cleaned


def test_markdown_keeps_policy_pii_words_and_numbers(tmp_path: Path) -> None:
    path = tmp_path / "privacy_cs.md"
    path.write_text("客服不得索取完整身份证。联系以 13812345678 为例不得复述。\n", encoding="utf-8")
    chunks = parse_path(
        path,
        document_id="privacy",
        title="privacy_cs",
        category=DocumentCategory.ACCOUNT,
        settings=_settings(),
    )
    blob = " ".join(chunk.content for chunk in chunks)
    assert "身份证" in blob
    assert "13812345678" in blob


def test_non_markdown_masks_phone(tmp_path: Path) -> None:
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"%PDF-fake")

    def fake_partition(_path: Path) -> list[_FakeElement]:
        return [_FakeElement("NarrativeText", "用户手机 13812345678 已登记。")]

    chunks = parse_path(
        path,
        document_id="scan",
        title="scan",
        category=DocumentCategory.FAQ,
        settings=_settings(),
        partition_fn=fake_partition,
    )
    assert chunks
    assert "13812345678" not in chunks[0].content
    assert f"138{PII_MASK}5678" in chunks[0].content


def test_utf8_sig_markdown_reads_bom(tmp_path: Path) -> None:
    path = tmp_path / "faq.md"
    path.write_bytes("\ufeff# FAQ\n\n电子发票当天下载。\n".encode())
    chunks = parse_path(
        path,
        document_id="faq",
        title="faq",
        category=DocumentCategory.FAQ,
        settings=_settings(),
    )
    assert chunks
    assert chunks[0].content.startswith("电子发票")


def test_exact_duplicate_keeps_first_chunk_id() -> None:
    first = _chunk("a_00", "doc_a", "定制商品不适用7天无理由。")
    second = _chunk("b_00", "doc_b", "定制商品不适用7天无理由。")
    kept = dedupe_chunks([first, second])
    assert [chunk.chunk_id for chunk in kept] == ["a_00"]


def test_near_duplicate_is_logged_not_dropped(caplog) -> None:
    text_a = "非定制未拆封影响二次销售的商品签收次日起7个自然日内可申请无理由退货。"
    text_b = "非定制未拆封影响二次销售的商品签收次日起7个自然日内可申请无理由退货！"
    distance = hamming64(simhash64(text_a), simhash64(text_b))
    assert 0 < distance <= NEAR_DUP_HAMMING or distance <= 8
    threshold = min(NEAR_DUP_HAMMING, distance) if distance <= NEAR_DUP_HAMMING else distance
    with caplog.at_level(logging.INFO, logger="app.retrieval.cleaning"):
        kept = dedupe_chunks(
            [_chunk("a_00", "return_policy", text_a), _chunk("b_00", "return_electronics", text_b)],
            near_dup_bits=threshold,
        )
    assert len(kept) == 2
    assert any(record.message == "ingest_near_duplicate" for record in caplog.records)


def test_chunk_markdown_normalizes_fullwidth() -> None:
    chunks = chunk_markdown(
        "## 退货\n\n定制商品不适用７天无理由。",
        document_id="doc",
        title="policy",
        category=DocumentCategory.RETURN_POLICY,
        source="x.md",
    )
    assert "7天" in chunks[0].content
    assert chunks[0].metadata["parser"] == "markdown"
