"""Unit tests for the offline eval metrics and the harness's pure helpers.

`eval/` was the only package at 0% coverage while every resume number is
derived from it, so these tests pin down both the arithmetic in
`eval/metrics.py` and the pure helpers in `eval/runner.py`.
"""

from __future__ import annotations

from pathlib import Path

from eval.metrics import (
    accuracy,
    classification_report,
    hit_at_k,
    mrr,
    percentile,
    precision_at_k,
    recall_at_k,
)
from eval.runner import (
    _doc_stem,
    _keyword_hit,
    _resume_bullets,
    _summarize_scores,
    _unique_stems,
    load_jsonl,
)


class _Chunk:
    """Minimal stand-in for RetrievedChunk; `_unique_stems` only reads document_id."""

    def __init__(self, document_id: str) -> None:
        self.document_id = document_id


# --- accuracy ---------------------------------------------------------------


def test_accuracy_empty_pairs_is_zero() -> None:
    assert accuracy([]) == 0.0


def test_accuracy_all_correct() -> None:
    assert accuracy([("faq", "faq"), ("refund", "refund")]) == 1.0


def test_accuracy_partial() -> None:
    assert accuracy([("faq", "faq"), ("refund", "logistics")]) == 0.5


# --- precision@k ------------------------------------------------------------


def test_precision_at_k_empty_retrieval() -> None:
    assert precision_at_k({"a"}, [], 3) == 0.0


def test_precision_at_k_counts_only_top_k() -> None:
    # top-3 = a, b, c -> 2 of 3 are relevant
    assert precision_at_k({"a", "c"}, ["a", "b", "c", "d"], 3) == 2 / 3


def test_precision_at_k_when_k_exceeds_length() -> None:
    assert precision_at_k({"a", "b"}, ["a", "b"], 10) == 1.0


# --- recall@k ---------------------------------------------------------------


def test_recall_at_k_without_relevant_set() -> None:
    assert recall_at_k(set(), ["a"], 1) == 0.0


def test_recall_at_k_only_scans_top_k() -> None:
    # relevant "b" sits at rank 3, so k=2 must miss it
    assert recall_at_k({"b"}, ["a", "x", "b"], 2) == 0.0
    assert recall_at_k({"b"}, ["a", "x", "b"], 3) == 1.0


# --- hit@k ------------------------------------------------------------------


def test_hit_at_k_true_on_any_overlap() -> None:
    assert hit_at_k({"z"}, ["a", "z"], 2) == 1.0


def test_hit_at_k_false_outside_window() -> None:
    assert hit_at_k({"z"}, ["a", "z"], 1) == 0.0


# --- MRR --------------------------------------------------------------------


def test_mrr_first_position() -> None:
    assert mrr({"a"}, ["a", "b"]) == 1.0


def test_mrr_second_position() -> None:
    assert mrr({"b"}, ["a", "b"]) == 0.5


def test_mrr_without_hit() -> None:
    assert mrr({"z"}, ["a", "b"]) == 0.0


# --- percentile -------------------------------------------------------------


def test_percentile_empty_is_zero() -> None:
    assert percentile([], 95) == 0.0


def test_percentile_single_value() -> None:
    assert percentile([42.0], 50) == 42.0


def test_percentile_endpoints_are_min_and_max() -> None:
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert percentile(values, 0) == 10.0
    assert percentile(values, 100) == 50.0


def test_percentile_picks_nearest_index() -> None:
    values = [1.0, 2.0, 3.0, 4.0]
    # round(0.5 * 3) == 2 under banker's rounding -> ordered[2]
    assert percentile(values, 50) == 3.0


# --- classification_report --------------------------------------------------


def test_classification_report_groups_by_gold_label() -> None:
    report = classification_report([("faq", "faq"), ("faq", "x"), ("refund", "refund")])
    assert report == {"faq": 0.5, "refund": 1.0}


def test_classification_report_empty() -> None:
    assert classification_report([]) == {}


# --- runner: load_jsonl -----------------------------------------------------


def test_load_jsonl_skips_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "rows.jsonl"
    path.write_text('{"a": 1}\n\n   \n{"a": 2}\n', encoding="utf-8")
    assert load_jsonl(path) == [{"a": 1}, {"a": 2}]


def test_load_jsonl_on_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    assert load_jsonl(path) == []


# --- runner: _doc_stem / _unique_stems --------------------------------------


def test_doc_stem_strips_last_underscore_suffix() -> None:
    assert _doc_stem("return_policy_12") == "return_policy"


