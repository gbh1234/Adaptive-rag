# 03 · 系统架构

> 一句话：Graph 进程内编译一次；DB session 每个请求新建，用 contextvars 交给工具，禁止把连接编进图。

## 本章目录

1. [分层](#分层)
2. [启动与请求生命周期](#启动与请求生命周期)
3. [请求级 DB session](#请求级-db-session)
4. [LangGraph 状态机](#langgraph-状态机)
5. [状态设计](#状态设计)
6. [目录职责](#目录职责)
7. [技术选型](#技术选型三问)

对应：`app/main.py`、`app/services/chat_service.py`、`app/agents/graph.py`、`app/core/request_scope.py`。

## 分层

```text
Request
  → API           协议、Pydantic、trace_id
  → ChatService   限流、UoW、调用已编译 Graph
  → LangGraph     护栏 → 意图 → 路由 → 检索|规划执行 → 生成 → 忠实度 → 压缩
  → Retriever / ToolRegistry / Repository
  → Provider      DeepSeek / Embedding / Cross-Encoder
  → SQLite|Postgres · 内存向量|Qdrant · 可选 Redis
```

面试板书用这张（与 [13 · 面试稿](13-interview-engineering-rag.md) 同一框架）：

```text
┌─────────────────────────────────────────────────────────┐
│ 接入   FastAPI · SSE · 限流 · ChatService               │
├─────────────────────────────────────────────────────────┤
│ 编排   护栏 → 意图 → Adaptive 五路                      │
│        Direct / Refuse / Single / Multi / Agent         │
│        → 生成 → 忠实度 → 压缩                            │
├──────────────────────┬──────────────────────────────────┤
│ 检索  改写 BM25 向量  │ 工具  15 + Skill + MCP + HITL   │
│       RRF · Cross-Encoder │      读失败 Fallback             │
│       Self-RAG ≤3    │                                  │
├──────────────────────┴──────────────────────────────────┤
│ 基础   DeepSeek · Cross-Encoder · DB · Redis · Qdrant/内存     │
└─────────────────────────────────────────────────────────┘
```

### 要点

API 不写业务；Graph 只编排；SQL 在 Repository；模型在 Provider。测试可以 Fake LLM + SQLite。

### 为什么

换协议（HTTP → 内部 RPC）只动 `app/api/`。换模型只动 `providers/`。换检索实现不改节点名。这是面试时「为什么不是一个 `chat()` 函数」的标准答案。

## 启动与请求生命周期

### 要点

进程启动：`lifespan` 里 `build_container`（建表、ingest 知识库、编译 Graph）。  
每个 HTTP：中间件绑 `trace_id` → `ChatService.chat` 开 session → `graph.ainvoke` → commit。

### 代码摘要

```python
# app/main.py
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    container = await build_container(get_settings())
    app.state.container = container
    try:
        yield
    finally:
        await container.aclose()


@app.middleware("http")
async def request_context(request: Request, call_next):
    trace_id = request.headers.get("x-trace-id") or new_trace_id()
    tokens = bind_request_context(trace_id=trace_id, request_id=request_id)
    request.state.trace_id = trace_id
    try:
        response = await call_next(request)
        response.headers["x-trace-id"] = trace_id
        return response
    finally:
        reset_request_context(tokens)
```

```python
# app/services/chat_service.py  （构造时编译图）
self._graph = build_graph(
    llm=llm, settings=settings, retriever=retriever,
    reranker=reranker, registry=self.registry,
)
```

### 为什么

Graph 编译一次：节点闭包里的 Retriever/LLM 是进程级单例，避免每个请求重新 `StateGraph.compile()`。  
`trace_id` 从请求头进来、写回响应头，才能把 nginx / 前端 / 日志串起来。

## 请求级 DB session

### 要点

工具在 Graph 节点里跑，但 SQLAlchemy session 不能存在编译后的图上，否则连接会串请求。用 `contextvars`。

### 代码摘要

```python
# app/core/request_scope.py
_db_session: ContextVar[AsyncSession | None] = ContextVar("db_session", default=None)

def get_db_session() -> AsyncSession:
    session = _db_session.get()
    if session is None:
        raise RuntimeError("no request-scoped database session")
    return session

@asynccontextmanager
async def request_session(factory) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        token = _db_session.set(session)
        try:
            yield session
        finally:
            _db_session.reset(token)
```

`ChatService.chat` 包一层 `async with request_session(...)`，工具通过 `get_db_session()` 拿当前请求的连接。结束时 commit；异常 rollback。

### 为什么

LangGraph 节点签名是 `state -> partial state`，没有「传入 db」的位置。把 session 塞进 `AgentState` 会让状态不可序列化、也难测。contextvars 是 async 安全的请求级槽位。

## LangGraph 状态机

### 要点

节点名不能和 `AgentState` 的 key 同名（所以是 `classify_intent` 不是 `intent`）。  
条件边只根据 `strategy` 分五路。

### 代码摘要

```python
# app/agents/graph.py
def _route_after_complexity(state: AgentState) -> str:
    strategy = state.get("strategy") or RetrievalStrategy.SINGLE
    return {
        RetrievalStrategy.DIRECT: "generate_answer",
        RetrievalStrategy.REFUSE: "refuse_answer",
        RetrievalStrategy.SINGLE: "retrieve_docs",
        RetrievalStrategy.MULTI: "retrieve_docs",
        RetrievalStrategy.AGENT: "plan_tasks",
    }[strategy]
```

```text
START → apply_guardrail
          ├ refused → refuse_answer → compact_memory → END
          └ classify_intent → route_complexity
                 ├ DIRECT / 生成
                 ├ REFUSE / 拒答
                 ├ SINGLE|MULTI / retrieve_docs → generate_answer
                 └ AGENT / plan_tasks → execute_tools → generate_answer
          → check_faithfulness → compact_memory → END
```

`SINGLE` 与 `MULTI` 都进 `retrieve_docs`，节点内部再看 `strategy` 决定是否走 Self-RAG（见 [04](04-adaptive-rag.md)）。

### 为什么

条件边比「在 generate 里再 if」清晰：SSE 能按节点名推进度；`MAX_AGENT_STEPS` 有界；单测可以只跑 `planner_node`。

## 状态设计

### 要点

`AgentState` 是 `TypedDict, total=False`：节点返回的 dict **替换**列出的 key。  
**不用** `Annotated[list, add]` 无限 append messages，压缩在 `compact_memory` 显式做。

### 代码摘要

```python
# app/agents/state.py
class AgentState(TypedDict, total=False):
    user_query: str
    intent: IntentResult | None
    strategy: RetrievalStrategy | None
    retrieved_chunks: list[RetrievedChunk]
    plan: AgentPlan | None
    tool_results: list[ToolResult]
    pending_action: ActionProposal | None
    final_answer: str | None
    token_usage: TokenUsage
    latency: LatencyBreakdown
```

API / Tool 边界用 Pydantic（`ChatRequest`、`PlanStep`、各工具 `input_model`）。图内部用 TypedDict 减少校验开销。

### 为什么

reducer 自动 append 会在长会话里把 128k 预算打爆且难以断言。显式压缩节点让「何时摘要」可测、可观测。

## 目录职责

| 路径 | 职责 |
|---|---|
| `app/api/` | 路由、DI |
| `app/schemas/` | 请求/响应/检索/订单 |
| `app/services/` | ChatService、容器、种子 |
| `app/agents/` | 状态机与节点 |
| `app/retrieval/` | 解析、清洗、切分、BM25、向量、RRF、Adaptive、Self-RAG |
| `app/tools/` | 15 工具、权限、Registry |
| `app/mcp/` | MCP → 同一套 `Tool` |
| `app/skills/` | 按需加载的流程 JSON |
| `app/repositories/` | 订单/会话/幂等 |
| `app/providers/` | LLM / Embedding / Rerank |
| `app/guardrails/` | 注入、边界、忠实度 |
| `app/memory/` | Token 预算 |
| `app/prompts/` | 版本化模板 |
| `app/observability/` | 日志、metrics、context |

## 技术选型（三问）

每个中间件应能回答：为什么用、为什么不是 X、不用会怎样。

| 组件 | 为什么 | 不用会怎样 |
|---|---|---|
| LangGraph | 条件边、步数上限、可测节点 | 路由糊在一个函数 |
| FastAPI | 校验、OpenAPI、SSE | 手写协议 |
| DeepSeek | OpenAI 兼容，`LLMProvider` 隔离 | 测试用 Fake |
| RRF | BM25 与余弦量纲不同，融 **rank** | 加分会偏一路 |
| Cross-Encoder | query+doc 联合编码打分 | 近义政策只靠词面/RRF 排不稳 |
| Qdrant | 可独立部署、稳定 point id | 本地内存库也能跑 |
| Postgres | 订单/审计/幂等 | 本地 SQLite |
| Redis | 限流 + 政策缓存；故障 fail-open | 进程内实现 |

Kafka / Celery / ES **没有**上：没有出站队列或检索日志湖的真实需求。

---

上一章 [02](02-getting-started.md) · 下一章 [04 · 检索](04-adaptive-rag.md)
