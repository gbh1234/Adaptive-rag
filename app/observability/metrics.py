"""In-process Prometheus metrics. Redis is not required for this."""

from prometheus_client import Counter, Histogram

REQUESTS = Counter(
    "cs_requests_total",
    "Chat requests",
    ["strategy", "intent", "status"],
)
REQUEST_LATENCY = Histogram(
    "cs_request_latency_seconds",
    "End-to-end chat latency",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, 16),
)
STAGE_LATENCY = Histogram(
    "cs_stage_latency_seconds",
    "Per-stage latency",
    ["stage"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8),
)
TOOL_CALLS = Counter("cs_tool_calls_total", "Tool invocations", ["tool", "status"])
TOKEN_USAGE = Counter("cs_tokens_total", "LLM tokens", ["kind"])
HALLUCINATION_FLAGS = Counter("cs_hallucination_flags_total", "Faithfulness failures")
ROUTING = Counter("cs_routing_total", "Adaptive-RAG routing decisions", ["strategy"])
