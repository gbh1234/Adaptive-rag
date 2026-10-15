# 06 · API 参考

> 一句话：业务拒答可以 HTTP 200；系统故障走 4xx/5xx + `error_code`。流式接口使用 SSE，`token` 只包含完成校验后的可展示答案。

## 本章目录

1. [约定](#约定)
2. [探活](#探活)
3. [对话](#对话)
4. [流式](#流式)
5. [管理面](#管理面)
6. [指标](#指标)
7. [错误体](#错误体)

前缀默认 `/api/v1`。OpenAPI：`http://localhost:8000/docs`。  
对应：`app/api/routes/`、`app/schemas/chat.py`、`app/main.py`。

## 约定

每个响应带 `x-trace-id`、`x-request-id`（可从请求头传入）。空 `message` → **422**。

### 代码摘要

```python
# app/schemas/chat.py
class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    user_id: str = Field(default="anonymous", min_length=1, max_length=64)
    session_id: str | None = None
    confirm_action_id: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=128)
```

`stream` 字段在 `ChatRequest` 上存在，但 **`POST /chat` 忽略它**；流式必须打 `/chat/stream`。

## 探活

### `GET /api/v1/health`

进程存活，不查库。`{ "status": "ok" }`。给 Kubernetes **liveness**。

### `GET /api/v1/ready`

硬依赖：**数据库**。Redis / Qdrant / LLM key 写入 `dependencies[]`，失败**不**把 ready 打成 false（避免 DeepSeek 抖动踢光探针）。给 **readiness**。

实现：`app/api/routes/health.py`。`DeepSeekProvider.ping()` 只检查 key 是否配置，不发 `chat/completions`。

## 对话

### `POST /api/v1/chat`

**Request** 见上表。**Response**（`ChatResponse`）：

| 字段 | 含义 |
|---|---|
| `answer` | 对用户可见文本 |
| `session_id` / `trace_id` | 会话与链路 |
| `intent` / `complexity` / `strategy` | 路由解释性字段 |
| `citations` | `document_id` / `title` / `chunk_id` |
| `pending_action` | HITL 待确认 |
| `refused` | 护栏拒答 |
| `error_code` | 业务侧拒绝码（仍可能 HTTP 200） |
| `token_usage` / `latency` | 分阶段毫秒 |

```bash
curl -s localhost:8000/api/v1/chat \
  -H 'content-type: application/json' \
  -H 'x-trace-id: tr_debug_001' \
  -d '{"message":"电子发票多久能开","user_id":"u_demo"}'
```

路由：`app/api/routes/chat.py` → `container.chat_service.chat(...)`。

## 流式

### `POST /api/v1/chat/stream`

SSE。事件 JSON：

| `event` | 何时 |
|---|---|
| `started` | 请求受理 |
| `node` | LangGraph 节点完成（如 `classify_intent`） |
| `token` | 最终答案经忠实度检查后分段发送；不包含模型的 JSON 包装或内部字段 |
| `answer` | 最终 `ChatResponse` |
| `done` | 结束 |

实现：`sse-starlette` + `ChatService.stream`。详见 [05 · Token 流式](05-agents-and-tools.md#token-流式)。

## 管理面

`GET /api/v1/admin/tools`、`/admin/skills`。  
`APP_ENV=production` 必须 `x-admin-token` 且配置 `ADMIN_API_TOKEN`。开发未配 token 则开放（勿对公网暴露）。比对：`hmac.compare_digest`。

## 指标

`GET /metrics`：Prometheus 文本。请求量、分段延迟、路由、工具状态（含 `fallback`）、token、幻觉计数。

## 错误体

系统异常走 HTTP 4xx/5xx：

```json
{ "error_code": "LLM_TIMEOUT", "message": "DeepSeek request timed out", "trace_id": "tr_..." }
```

### 代码摘要

```python
# app/main.py
@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    body = APIErrorBody(
        error_code=exc.error_code,
        message=exc.message,
        trace_id=getattr(request.state, "trace_id", "-"),
    )
    return JSONResponse(status_code=exc.http_status, content=body.model_dump(mode="json"))
```

| HTTP | 典型 `error_code` |
|---|---|
| 400 | `INVALID_REQUEST`、`PROMPT_INJECTION_BLOCKED`、`QUERY_OUT_OF_SCOPE` |
| 401 | `UNAUTHORIZED` |
| 409 | `IDEMPOTENCY_CONFLICT` |
| 422 | 校验失败 |
| 429 | `RATE_LIMITED` |
| 502/503 | `LLM_*`、`VECTOR_DB_UNAVAILABLE`、`DATABASE_UNAVAILABLE`、`TOOL_EXECUTION_FAILED` |
| 500 | `INTERNAL_ERROR`（响应无栈） |

「证据不足」是 **200 + 文案**，不要和 503 混用。枚举：`app/core/error_codes.py`。

---

上一章 [05](05-agents-and-tools.md) · 下一章 [07 · 配置](07-configuration.md)
