"""Terminal rendering helpers for the interactive CLI.

Pure formatting functions plus the stdout writers shared by the client and the
command layer. Kept free of I/O beyond ``stdout`` so it stays easy to test.
"""

from __future__ import annotations

import ast
import json
import sys
from typing import Any

NODE_LABELS = {
    "apply_guardrail": "护栏",
    "classify_intent": "意图",
    "route_complexity": "路由",
    "retrieve_docs": "检索",
    "plan_tasks": "规划",
    "execute_tools": "执行",
    "generate_answer": "生成",
    "refuse_answer": "拒答",
    "check_faithfulness": "忠实度",
    "compact_memory": "记忆",
}

HELP = """直接输入问题，回车后等待回答，然后可以继续问。
  /help  命令说明
  /new   新开会话
  /y     确认写操作（退款/取消等）
  /n     忽略待确认
  /quit  退出
演示单：ORD10001 已发货耳机 · ORD10002 已签收定制杯 · ORD10003 未发货 T 恤
"""


def parse_sse_data_line(line: str) -> dict[str, Any] | None:
    """Parse one SSE ``data:`` line into a dict, or return None for noise."""
    stripped = line.strip()
    if not stripped.startswith("data:"):
        return None
    payload = stripped[5:].strip()
    if not payload or payload == "[DONE]":
        return None
    try:
        parsed: Any = json.loads(payload)
    except json.JSONDecodeError:
        try:
            parsed = ast.literal_eval(payload)
        except (SyntaxError, ValueError):
            return None
    return parsed if isinstance(parsed, dict) else None


def format_meta(body: dict[str, Any]) -> str:
    """Render the one-line metadata summary shown under each answer."""
    bits = [
        body.get("intent") or "-",
        body.get("strategy") or "-",
        body.get("complexity") or "-",
    ]
    total = (body.get("latency") or {}).get("total_ms")
    if isinstance(total, int | float):
        bits.append(f"{total / 1000:.1f}s")
    return " · ".join(str(item) for item in bits)


def emit(text: str) -> None:
    """Write text to stdout and flush, so streaming output appears immediately."""
    sys.stdout.write(text)
    sys.stdout.flush()


def apply_event(
    event: dict[str, Any], *, show_tokens: bool, printed_nodes: bool
) -> tuple[dict[str, Any] | None, bool]:
    """Render one stream event; return the final answer body when it arrives."""
    kind = event.get("event")
    if kind == "node":
        node = str(event.get("node") or "")
        label = NODE_LABELS.get(node, node)
        prefix = "" if printed_nodes else "  "
        emit(f"{prefix}[{label}]")
        return None, True
    if kind == "token" and show_tokens:
        emit(str(event.get("text") or ""))
        return None, printed_nodes
    if kind == "answer":
        data = event.get("data")
        if isinstance(data, dict):
            return data, printed_nodes
    return None, printed_nodes
