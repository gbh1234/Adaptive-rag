import json

import httpx
import pytest

from app.agents.nodes.intent import IntentClassifier
from app.agents.nodes.intent_jev import INTENT_CRITERIA, JevIntentClassifier
from app.config.settings import Settings
from app.core.enums import IntentLabel
from app.providers.fake import FakeLLMProvider, OfflineLLMProvider


def settings(**overrides) -> Settings:
    return Settings(**{"jev_api_key": "test-key", "jev_max_retries": 1, **overrides})


def body(label: str = "return_exchange", confidence: float = 0.8) -> dict:
    return {
        "model": "jev-1.13.0",
        "answers": {
            "intent": {
                "type": "choice",
                "choice": label,
                "confidence": confidence,
                "probabilities": {key: float(key == label) for key in INTENT_CRITERIA},
            }
        },
    }


@pytest.mark.asyncio
async def test_jev_uses_typed_choice_and_preserves_chinese() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.typesafe.ai/v1/systemone"
        assert request.headers["authorization"] == "Bearer test-key"
        payload = json.loads(request.content)
        assert payload["state"] == {"user_query": "定制杯质量问题能退吗"}
        assert payload["model"] == "jev-1.13.0"
        question = payload["questions"]["intent"]
        assert question["type"] == "choice"
        assert set(question["criteria"]) == {item.value for item in IntentLabel}
        assert "只输出 JSON" not in question["instructions"]
        return httpx.Response(200, json=body())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await JevIntentClassifier(settings(), client=client).classify(
            "定制杯质量问题能退吗"
        )
    assert result.label == IntentLabel.RETURN_EXCHANGE
    assert result.confidence == 0.8
    assert result.prompt_version == "intent_jev_v1"
    assert result.rationale.startswith("jev:model=")


@pytest.mark.asyncio
@pytest.mark.parametrize("overlay, expected", [(True, "human_handoff"), (False, "refund")])
async def test_overlay_can_be_disabled_for_comparison(overlay, expected) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body("refund")))
    ) as client:
        result = await JevIntentClassifier(
            settings(), client=client, apply_overlay=overlay
        ).classify("人工审核一下退款")
    assert result.label.value == expected


@pytest.mark.asyncio
async def test_missing_key_falls_back_without_network() -> None:
    def handler(_):
        pytest.fail("Missing key must not make a network request")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await JevIntentClassifier(settings(jev_api_key=""), client=client).classify("你好")
    assert result.label == IntentLabel.GREETING
    assert result.rationale.startswith("jev_fallback:")


@pytest.mark.asyncio
async def test_auth_failure_is_not_retried_and_uses_original_classifier() -> None:
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401, json={"error": "invalid key"})

    old_llm = FakeLLMProvider(
        canned={"": '{"label":"faq_policy","confidence":0.6,"prompt_version":"intent_v3"}'}
    )
    fallback = IntentClassifier(old_llm, apply_overlay=False)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await JevIntentClassifier(
            settings(jev_max_retries=3), client=client, fallback=fallback, apply_overlay=False
        ).classify("一个模糊的业务问题")
    assert len(calls) == 1
    assert len(old_llm.calls) == 1
    assert result.label == IntentLabel.FAQ_POLICY
    assert result.rationale.startswith("jev_fallback:")


@pytest.mark.asyncio
async def test_transient_failure_is_retried(monkeypatch) -> None:
    calls = []

    async def no_sleep(_):
        pass

    monkeypatch.setattr("app.core.retry.asyncio.sleep", no_sleep)

    def handler(request):
        calls.append(request)
        return httpx.Response(503) if len(calls) == 1 else httpx.Response(200, json=body())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await JevIntentClassifier(settings(jev_max_retries=2), client=client).classify(
            "定制杯能退吗"
        )
    assert len(calls) == 2
    assert result.prompt_version == "intent_jev_v1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response_body",
    [
        {},
        body("unknown_label"),
        body(confidence=1.5),
        {"model": "jev", "answers": {"intent": {"type": "noul", "noul": 0.9}}},
        {
            "model": "jev",
            "answers": {"intent": {**body()["answers"]["intent"], "probabilities": {}}},
        },
    ],
)
async def test_invalid_responses_are_marked_as_fallback(response_body) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response_body))
    ) as client:
        result = await JevIntentClassifier(settings(), client=client).classify("你好")
    assert result.label == IntentLabel.GREETING
    assert result.rationale.startswith("jev_fallback:LLM_OUTPUT_INVALID;")


@pytest.mark.asyncio
async def test_graph_switches_only_intent_classifier(monkeypatch) -> None:
    from app.agents import graph as graph_module
    from app.core.enums import RetrievalStrategy
    from app.tools.registry import ToolRegistry

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body("greeting")))
    ) as client:
        monkeypatch.setattr(
            graph_module,
            "JevIntentClassifier",
            lambda configured, fallback: JevIntentClassifier(
                configured, fallback=fallback, client=client
            ),
        )
        graph = graph_module.build_graph(
            llm=OfflineLLMProvider(),
            settings=settings(intent_backend="jev"),
            retriever=None,
            reranker=None,
            registry=ToolRegistry(),
        )
        result = await graph.ainvoke({"user_query": "你好"})
    assert result["intent"].prompt_version == "intent_jev_v1"
    assert result["strategy"] == RetrievalStrategy.DIRECT
    assert result["final_answer"].startswith("你好")
