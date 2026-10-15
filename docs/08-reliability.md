# 08 · 可靠性与可观测性

> 一句话：超时拆分；重试只打瞬时错误且 full jitter；限流 Redis 挂了 fail-open，鉴权 fail-closed。

## 本章目录

1. [超时](#超时)
2. [重试](#重试)
3. [失败语义](#失败语义)
4. [探活](#探活)
5. [日志与指标](#日志与指标)

对应：`app/core/retry.py`、`app/providers/deepseek.py`、`app/observability/`。

## 超时

### 要点

`httpx.Timeout(connect=3, read=LLM_TIMEOUT_SECONDS, write=10, pool=5)`。禁止默认无限读。Qdrant 5s；sync 调用包在 `asyncio.to_thread`。

### 代码摘要

```python
# app/providers/deepseek.py
self._client = httpx.AsyncClient(
    base_url=settings.deepseek_base_url.rstrip("/"),
    timeout=httpx.Timeout(connect=3.0, read=settings.llm_timeout_seconds, write=10.0, pool=5.0),
)
```

## 重试

### 要点

Full jitter：`sleep = random(0, min(cap, base * 2^attempt))`。多实例不会在同一时刻打爆。  
**重试**：超时、连接错误、408/429/502/503/504。  
**不重试**：400、401、403、404、422。

### 代码摘要

```python
# app/core/retry.py
RETRYABLE_HTTP_STATUS = frozenset({408, 429, 500, 502, 503, 504})
NON_RETRYABLE_HTTP_STATUS = frozenset({400, 401, 403, 404, 422})

def _full_jitter_delay(attempt: int, base: float, cap: float) -> float:
    ceiling = min(cap, base * (2**attempt))
    return random.uniform(0.0, ceiling)
```

`DeepSeekProvider.generate` 包在 `with_exponential_backoff` 里。**stream 不在中途重试**（已经向用户推过 token）。

单测：`tests/unit/test_retry.py`。

### 为什么

401 若重试，坏密钥会被放大成一串无效计费。指数退避若无 jitter，所有 replica 在同一时刻醒来（retry storm）。

## 失败语义

| 情况 | 对用户 | HTTP |
|---|---|---|
| 政策证据不足 | 200，不确定/转人工 | 业务 |
| 注入、越权 | 200，`refused=true` | 护栏 |
| DeepSeek 超时 | `LLM_TIMEOUT` | 503 |
| 两路检索都失败 | `VECTOR_DB_UNAVAILABLE` | 503 |
| 数据库挂 | `DATABASE_UNAVAILABLE` | 503 |
| 限流 | `RATE_LIMITED` | 429；Redis 挂 **fail-open** |

限流 fail-open：限流组件故障不应把整站客服打挂。鉴权相反，必须 fail-closed。

## 探活

- liveness = `/api/v1/health`
- readiness = `/api/v1/ready`（以 DB 为准）

不要把 LLM ping 做成一次 `chat/completions`。

## 日志与指标

JSON 行：`timestamp`、`level`、`logger`、`trace_id`、`request_id`。`mask_pii`。禁止打 API Key。Prompt/tool 默认不全量落盘。

`GET /metrics`：请求量、策略/意图、intent/retrieval/llm/tool 分段延迟、工具 `ok|denied|error|idempotent|fallback`、token、幻觉计数。

排障：先看分段。评测里 P95 数秒的请求通常 LLM 占大头。用 `x-trace-id` 把 HTTP → 意图 → 检索 → 工具串起来。

---

上一章 [07](07-configuration.md) · 下一章 [09 · 安全](09-security.md)
