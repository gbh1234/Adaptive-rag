# 可观测性

> 本文是第十二部分的第二篇正文，它讲清系统如何把内部状态暴露出来。全文分为五节，前两节讲日志与追踪，中间两节讲指标与排障，最后一节给出反例与练习。

---

## 一、为什么需要可观测性

线上系统出问题时，工程师面对的第一个困难往往是"不知道发生了什么"。用户说"刚才那条回复不对"，但系统没有留下任何线索，工程师只能靠猜。

**可观测性（Observability）** 要解决的正是这个问题：它让系统在运行时把关键信息暴露出来，使工程师能够重建一次请求的完整过程。

本项目的可观测性由三部分组成。

| 组成 | 记录什么 |
| --- | --- |
| 日志 | 发生了什么 |
| 追踪 | 这条请求经过了哪些环节 |
| 指标 | 整体趋势如何 |

三者配合，构成一个可排障的系统。

---

## 二、日志与追踪

### 2.1 结构化日志

本项目的日志采用 JSON 格式，`app/observability/logging.py` 中的 `configure_logging` 把日志字段固定为时间、级别、记录器、消息、trace_id 与 request_id。

JSON 格式的好处是便于机器检索：工程师可以按 trace_id 过滤出一次请求的全部日志，而不必用肉眼在文本里翻找。

日志还有一层脱敏。`ContextFilter` 在写入每条日志前调用 `mask_pii`，屏蔽消息里的敏感信息。

> 这里有一条边界必须讲清：日志脱敏是日志层的防护，它不能替代知识库脱敏。二者是两件事，读者不应把它们混为一谈。

### 2.2 trace_id 贯穿全链路

本项目的 trace_id 从请求头进入，经过中间件绑定到上下文变量，再由日志与响应头带出。

中间件在 `app/main.py` 中读取请求头里的 `x-trace-id`，如果没有就生成一个新的；处理完成后，它把 trace_id 写回响应头。这样，前端、网关与后端日志就能通过同一个 trace_id 串联起来。

上下文变量由 `app/observability/context.py` 中的 `bind_request_context` 与 `reset_request_context` 管理。使用上下文变量而不是全局变量，是因为它天然支持异步并发：每个请求有自己的一份上下文，不会相互串扰。

---

## 三、指标

本项目在 `app/observability/metrics.py` 中用进程内的 Prometheus 客户端暴露指标，它不依赖 Redis 或外部采集器。核心指标包括几类。

| 指标 | 打标签维度 |
| --- | --- |
| 请求计数 | 策略、意图、状态 |
| 延迟直方图 | 端到端、分阶段（意图 / 检索 / 模型 / 工具） |
| 工具调用计数 | 工具名、状态（成功 / 拒绝 / 错误 / 幂等 / 降级） |
| token 用量与幻觉计数 | 用量与次数 |

`app/observability/metrics.py` —— 指标定义

```python
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
```

`REQUESTS` 用 `["strategy", "intent", "status"]` 三个标签维度区分请求，`TOOL_CALLS` 用 `["tool", "status"]` 区分工具名与调用结果，这些标签正是上文表格里"打标签维度"一列的来源。两个 `Histogram` 分别记录端到端与分阶段延迟，`buckets` 决定了分位统计的粒度，`STAGE_LATENCY` 额外的 `["stage"]` 标签让它能按意图、检索、模型、工具拆开观测。

这些指标的价值在于趋势。单看一条日志只能知道"这一次发生了什么"，而看指标能知道"最近一段时间整体在变好还是变坏"。例如，如果工具拒绝的计数突然上升，工程师就能及时发现权限配置出了问题。

> 日志回答"这一次"，指标回答"最近整体"，二者互补。

---

## 四、如何排障

排障有一个固定的顺序：先看分段，再看追踪，最后看日志。

1. **第一步是看分段延迟。** 一条请求的总延迟偏高，可能是模型慢，也可能是检索慢，还可能是工具慢。分阶段延迟能立刻定位到是哪一段慢。本项目的实测显示，P95 数秒的请求通常模型占大头。
2. **第二步是看追踪。** 确定了大致的环节之后，工程师用 trace_id 把这次请求经过的所有节点与工具调用串起来，看它走了哪条策略、调了哪些工具、在哪里失败。
3. **第三步是看日志。** 在具体的节点上，工程师查看详细日志，找到失败的根因。由于日志已经脱敏，工程师不必担心在排障时泄露敏感信息。

> 排障的顺序是固定的：先分段定位环节，再用 trace_id 串链路，最后看日志找根因。

---

## 五、反例与练习

假设系统没有 trace_id，也没有结构化日志。用户反馈"刚才那条回复不对"，工程师只能去日志里搜用户的问题文本，但日志是纯文本、格式不统一，搜出来的结果无法对应到具体的请求与执行链路。工程师无法判断那条回复走了哪条策略、用了哪些证据，也就无法复现问题。

> 这个反例说明，可观测性不是锦上添花，而是线上排障的必要条件。

本部分的练习有两项。

- **第一项，排障演练。** 读者应假设一条请求延迟偏高，说明如何用分段延迟与 trace_id 定位到具体环节。
- **第二项，设计指标。** 读者应说明为什么工具调用计数要按状态打标签，而不是只统计总次数。

> **指标回指。** 本篇对应的指标是第 11 部分"评测体系"中的端到端延迟分段。评测中的分段数据，正是由本篇介绍的指标机制采集而来。读者在阅读下一篇时，可以对照理解这些能力如何被部署到线上。

---

**本篇涉及的源码：** `app/observability/logging.py`、`app/main.py`、`app/observability/context.py`、`app/observability/metrics.py`
