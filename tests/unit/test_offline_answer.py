import pytest

from app.agents.nodes.generate import generate_node
from app.agents.nodes.intent import IntentClassifier, rule_based_intent
from app.core.enums import IntentLabel, RetrievalStrategy
from app.providers.fake import OfflineLLMProvider
from app.schemas.retrieval import RetrievedChunk


def test_greeting_prefix_does_not_hide_order_intent() -> None:
    intent = rule_based_intent("你好，我想取消订单 ORD10003")
    assert intent.label != IntentLabel.GREETING


@pytest.mark.asyncio
async def test_offline_classifier_uses_rules_not_fake_json() -> None:
    intent = await IntentClassifier(OfflineLLMProvider()).classify("电子发票一般多久可以开具？")
    assert intent.label == IntentLabel.FAQ_POLICY


@pytest.mark.asyncio
async def test_offline_answer_quotes_evidence_instead_of_test_json() -> None:
    chunk = RetrievedChunk(
        chunk_id="chunk-1",
        document_id="policy-1",
        title="退货规则",
        content="定制商品不适用七天无理由退货；存在质量问题时可申请售后。",
        score=1.0,
    )
    result = await generate_node(
        {
            "user_query": "定制商品有质量问题还能退吗？",
            "strategy": RetrievalStrategy.MULTI,
            "retrieved_chunks": [chunk],
        },
        OfflineLLMProvider(),
    )
    assert "质量问题" in result["final_answer"]
    assert "label" not in result["final_answer"]
    assert result["citations"][0].chunk_id == "chunk-1"
