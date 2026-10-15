"""LLM-backed conversation summarisation."""

from app.core.exceptions import LLMOutputError, LLMProviderError
from app.prompts.summary import SUMMARY_SYSTEM, SUMMARY_USER
from app.providers.base import LLMProvider
from app.providers.json_parser import extract_json_object
from app.schemas.chat import ChatMessage


class ConversationSummarizer:
    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def summarize(self, messages: list[ChatMessage]) -> str:
        history = "\n".join(f"{m.role}: {m.content}" for m in messages[-16:])
        try:
            response = await self._llm.generate(
                [
                    {"role": "system", "content": SUMMARY_SYSTEM},
                    {"role": "user", "content": SUMMARY_USER.format(history=history)},
                ],
                temperature=0.0,
                max_tokens=256,
                response_format={"type": "json_object"},
            )
            payload = extract_json_object(response.content)
            return str(payload.get("summary") or "")[:800]
        except (LLMProviderError, LLMOutputError):
            return " ".join(m.content[:40] for m in messages[-4:])
