"""Compare the old and Jev classifiers without changing the running API.

python -m eval.compare_intent --limit 10 --no-overlay
python -m eval.compare_intent --backend jev --limit 1 --output data/local/jev_intent.json

Both backends use the same samples and overlay setting. Fallbacks are counted
explicitly; the existing dataset is a development set, not a held-out test set.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import Counter
from pathlib import Path

from app.agents.nodes.intent import IntentClassifier
from app.agents.nodes.intent_jev import JevIntentClassifier
from app.config.settings import get_settings
from app.core.constants import PROMPT_VERSION_INTENT
from app.providers.deepseek import DeepSeekProvider
from app.providers.fake import OfflineLLMProvider
from eval.metrics import accuracy, percentile
from eval.runner import INTENT_PATH, load_jsonl


async def compare(*, backend: str, limit: int, overlay: bool) -> dict:
    settings = get_settings()
    if backend in {"both", "deepseek"} and not settings.llm_configured:
        raise SystemExit("Configure DEEPSEEK_API_KEY before comparing DeepSeek.")
    if backend in {"both", "jev"} and not settings.jev_api_key.get_secret_value():
        raise SystemExit("Configure JEV_API_KEY in .env; never paste the key into a report.")
    llm = DeepSeekProvider(settings) if settings.llm_configured else OfflineLLMProvider()
    old = IntentClassifier(llm, apply_overlay=overlay)
    new = JevIntentClassifier(settings, fallback=old, apply_overlay=overlay)
    classifiers = {"deepseek": old, "jev": new}
    selected = ["deepseek", "jev"] if backend == "both" else [backend]
    rows = load_jsonl(INTENT_PATH)[:limit]
    cases: list[dict] = []
    try:
        # Sequential requests avoid turning a comparison into a rate-limit test.
        for row in rows:
            case = {"id": row["id"], "query": row["query"], "gold": row["intent"]}
            for name in selected:
                started = time.perf_counter()
                prediction = await classifiers[name].classify(row["query"])
                is_fallback = prediction.rationale.startswith("jev_fallback:") or (
                    prediction.prompt_version != PROMPT_VERSION_INTENT
                    if name == "deepseek"
                    else prediction.prompt_version != "intent_jev_v1"
                )
                case[name] = {
                    **prediction.model_dump(mode="json"),
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    "fallback": is_fallback,
                    "correct": prediction.label.value == row["intent"],
                }
            cases.append(case)
    finally:
        closer = getattr(llm, "aclose", None)
        if closer:
            await closer()
    summaries = {}
    for name in selected:
        predictions = [case[name] for case in cases]
        latencies = [item["latency_ms"] for item in predictions]
        summaries[name] = {
            "accuracy": accuracy([(case["gold"], case[name]["label"]) for case in cases]),
            "fallback_count": sum(item["fallback"] for item in predictions),
            "overlay_override_count": sum(";overlay:" in item["rationale"] for item in predictions),
            "prompt_versions": dict(Counter(item["prompt_version"] for item in predictions)),
            "latency_p50_ms": percentile(latencies, 50),
            "latency_p95_ms": percentile(latencies, 95),
        }
    return {
        "dataset": str(INTENT_PATH),
        "n": len(cases),
        "apply_overlay": overlay,
        "jev_model": settings.jev_model,
        "note": "Development-set comparison; accuracy includes reported fallback cases.",
        "summary": summaries,
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare DeepSeek and Jev intent classifiers")
    parser.add_argument("--backend", choices=["both", "deepseek", "jev"], default="both")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--no-overlay", action="store_true", help="Disable rule correction on both")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    report = asyncio.run(
        compare(backend=args.backend, limit=args.limit, overlay=not args.no_overlay)
    )
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
