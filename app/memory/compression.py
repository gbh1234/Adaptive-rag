"""Progressive context compression.

50–70% budget: truncate bulky tool payloads.
70–85%: shrink older turns to bullets.
>85%: auto-compact — keep last K turns + a running summary.
"""

from __future__ import annotations

from app.config.settings import Settings
from app.core.enums import CompressionLevel
from app.memory.budget import decide_level, estimate_tokens, messages_tokens
from app.schemas.agent import ToolResult
from app.schemas.chat import ChatMessage

KEEP_RECENT_TURNS = 4
TOOL_SOFT_CHARS = 400
TOOL_HARD_CHARS = 160


def compress_tool_results(
    results: list[ToolResult],
    level: CompressionLevel,
) -> list[ToolResult]:
    limit = {
        CompressionLevel.NONE: 10_000,
        CompressionLevel.SOFT_TRUNCATE: TOOL_SOFT_CHARS,
        CompressionLevel.HARD_COMPRESS: TOOL_HARD_CHARS,
        CompressionLevel.AUTO_COMPACT: TOOL_HARD_CHARS,
    }[level]
    compressed: list[ToolResult] = []
    for result in results:
        cloned = result.model_copy(deep=True)
        text = str(cloned.output)
        if len(text) > limit:
            cloned.output = {"truncated": True, "preview": text[:limit]}
            cloned.truncated = True
        compressed.append(cloned)
    return compressed


def sliding_window(
    messages: list[ChatMessage], *, keep: int = KEEP_RECENT_TURNS
) -> list[ChatMessage]:
    if len(messages) <= keep * 2:
        return list(messages)
    return list(messages[-(keep * 2) :])


def apply_compression(
    messages: list[ChatMessage],
    tool_results: list[ToolResult],
    summary: str,
    settings: Settings,
) -> tuple[list[ChatMessage], list[ToolResult], CompressionLevel, str]:
    used = messages_tokens(messages) + estimate_tokens(summary)
    level = decide_level(used, settings)
    tools = compress_tool_results(tool_results, level)
    if level in {CompressionLevel.HARD_COMPRESS, CompressionLevel.AUTO_COMPACT}:
        window = sliding_window(messages)
        if summary:
            window = [ChatMessage(role="system", content=f"对话摘要：{summary}")] + window
        return window, tools, level, summary
    if level == CompressionLevel.SOFT_TRUNCATE:
        return messages, tools, level, summary
    return messages, tools, level, summary
