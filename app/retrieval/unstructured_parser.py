"""Unstructured parsing for PDF/Office/HTML/images with a Markdown fallback."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config.settings import Settings
from app.core.enums import DocumentCategory
from app.retrieval.chunking import (
    MAX_CHUNK_CHARS,
    OVERLAP_CHARS,
    _window,
    chunk_markdown,
    stable_chunk_id,
)
from app.retrieval.cleaning import normalize_text, redact_chunk_pii
from app.schemas.retrieval import RetrievedChunk

logger = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = frozenset(
    {
        ".md",
        ".pdf",
        ".docx",
        ".pptx",
        ".html",
        ".htm",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".tiff",
        ".tif",
    }
)
MARKDOWN_SUFFIXES = frozenset({".md"})
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".tiff", ".tif"})
LAYOUT_SUFFIXES = frozenset({".pdf"}) | IMAGE_SUFFIXES

_SKIP_CATEGORIES = frozenset({"Header", "Footer", "PageBreak"})
_TITLE_CATEGORIES = frozenset({"Title"})
_TABLE_CATEGORIES = frozenset({"Table"})
_IMAGE_CATEGORIES = frozenset({"Image", "Figure"})

TABLE_HTML_MAX_CHARS = 4000
PartitionFn = Callable[[Path], list[Any]]

_partition_fn: Any | None = None
_partition_error: str | None = None
_partition_probed = False


@dataclass(frozen=True)
class ParsedElement:
    category: str
    text: str
    page_number: str = ""
    table_html: str = ""


def list_knowledge_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    files = [
        path
        for path in directory.iterdir()
        if path.is_file()
        and not path.name.startswith(".")
        and path.suffix.lower() in SUPPORTED_SUFFIXES
    ]
    return sorted(files)


def unstructured_should_load(settings: Settings) -> bool:
    return settings.unstructured_configured


def unstructured_available() -> bool:
    return _resolve_partition() is not None


def _resolve_partition() -> Any | None:
    global _partition_fn, _partition_error, _partition_probed
    if _partition_probed:
        return _partition_fn
    _partition_probed = True
    try:
        from unstructured.partition.auto import partition
    except ImportError:
        _partition_error = "unstructured missing; pip install -e '.[docs]'"
        logger.warning("unstructured_sdk_missing")
        return None
    _partition_fn = partition
    return _partition_fn


def ocr_languages(value: str) -> list[str]:
    return [part.strip() for part in value.replace(",", "+").split("+") if part.strip()]


def coerce_element(raw: Any) -> ParsedElement:
    if isinstance(raw, ParsedElement):
        return raw
    category = str(getattr(raw, "category", "") or type(raw).__name__)
    text = str(getattr(raw, "text", "") or "")
    metadata = getattr(raw, "metadata", None)
    page_number = ""
    table_html = ""
    if metadata is not None:
        page = getattr(metadata, "page_number", None)
        if page is not None:
            page_number = str(page)
        html = getattr(metadata, "text_as_html", None)
        if html:
            table_html = str(html)
    return ParsedElement(
        category=category,
        text=text,
        page_number=page_number,
        table_html=table_html,
    )


def elements_to_chunks(
    elements: Iterable[Any],
    *,
    document_id: str,
    title: str,
    category: DocumentCategory,
    source: str,
    policy_version: str = "v1",
) -> list[RetrievedChunk]:
    chunks: list[RetrievedChunk] = []
    section = "body"
    buffer: list[ParsedElement] = []

    def flush_buffer() -> None:
        nonlocal buffer
        if not buffer:
            return
        body = "\n".join(item.text.strip() for item in buffer if item.text.strip())
        pages = [item.page_number for item in buffer if item.page_number]
        types = {item.category for item in buffer}
        element_type = types.pop() if len(types) == 1 else "NarrativeText"
        page_number = pages[0] if pages else ""
        for piece in _window(body, MAX_CHUNK_CHARS, OVERLAP_CHARS):
            chunks.append(
                _build_chunk(
                    document_id=document_id,
                    title=title,
                    category=category,
                    source=source,
                    policy_version=policy_version,
                    content=piece,
                    section=section,
                    chunk_index=len(chunks),
                    parser="unstructured",
                    element_type=element_type,
                    page_number=page_number,
                )
            )
        buffer = []

    for raw in elements:
        element = coerce_element(raw)
        kind = element.category
        if kind in _SKIP_CATEGORIES:
            continue
        if kind in _TITLE_CATEGORIES:
            flush_buffer()
            heading = normalize_text(element.text, join_hard_breaks=False)
            if heading:
                section = heading
            continue
        if kind in _TABLE_CATEGORIES:
            flush_buffer()
            content = element.text.strip()
            if not content and not element.table_html:
                continue
            chunks.append(
                _build_chunk(
                    document_id=document_id,
                    title=title,
                    category=category,
                    source=source,
                    policy_version=policy_version,
                    content=content or element.table_html.strip(),
                    section=section,
                    chunk_index=len(chunks),
                    parser="unstructured",
                    element_type="Table",
                    page_number=element.page_number,
                    table_html=element.table_html,
                )
            )
            continue
        if kind in _IMAGE_CATEGORIES:
            flush_buffer()
            content = element.text.strip()
            if not content:
                continue
            chunks.append(
                _build_chunk(
                    document_id=document_id,
                    title=title,
                    category=category,
                    source=source,
                    policy_version=policy_version,
                    content=content,
                    section=section,
                    chunk_index=len(chunks),
                    parser="unstructured",
                    element_type=kind,
                    page_number=element.page_number,
                )
            )
            continue
        if not element.text.strip():
            continue
        buffer.append(element)
    flush_buffer()
    return chunks


def parse_path(
    path: Path,
    *,
    document_id: str,
    title: str,
    category: DocumentCategory,
    settings: Settings,
    policy_version: str = "v1",
    partition_fn: PartitionFn | None = None,
) -> list[RetrievedChunk]:
    """Partition a file into RetrievedChunk. Markdown heading split is the fallback."""
    source = str(path)
    suffix = path.suffix.lower()
    use_unstructured = partition_fn is not None or (
        unstructured_should_load(settings) and unstructured_available()
    )
    if use_unstructured:
        try:
            elements = (
                partition_fn(path) if partition_fn is not None else _partition_file(path, settings)
            )
            chunks = elements_to_chunks(
                elements,
                document_id=document_id,
                title=title,
                category=category,
                source=source,
                policy_version=policy_version,
            )
            return _maybe_redact(chunks, suffix)
        except Exception as exc:
            logger.warning(
                "unstructured_partition_failed",
                extra={"path": source, "error": str(exc)},
            )
            if suffix in MARKDOWN_SUFFIXES:
                return _markdown_fallback(
                    path,
                    document_id=document_id,
                    title=title,
                    category=category,
                    source=source,
                    policy_version=policy_version,
                )
            return []
    if suffix in MARKDOWN_SUFFIXES:
        return _markdown_fallback(
            path,
            document_id=document_id,
            title=title,
            category=category,
            source=source,
            policy_version=policy_version,
        )
    logger.warning("skip_non_markdown_without_unstructured", extra={"path": source})
    return []


def _partition_file(path: Path, settings: Settings) -> list[Any]:
    partition = _resolve_partition()
    if partition is None:
        raise RuntimeError(_partition_error or "unstructured unavailable")
    kwargs: dict[str, Any] = {"filename": str(path)}
    if path.suffix.lower() in LAYOUT_SUFFIXES:
        kwargs["strategy"] = settings.unstructured_strategy
        langs = ocr_languages(settings.unstructured_ocr_languages)
        if langs:
            kwargs["languages"] = langs
    return list(partition(**kwargs))


def _markdown_fallback(
    path: Path,
    *,
    document_id: str,
    title: str,
    category: DocumentCategory,
    source: str,
    policy_version: str,
) -> list[RetrievedChunk]:
    text = path.read_text(encoding="utf-8-sig")
    return chunk_markdown(
        text,
        document_id=document_id,
        title=title,
        category=category,
        source=source,
        policy_version=policy_version,
    )


def _build_chunk(
    *,
    document_id: str,
    title: str,
    category: DocumentCategory,
    source: str,
    policy_version: str,
    content: str,
    section: str,
    chunk_index: int,
    parser: str,
    element_type: str,
    page_number: str = "",
    table_html: str = "",
) -> RetrievedChunk:
    join_hard_breaks = element_type != "Table"
    normalized = normalize_text(content, join_hard_breaks=join_hard_breaks)
    metadata = {
        "source": source,
        "parser": parser,
        "element_type": element_type,
    }
    if page_number:
        metadata["page_number"] = page_number
    if table_html:
        metadata["table_html"] = table_html[:TABLE_HTML_MAX_CHARS]
    return RetrievedChunk(
        chunk_id=stable_chunk_id(document_id, chunk_index),
        document_id=document_id,
        title=title,
        content=normalized,
        score=0.0,
        category=category,
        section=normalize_text(section, join_hard_breaks=False) or section,
        chunk_index=chunk_index,
        policy_version=policy_version,
        metadata=metadata,
        source="ingest",
    )


def _maybe_redact(chunks: list[RetrievedChunk], suffix: str) -> list[RetrievedChunk]:
    if suffix in MARKDOWN_SUFFIXES:
        return chunks
    return [redact_chunk_pii(chunk) for chunk in chunks]
