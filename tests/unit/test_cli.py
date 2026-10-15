from app.cli import format_meta, parse_sse_data_line


def test_parse_sse_skips_noise() -> None:
    assert parse_sse_data_line("") is None
    assert parse_sse_data_line("event: message") is None
    assert parse_sse_data_line("data: [DONE]") is None
    assert parse_sse_data_line("data: not-json") is None


def test_parse_sse_json() -> None:
    line = 'data: {"event": "node", "node": "classify_intent"}'
    assert parse_sse_data_line(line) == {"event": "node", "node": "classify_intent"}


def test_parse_sse_python_repr() -> None:
    line = "data: {'event': 'answer', 'data': {'answer': '你好', 'pending_action': None}}"
    parsed = parse_sse_data_line(line)
    assert parsed is not None
    assert parsed["event"] == "answer"
    assert parsed["data"]["answer"] == "你好"
    assert parsed["data"]["pending_action"] is None


def test_format_meta() -> None:
    text = format_meta(
        {
            "intent": "return_exchange",
            "strategy": "multi",
            "complexity": "multi_hop",
            "latency": {"total_ms": 10975.9},
        }
    )
    assert text == "return_exchange · multi · multi_hop · 11.0s"
