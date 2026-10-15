"""Text normalisation, near-duplicate detection and PII redaction."""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata

from app.core.security import mask_pii
from app.schemas.retrieval import RetrievedChunk

logger = logging.getLogger(__name__)

# 64-bit SimHash: Hamming distance at or below this is "near duplicate" (log only).
NEAR_DUP_HAMMING = 3

_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff\u00ad"), None)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_INLINE_SPACE = re.compile(r"[^\S\n]+")
_MULTI_NEWLINE = re.compile(r"\n{3,}")
_CJK_HARD_BREAK = re.compile(r"(?<=[\u4e00-\u9fff])\n(?=[\u4e00-\u9fff])")


def normalize_text(text: str, *, join_hard_breaks: bool = True) -> str:
    """UTF-8-safe cleanup: invisible chars, NFKC, whitespace, optional CJK line-join."""
    if not text:
        return ""
    cleaned = text.translate(_ZERO_WIDTH)
    cleaned = unicodedata.normalize("NFKC", cleaned)
    cleaned = _CONTROL.sub("", cleaned)
    if join_hard_breaks:
        cleaned = _CJK_HARD_BREAK.sub("", cleaned)
    cleaned = _INLINE_SPACE.sub(" ", cleaned)
    cleaned = _MULTI_NEWLINE.sub("\n\n", cleaned)
    return cleaned.strip()


def content_sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def simhash64(text: str) -> int:
    """Character 2-gram SimHash. No extra dependency."""
    if not text:
        return 0
    grams = [text[index : index + 2] for index in range(len(text) - 1)] or [text]
    weights = [0] * 64
    for gram in grams:
        value = int.from_bytes(hashlib.sha256(gram.encode("utf-8")).digest()[:8], "big")
        for bit in range(64):
            weights[bit] += 1 if (value >> bit) & 1 else -1
    fingerprint = 0
    for bit, score in enumerate(weights):
        if score >= 0:
            fingerprint |= 1 << bit
    return fingerprint


def hamming64(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def redact_chunk_pii(chunk: RetrievedChunk) -> RetrievedChunk:
    updated = chunk.model_copy(deep=True)
    updated.content = mask_pii(updated.content)
    html = updated.metadata.get("table_html")
    if html:
        updated.metadata["table_html"] = mask_pii(html)
    return updated


def dedupe_chunks(
    chunks: list[RetrievedChunk],
    *,
    near_dup_bits: int = NEAR_DUP_HAMMING,
) -> list[RetrievedChunk]:
    """Drop exact content duplicates; log cross-document near-duplicates without dropping."""
    kept: list[RetrievedChunk] = []
    seen: dict[str, str] = {}
    for chunk in chunks:
        digest = content_sha1(chunk.content)
        prior = seen.get(digest)
        if prior is not None:
            logger.info(
                "ingest_exact_duplicate_dropped",
                extra={
                    "chunk_id": chunk.chunk_id,
                    "document_id": chunk.document_id,
                    "kept_chunk_id": prior,
                },
            )
            continue
        seen[digest] = chunk.chunk_id
        kept.append(chunk)

    fingerprints = [(chunk.document_id, chunk.chunk_id, simhash64(chunk.content)) for chunk in kept]
    for index, (doc_a, chunk_a, hash_a) in enumerate(fingerprints):
        for doc_b, chunk_b, hash_b in fingerprints[index + 1 :]:
            if doc_a == doc_b:
                continue
            distance = hamming64(hash_a, hash_b)
            if distance <= near_dup_bits:
                logger.info(
                    "ingest_near_duplicate",
                    extra={
                        "chunk_id_a": chunk_a,
                        "chunk_id_b": chunk_b,
                        "document_id_a": doc_a,
                        "document_id_b": doc_b,
                        "hamming": distance,
                    },
                )
    return kept