def test_doc_stem_without_suffix_is_unchanged() -> None:
    assert _doc_stem("returnpolicy") == "returnpolicy"


def test_unique_stems_preserves_first_seen_order() -> None:
    chunks = [_Chunk("a_0"), _Chunk("b_1"), _Chunk("a_2"), _Chunk("c_0")]
    assert _unique_stems(chunks) == ["a", "b", "c"]


# --- runner: _summarize_scores ----------------------------------------------


def test_summarize_scores_empty_is_all_zero() -> None:
    assert _summarize_scores([]) == {"mean": 0.0, "min": 0.0, "max": 0.0}


def test_summarize_scores_rounds_to_four_places() -> None:
    assert _summarize_scores([1.0, 2.0, 4.0]) == {"mean": 2.3333, "min": 1.0, "max": 4.0}


# --- runner: _keyword_hit ---------------------------------------------------


def test_keyword_hit_without_keywords_is_true() -> None:
    assert _keyword_hit("anything", []) is True


def test_keyword_hit_requires_every_keyword() -> None:
    assert _keyword_hit("七天无理由退货", ["七天", "退货"]) is True
    assert _keyword_hit("七天无理由退货", ["七天", "发票"]) is False


# --- runner: _resume_bullets ------------------------------------------------


def _report() -> dict:
    return {
        "intent_rules": {"accuracy": 0.62},
        "intent_v1": {"accuracy": 0.80},
        "intent_v2": {"accuracy": 0.88},
        "intent_v3": {"accuracy": 0.91, "n": 100},
        "intent_overlay": {"accuracy": 0.93},
        "retrieval": {
            "systems": [
                {
                    "backend": "bm25",
                    "precision_at_1": {"mean": 0.50},
                    "recall_at_3": {"mean": 0.70},
                    "mrr": {"mean": 0.60},
                },
                {
                    "backend": "dense-hash",
                    "precision_at_1": {"mean": 0.55},
                    "recall_at_3": {"mean": 0.75},
                },
                {
                    "backend": "hybrid+rrf",
                    "precision_at_1": {"mean": 0.60},
                    "recall_at_3": {"mean": 0.80},
                },
                {
                    "backend": "hybrid+cross-encoder",
                    "precision_at_1": {"mean": 0.70},
                    "recall_at_3": {"mean": 0.85},
                },
            ]
        },
        "generation": {
            "naive_no_context": {"faithfulness": 0.40, "hallucination_rate": 0.50},
            "rag": {"faithfulness": 0.70},
            "rag_plus_self_check": {"faithfulness": 0.90, "hallucination_rate": 0.10},
            "hallucination_relative_drop": 0.80,
        },
        "e2e": {
            "n": 16,
            "latency_ms": {"p50": 900, "p95": 2100},
            "refuse_accuracy": 0.90,
            "keyword_hit": 0.85,
        },
    }


def test_resume_bullets_empty_report() -> None:
    assert _resume_bullets({}) == []


def test_resume_bullets_cover_every_section() -> None:
    bullets = _resume_bullets(_report())
    # intent + bm25 + dense + hybrid+rrf + cross-encoder + 2 generation + e2e
    assert len(bullets) == 8

    assert bullets[0].startswith("意图识别：100 条")
    assert "intent_v1 80.0% → intent_v2 88.0% → intent_v3+overlay 91.0%" in bullets[0]
    assert "规则 62.0%" in bullets[0]
    assert "仅覆盖层 93.0%" in bullets[0]

    assert any("BM25 Precision@1 50.0%，Recall@3 70.0%，MRR 0.60" in b for b in bullets)
    assert any("dense-hash Precision@1 55.0%，Recall@3 75.0%" in b for b in bullets)
    assert any("hybrid+rrf Precision@1 60.0%，Recall@3 80.0%" in b for b in bullets)
    assert any("Hybrid+Cross-Encoder Precision@1 70.0%，Recall@3 85.0%" in b for b in bullets)
    assert any("Faithfulness：无检索 40% → RAG 70% → RAG+自纠错 90%" in b for b in bullets)
    assert any("幻觉率：无检索 50% → RAG+自纠错 10%，相对下降 80%" in b for b in bullets)
    assert any("E2E 16 条：P50 900ms / P95 2100ms" in b for b in bullets)


def test_resume_bullets_without_earlier_intent_versions() -> None:
    bullets = _resume_bullets({"intent_v3": {"accuracy": 0.90, "n": 10}})
    assert bullets == ["意图识别：10 条 intent_v3+overlay 90.0%"]
