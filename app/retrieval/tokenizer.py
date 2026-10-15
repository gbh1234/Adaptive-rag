"""Shared tokenisation helper."""

from __future__ import annotations

import re

try:
    import jieba
except ImportError:  # pragma: no cover
    jieba = None

_HAN = re.compile(r"[\u4e00-\u9fff]+")
_WORD = re.compile(r"[A-Za-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Chinese-aware tokenizer.

    jieba is preferred. If unavailable, fall back to CJK bigrams + latin words
    so BM25 still has a working inverted index.
    """
    text = text.strip().lower()
    if not text:
        return []
    if jieba is not None:
        return [token for token in jieba.lcut(text) if token.strip() and not token.isspace()]
    tokens: list[str] = []
    for block in _HAN.findall(text):
        if len(block) == 1:
            tokens.append(block)
        else:
            tokens.extend(block[i : i + 2] for i in range(len(block) - 1))
    tokens.extend(_WORD.findall(text))
    return tokens
