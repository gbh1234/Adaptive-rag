"""Faithfulness scoring against retrieved evidence."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.exceptions import LLMOutputError, LLMProviderError
from app.prompts.faithfulness import FAITHFULNESS_SYSTEM, FAITHFULNESS_USER
from app.providers.base import LLMProvider
from app.providers.json_parser import parse_model
from app.schemas.retrieval import RetrievedChunk


class FaithfulnessResult(BaseModel):
    supported: bool
    hallucinated_spans: list[str] = Field(default_factory=list)
    rationale: str = ""


class FaithfulnessChecker:
    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def check(
        self,
        *,
        query: str,
        answer: str,
        chunks: list[RetrievedChunk],
        tool_results_text: str,
    ) -> FaithfulnessResult:
        evidence = "\n".join(f"[{c.chunk_id}] {c.content}" for c in chunks[:8]) or "(none)"
        try:
            response = await self._llm.generate(
                [
                    {"role": "system", "content": FAITHFULNESS_SYSTEM},
                    {
                        "role": "user",
                        "content": FAITHFULNESS_USER.format(
                            query=query,
                            answer=answer,
                            evidence=evidence,
                            tool_results=tool_results_text or "(none)",
                        ),
                    },
                ],
                temperature=0.0,
                max_tokens=256,
                response_format={"type": "json_object"},
            )
            return parse_model(response.content, FaithfulnessResult)
        except (LLMProviderError, LLMOutputError):
            return FaithfulnessResult(supported=False, rationale="checker_unavailable")
