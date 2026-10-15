from app.config.settings import Settings
from app.core.enums import CompressionLevel
from app.memory.budget import decide_level
from app.memory.compression import apply_compression, compress_tool_results
from app.schemas.agent import ToolResult
from app.schemas.chat import ChatMessage


def test_compression_levels_follow_budget_ratios() -> None:
    settings = Settings(
        token_budget=1000, compress_soft_ratio=0.5, compress_hard_ratio=0.7, auto_compact_ratio=0.85
    )
    assert decide_level(100, settings) == CompressionLevel.NONE
    assert decide_level(600, settings) == CompressionLevel.SOFT_TRUNCATE
    assert decide_level(800, settings) == CompressionLevel.HARD_COMPRESS
    assert decide_level(900, settings) == CompressionLevel.AUTO_COMPACT


def test_soft_truncate_shrinks_tool_payload() -> None:
    fat = ToolResult(name="get_order", success=True, output={"blob": "x" * 2000})
    shrunk = compress_tool_results([fat], CompressionLevel.SOFT_TRUNCATE)
    assert shrunk[0].truncated is True
    assert len(str(shrunk[0].output)) < 800


def test_auto_compact_keeps_recent_messages() -> None:
    settings = Settings(token_budget=50, auto_compact_ratio=0.01)
    messages = [ChatMessage(role="user", content=f"turn {i} " * 20) for i in range(12)]
    window, _, level, _ = apply_compression(messages, [], "摘要", settings)
    assert level == CompressionLevel.AUTO_COMPACT
    assert len(window) < len(messages)
