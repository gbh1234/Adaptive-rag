"""Offline evaluation metrics: accuracy, precision/recall@k, MRR and latency percentiles."""

from __future__ import annotations

from collections import defaultdict


def accuracy(pairs: list[tuple[str, str]]) -> float:
    if not pairs:
        return 0.0
    return sum(gold == pred for gold, pred in pairs) / len(pairs)


def precision_at_k(relevant: set[str], retrieved: list[str], k: int) -> float:
    top = retrieved[:k]
    if not top:
        return 0.0
    return sum(item in relevant for item in top) / len(top)


def recall_at_k(relevant: set[str], retrieved: list[str], k: int) -> float:
    if not relevant:
        return 0.0
    return sum(item in relevant for item in retrieved[:k]) / len(relevant)


def hit_at_k(relevant: set[str], retrieved: list[str], k: int) -> float:
    return 1.0 if any(item in relevant for item in retrieved[:k]) else 0.0


def mrr(relevant: set[str], retrieved: list[str]) -> float:
    for rank, item in enumerate(retrieved, start=1):
        if item in relevant:
            return 1.0 / rank
    return 0.0


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((p / 100) * (len(ordered) - 1))))
    return float(ordered[index])


def classification_report(pairs: list[tuple[str, str]]) -> dict[str, float]:
    by_label: dict[str, list[bool]] = defaultdict(list)
    for gold, pred in pairs:
        by_label[gold].append(gold == pred)
    return {label: (sum(hits) / len(hits) if hits else 0.0) for label, hits in by_label.items()}
