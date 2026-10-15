"""Markdown chunking with stable chunk identifiers."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from app.core.enums import DocumentCategory
from app.retrieval.cleaning import normalize_text
from app.schemas.retrieval import RetrievedChunk

_HEADING = re.compile(r"^#{1,3}\s+(.*)$")
MAX_CHUNK_CHARS = 500
OVERLAP_CHARS = 60


def stable_chunk_id(document_id: str, chunk_index: int) -> str:
    """IDs are deterministic across ingest runs so citations stay stable."""
    return f"{document_id}_{chunk_index:02d}"


def document_id_from_path(path: Path) -> str:
    stem = path.stem.lower().replace(" ", "_")
    digest = hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:8]
    return f"{stem}_{digest}"


def chunk_markdown(
    text: str,
    *,
    document_id: str,
    title: str,
    category: DocumentCategory,
    source: str,
    policy_version: str = "v1",
) -> list[RetrievedChunk]:
    sections = _split_sections(text)
    chunks: list[RetrievedChunk] = []
    chunk_index = 0
    for section_title, body in sections:
        for piece in _window(body, MAX_CHUNK_CHARS, OVERLAP_CHARS):
            content = normalize_text(piece, join_hard_breaks=True)
            if not content:
                continue
            chunks.append(
                RetrievedChunk(
                    chunk_id=stable_chunk_id(document_id, chunk_index),
                    document_id=document_id,
                    title=title,
                    content=content,
                    score=0.0,
                    category=category,
                    section=normalize_text(section_title, join_hard_breaks=False) or section_title,
                    chunk_index=chunk_index,
                    policy_version=policy_version,
                    metadata={"source": source, "parser": "markdown"},
                    source="ingest",
                )
            )
            chunk_index += 1
    return chunks


def _split_sections(text: str) -> list[tuple[str, str]]:
    lines = text.splitlines()
    sections: list[tuple[str, str]] = []
    current_title = "body"
    buffer: list[str] = []
    for line in lines:
        heading = _HEADING.match(line)
        if heading:
            if buffer:
                sections.append((current_title, "\n".join(buffer)))
                buffer = []
            current_title = heading.group(1).strip()
        else:
            buffer.append(line)
    if buffer:
        sections.append((current_title, "\n".join(buffer)))
    return sections or [("body", text)]


def _window(text: str, size: int, overlap: int) -> list[str]:
    cleaned = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(cleaned) <= size:
        return [cleaned] if cleaned else []
    pieces: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(len(cleaned), start + size)
        pieces.append(cleaned[start:end])
        if end == len(cleaned):
            break
        start = max(end - overlap, start + 1)
    return pieces
