from pathlib import Path
from types import SimpleNamespace

from app.config.settings import Settings
from app.core.enums import DocumentCategory
from app.retrieval.chunking import chunk_markdown, stable_chunk_id
from app.retrieval.unstructured_parser import (
    ParsedElement,
    elements_to_chunks,
    list_knowledge_files,
    parse_path,
)

FIXTURE_HTML = Path("tests/fixtures/docs/policy.html")


class _FakeElement:
    def __init__(
        self,
        category: str,
        text: str,
        *,
        page_number: int | None = None,
        table_html: str | None = None,
    ) -> None:
        self.category = category
        self.text = text
        self.metadata = SimpleNamespace(page_number=page_number, text_as_html=table_html)


def _settings(**overrides) -> Settings:
    data = {
        "app_env": "testing",
        "unstructured_enabled": True,
        "unstructured_force": False,
    }
    data.update(overrides)
    return Settings(**data)


def test_title_becomes_section_and_table_stays_whole() -> None:
    elements = [
        _FakeElement("Header", "公司页眉"),
        _FakeElement("Title", "退货政策", page_number=1),
        _FakeElement("NarrativeText", "定制商品不适用7天无理由。", page_number=1),
        _FakeElement(
            "Table",
            "场景 运费\n无理由 买家承担",
            page_number=2,
            table_html="<table><tr><td>运费</td></tr></table>",
        ),
        _FakeElement("Footer", "页脚"),
        _FakeElement("PageBreak", ""),
    ]
    chunks = elements_to_chunks(
        elements,
        document_id="return_policy",
        title="return_policy",
        category=DocumentCategory.RETURN_POLICY,
        source="policy.pdf",
    )
    assert [c.section for c in chunks] == ["退货政策", "退货政策"]
    assert chunks[0].metadata["element_type"] == "NarrativeText"
    assert chunks[1].metadata["element_type"] == "Table"
    assert chunks[1].metadata["table_html"].startswith("<table>")
    assert chunks[1].metadata["page_number"] == "2"
    assert chunks[1].metadata["parser"] == "unstructured"
    assert "买家承担" in chunks[1].content


def test_table_is_not_windowed() -> None:
    body = "运费规则行。" * 100
    assert len(body) > 500
    chunks = elements_to_chunks(
        [_FakeElement("Table", body, table_html="<table><tr><td>x</td></tr></table>")],
        document_id="shipping",
        title="shipping",
        category=DocumentCategory.SHIPPING,
        source="t.pdf",
    )
    assert len(chunks) == 1
    assert chunks[0].metadata["element_type"] == "Table"
    assert chunks[0].content == body
    elements = [
        ParsedElement(category="Image", text=""),
        ParsedElement(category="Image", text="  包装破损照片说明  ", page_number="3"),
        ParsedElement(category="ListItem", text="签收时请拍照。"),
    ]
    chunks = elements_to_chunks(
        elements,
        document_id="shipping",
        title="shipping",
        category=DocumentCategory.SHIPPING,
        source="photo.png",
    )
    assert len(chunks) == 2
    assert chunks[0].metadata["element_type"] == "Image"
    assert "包装破损" in chunks[0].content
    assert chunks[1].metadata["element_type"] == "ListItem"


def test_unstructured_chunk_ids_are_stable() -> None:
    elements = [
        _FakeElement("Title", "A"),
        _FakeElement("NarrativeText", "hello world"),
        _FakeElement("Title", "B"),
        _FakeElement("NarrativeText", "second section about returns"),
    ]
    once = elements_to_chunks(
        elements,
        document_id="return_policy",
        title="t",
        category=DocumentCategory.RETURN_POLICY,
        source="x",
    )
    twice = elements_to_chunks(
        elements,
        document_id="return_policy",
        title="t",
        category=DocumentCategory.RETURN_POLICY,
        source="x",
    )
    assert [c.chunk_id for c in once] == [c.chunk_id for c in twice]
    assert once[0].chunk_id == stable_chunk_id("return_policy", 0)


def test_parse_path_uses_injected_partition(tmp_path: Path) -> None:
    path = tmp_path / "return_policy.pdf"
    path.write_bytes(b"%PDF-fake")

    def fake_partition(_path: Path) -> list[_FakeElement]:
        return [
            _FakeElement("Title", "退货"),
            _FakeElement("NarrativeText", "定制商品不适用7天无理由。"),
        ]

    chunks = parse_path(
        path,
        document_id="doc",
        title="return_policy",
        category=DocumentCategory.RETURN_POLICY,
        settings=_settings(),
        partition_fn=fake_partition,
    )
    assert len(chunks) == 1
    assert chunks[0].section == "退货"
    assert chunks[0].metadata["parser"] == "unstructured"


def test_parse_path_skips_non_markdown_without_unstructured(tmp_path: Path) -> None:
    path = tmp_path / "scan.png"
    path.write_bytes(b"\x89PNG")
    chunks = parse_path(
        path,
        document_id="scan",
        title="scan",
        category=DocumentCategory.FAQ,
        settings=_settings(),
    )
    assert chunks == []


def test_parse_path_falls_back_to_markdown(tmp_path: Path) -> None:
    path = tmp_path / "return_policy.md"
    path.write_text("## 退货\n\n定制商品不适用7天无理由。\n", encoding="utf-8")
    chunks = parse_path(
        path,
        document_id="doc",
        title="return_policy",
        category=DocumentCategory.RETURN_POLICY,
        settings=_settings(),
    )
    assert chunks
    assert chunks[0].section == "退货"
    assert chunks[0].metadata["parser"] == "markdown"


def test_parse_path_partition_error_falls_back_markdown(tmp_path: Path) -> None:
    path = tmp_path / "faq.md"
    path.write_text("# FAQ\n\n电子发票当天下载。\n", encoding="utf-8")

    def boom(_path: Path) -> list[_FakeElement]:
        raise RuntimeError("ocr crashed")

    chunks = parse_path(
        path,
        document_id="faq",
        title="faq",
        category=DocumentCategory.FAQ,
        settings=_settings(),
        partition_fn=boom,
    )
    assert chunks
    assert chunks[0].metadata["parser"] == "markdown"


def test_html_fixture_with_injected_partition() -> None:
    assert FIXTURE_HTML.is_file()

    def fake_partition(_path: Path) -> list[_FakeElement]:
        return [
            _FakeElement("Title", "退货政策"),
            _FakeElement("NarrativeText", "定制商品不适用7天无理由。"),
            _FakeElement(
                "Table",
                "场景 运费 无理由 买家承担",
                table_html="<table><tr><td>买家承担</td></tr></table>",
            ),
        ]

    chunks = parse_path(
        FIXTURE_HTML,
        document_id="policy",
        title="policy",
        category=DocumentCategory.RETURN_POLICY,
        settings=_settings(),
        partition_fn=fake_partition,
    )
    assert len(chunks) == 2
    assert chunks[1].metadata["element_type"] == "Table"


def test_list_knowledge_files_includes_supported_suffixes(tmp_path: Path) -> None:
    (tmp_path / "return_policy.md").write_text("# a\n", encoding="utf-8")
    (tmp_path / "shipping.pdf").write_bytes(b"%PDF")
    (tmp_path / "ignore.txt").write_text("nope", encoding="utf-8")
    (tmp_path / ".hidden.md").write_text("# hidden\n", encoding="utf-8")
    files = list_knowledge_files(tmp_path)
    names = {path.name for path in files}
    assert names == {"return_policy.md", "shipping.pdf"}


def test_markdown_fallback_chunk_ids_still_stable() -> None:
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
