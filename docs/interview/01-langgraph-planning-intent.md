# LangGraph 状态机、规划执行、意图与评测

> 对应简历句：**基于 LangGraph 搭建核心状态机，规划器与执行器，统一接入核心工具，实现流式输出与指数退避 + 抖动重试；解析意图识别，采用 Prompt-template + DeepSeek v3 构建意图路由节点并通过 LLM 自主决策分解子任务并调用工具，自建 100 条测试 query 测试意图识别准确率达到 97%。**
>
> 用法：每个问题先给 **30 秒开口**，再给对照仓库的详细答案。数字只引用 `[eval/MEASURED.md](../../eval/MEASURED.md)`（2026-08-22）。行为只写代码里真实存在的；没做的会标明。
>
> 正文先读 [Chapter 1 · 执行图](chapter1.md)。配套：[03 架构](../03-architecture.md) · [05 智能体](../05-agents-and-tools.md) · [08 可靠性](../08-reliability.md) · [10 评测](../10-evaluation.md) · [面试维度索引](../16-interview-bagu-map.md)。

## 本章目录

1. [LangGraph 状态机](#1-langgraph-状态机)
2. [规划器与执行器](#2-规划器与执行器)
3. [统一接入核心工具](#3-统一接入核心工具)
4. [流式输出](#4-流式输出)
5. [指数退避 + 抖动重试](#5-指数退避--抖动重试)
6. [意图识别与路由](#6-意图识别与路由)
7. [100 条 / 97% 数字口径](#7-100-条--97-数字口径)
8. [跨模块综合题](#8-跨模块综合题)
9. [面试官在验证什么](#9-面试官在验证什么)

---

## 1. LangGraph 状态机

### 1.1 为什么用 LangGraph，而不是一条函数流水线或纯 ReAct 循环？

**开口：** 客服请求要按复杂度分叉：问候不检索、政策走 Hybrid、退款走规划器、注入直接拒。条件边把分叉变成可单测节点，SSE 能按节点名推进度；ReAct 逐步 Thought/Action 在写操作上不可测、也不安全。

**详细答案：**

电商客服不是「永远 embed → top-k → 拼 prompt」。同一入口会遇到五类事：打招呼、政策问答、查订单、申请退款、越权注入。如果写成一个 400 行 `if/else` 函数：

- 单测只能 mock 整条链路，无法只跑 `planner_node`；
- SSE 没法按「节点完成」推进度；
- 步数上限、HITL 待确认、拒答都会糊在 generate 里。

本仓库用 LangGraph 的 **节点 + 条件边** 把阶段拆开，图在 `app/agents/graph.py`。LangGraph **只负责编排**，意图、检索、权限、HITL 都是自研模块，不是把业务交给框架 Agent。

不选标准 ReAct 的原因：退款、取消是有副作用的写操作。逐步让模型输出 `Thought/Action` 字符串再 parse，等于每一步都可能改计划、乱调 `cancel_order`。本仓库 Agent 叉是 **一次 JSON 计划、再顺序执行**（Plan-and-Execute），观察进 `tool_results`，到生成节点才用，中间不让模型改计划。

**别吹：** 不要说「全程自主 Agent」。只有 `strategy=agent` 那一叉像 Agent；问候走 Direct，政策走检索。

---

### 1.2 图上有哪些节点、条件边怎么走？一次请求从 START 到 END 经过哪几步？

**开口：** `START → 护栏 → 意图 → 复杂度`，然后五路：Direct 生成、Refuse 拒答、Single/Multi 检索、Agent 规划执行；生成后一律忠实度 → 记忆压缩 → END。

**详细答案：**

节点（名字刻意不和 `AgentState` 的 key 同名）：

| 节点                 | 职责                                  |
| -------------------- | ------------------------------------- |
| `apply_guardrail`    | 注入 / 越权检测                       |
| `classify_intent`    | DeepSeek JSON + 覆盖层                |
| `route_complexity`   | Adaptive 路由，写出 `strategy`        |
| `retrieve_docs`      | Single 一次 Hybrid；Multi 走 Self-RAG |
| `plan_tasks`         | Planner，可能产出 `pending_action`    |
| `execute_tools`      | 按计划调工具；未确认则空跑            |
| `generate_answer`    | 生成；HITL 待确认时只回确认文案       |
| `refuse_answer`      | 固定拒答话术                          |
| `check_faithfulness` | 忠实度；失败则自纠错一次              |
| `compact_memory`     | 128k 预算三级压缩                     |

条件边两处：

1. 护栏后：`refused` → `refuse_answer`，否则 `classify_intent`。
2. 复杂度后按 `strategy`：

```text
DIRECT  → generate_answer
REFUSE  → refuse_answer
SINGLE  → retrieve_docs → generate_answer
MULTI   → retrieve_docs → generate_answer   # 节点内部再走 Self-RAG
AGENT   → plan_tasks → execute_tools → generate_answer
```

`SINGLE` 与 `MULTI` 共用 `retrieve_docs`，避免两套几乎一样的边。拒答路径 **跳过忠实度**，直接 `compact_memory`。正常生成路径：`generate_answer → check_faithfulness → compact_memory → END`。

一次「查政策」请求典型路径：

```text
START → apply_guardrail → classify_intent → route_complexity
      → retrieve_docs → generate_answer → check_faithfulness → compact_memory → END
```

一次「申请退款且尚未确认」：

```text
… → plan_tasks（写出 pending_action）→ execute_tools（空 tool_results）
  → generate_answer（返回确认文案）→ check_faithfulness（跳过）→ compact_memory → END
```

代码：`app/agents/graph.py` 的 `_route_after_complexity` 与 `build_graph`。

---

### 1.3 `AgentState` 里有哪些字段？节点为什么不能和 state key 同名？

**开口：** 状态是 `TypedDict`，节点返回的 dict **替换**列出的 key。节点若叫 `intent`，LangGraph 会把节点输出和状态字段搅在一起，所以节点叫 `classify_intent`。

**详细答案：**

`AgentState`（`app/agents/state.py`）是 `TypedDict, total=False`，核心字段：

- 身份与会话：`trace_id`、`session_id`、`user_id`、`user_query`、`messages`、`summary`
- 路由：`intent`、`complexity`、`strategy`、`query_complexity`
- 检索：`rewritten_queries`、`retrieved_chunks`
- Agent：`plan`、`tool_results`、`pending_action`、`confirm_action_id`、`idempotency_key`
- 产出：`final_answer`、`citations`、`refused`、`error`
- 控制与观测：`step_count`、`token_usage`、`latency`、`extra`

**不用** `Annotated[list, add]` 给 messages 做无限 append。长会话会把 128k 预算打爆，且难以断言。压缩在 `compact_memory` **显式**做。

节点名不能和 key 同名：LangGraph 的 `stream_mode="updates"` 以节点名为键返回 partial state。若节点叫 `intent`，更新通道和字段同名，reducer 会把更新写乱。所以是 `classify_intent` 写 `{"intent": ...}`，`plan_tasks` 写 `{"plan": ...}`。

图内部用 TypedDict 减少每跳校验；HTTP / Tool 边界仍用 Pydantic（`ChatRequest`、`PlanStep`、各工具 `input_model`）。

---

### 1.4 哪些请求走检索、哪些走规划器、哪些直接生成或拒答？复杂度怎么路由？

**开口：** 问候 Direct、越权 Refuse、政策 Single/Multi、查单退款 Agent。意图之后还有一层 AdaptiveRouter，LLM 优先，挂了走规则。

**详细答案：**

`RetrievalStrategy` 五值（`app/core/enums.py`）：

| strategy | 典型意图                             | 做什么                      |
| -------- | ------------------------------------ | --------------------------- |
| `DIRECT` | `greeting`、`chitchat`               | 参数化回答，不检索          |
| `REFUSE` | `out_of_scope`                       | 固定拒答                    |
| `SINGLE` | 多数 `faq_policy`                    | 改写 → Hybrid → 精排 → 生成 |
| `MULTI`  | 多跳政策（「同时 / 如果已经过了」）  | Self-RAG 再跳               |
| `AGENT`  | 订单、物流、退款、退换、取消、转人工 | Planner + 工具              |

路由在 `route_complexity`：`AdaptiveRouter.route(query, intent)`。实现 `app/retrieval/adaptive.py`：

- LLM 输出 `ComplexityResult`（`complexity` + `strategy`），`temperature=0` + JSON；
- LLM 挂了走 `rule_based_complexity`：越权 → REFUSE；问候闲聊 → DIRECT；订单号 / 退款等 tool cue → AGENT；「同时 / 并且 / 如果」等 → MULTI；默认 SINGLE。

意图 **不等于** 策略。例如 `faq_policy` 多数走 SINGLE，但「7 天无理由和运费谁出，如果已经拆封了呢」会因多跳 cue 走 MULTI。`human_handoff` 走 AGENT，因为要调 `escalate_to_human`。

**为什么问候不检索：** 浪费延迟和钱，还把无关 chunk 塞进生成，增大幻觉空间。

---

### 1.5 图是每次请求编译还是启动时编译一次？DB session 为什么不能塞进 state？

**开口：** 进程启动编一次，请求只 `astream`。Session 用 contextvars，不进 state——state 要可序列化、可测，节点签名也没有 db 参数。

**详细答案：**

`ChatService.__init__` 调 `build_graph(...)`，返回 `graph.compile()`。容器是进程级单例，所以 **每个 worker 启动编一次**，不是每个 HTTP 请求编一次。请求里跑 `self._graph.astream(state, stream_mode="updates")`。

DB 不能进 `AgentState` 的原因：

1. LangGraph 节点签名是 `state -> partial state`，没有「传入 db」的位置。
2. SQLAlchemy session 不可序列化；以后若 checkpoint 会直接炸。
3. 单测节点时会被真实连接绑死。

做法：`ChatService` 在请求里 `async with request_session(...)`，把 session 塞进 contextvars（`app/core/request_scope.py`）。工具 `get_db_session()` 懒取当前请求连接。结束 commit，异常 rollback。

图里 **不持有连接**。Registry 是进程级；工具对象无 session。

---

### 1.6 步数上限怎么设？模型说「继续」时怎么硬停？

**开口：** `MAX_AGENT_STEPS=8`、`MAX_TOOL_CALLS=6`，执行器循环里硬 `break`，不靠模型说「我停了」。

**详细答案：**

`app/config/settings.py`：`max_agent_steps=8`，`max_tool_calls=6`。Planner prompt 另有「最多 6 步」，`_sanitize_plan` 再截断 `steps[:6]`。

执行器（`executor_node`）每调一次工具 `calls += 1`，并写回 `step_count`。循环头：

```python
if calls >= settings.max_tool_calls or (state.get("step_count") or 0) >= settings.max_agent_steps:
    break
```

这是 **硬停止条件**。模型在 rationale 里写「请继续」也不会再进下一轮规划——本仓库 **没有** 规划-执行闭环。Agent 叉是一次计划、顺序执行、生成，然后出图。

---

### 1.7 单测怎么只跑某一个节点（例如只测 planner）？

**开口：** 节点是普通 async 函数，传入 Fake LLM 和假 state dict 即可；不必 compile 整张图。

**详细答案：**

节点签名类似 `async def planner_node(state: AgentState, planner: Planner) -> dict`。单测构造最小 state（`user_query`、`intent`、`summary`），注入 `Planner(FakeLLM, registry)`，断言返回的 `plan` / `pending_action`。

相关测试：

- `tests/unit/test_executor_fallback.py`：只跑执行层 Fallback
- `tests/unit/test_intent_overlay.py`：覆盖层
- `tests/unit/test_adaptive_router.py`：复杂度规则
- `tests/unit/test_retry.py`：退避，不打网

pytest 在 `conftest.py` 清空真实 API key，CI **不打真实 LLM**。整图路径用 `tests/e2e/` + Fake，或离线 `eval.runner --task e2e --llm`。

**条件边的价值：** 把「能不能单测一个节点」从架构上保住，而不是测一个 400 行 god function。

---

### 1.8 追问：这是全程自主 Agent 吗？写操作会不会在图里直接执行？

**开口：** 不是全程 Agent。写 / 破坏性工具必须 HITL；未确认时执行器返回空结果，只把确认文案给用户。

**详细答案：**

- 问候、闲聊：Direct，无工具。
- 政策：检索 + 生成，无副作用。
- 查单、物流：Agent 但工具是 `read`，可直接跑。
- `create_refund_request` / `create_return_request` / `cancel_order`：`write` 或 `destructive`。Planner 发现计划里有这类工具且 state 没有 `confirm_action_id`，立刻生成 `ActionProposal`（`act_` 前缀），**本轮不执行写**。执行器见 `pending_action` 且未确认，直接 `tool_results=[]`。生成节点看到 pending 就返回「即将执行 xxx，需要你确认」，不调 LLM。

前端再带 `confirm_action_id` 进来，执行器才 `assert_permitted(..., confirmed=True)` 并走幂等。

**别吹：** 「LLM 自主决策调用工具」不等于「模型说退就退」。自主的是 **规划**，执行写操作仍要人点头。

---

## 2. 规划器与执行器

### 2.1 Planner 和 Executor 各自输入输出是什么？一次规划还是逐步再规划？

**开口：** 一次规划。Planner 吃 query + 意图 + 摘要，吐 `AgentPlan`（≤6 步）和可能的 `pending_action`；Executor 按步调 `Tool.run`，吐 `tool_results`。观察不回流改计划。

**详细答案：**

**Planner 输入：** `user_query`、`intent.label`、会话 `summary`。内部还 `match_skill` 收缩工具目录。

**Planner 输出：** `{"plan": AgentPlan, "pending_action": ActionProposal | None}`。`AgentPlan` 含 `rationale` 和 `steps`（`step_id`、`goal`、`tool_name`、`arguments`、`needs_retrieval`）。

**Executor 输入：** `plan`、`pending_action`、`confirm_action_id`、`idempotency_key`、身份字段。

**Executor 输出：** `{"tool_results": [...], "step_count": n, "latency.tool_ms": ...}`。

这是 **Plan-and-Execute**，不是逐步 ReAct。图上边是死的：`plan_tasks → execute_tools → generate_answer`，没有「执行后再回规划器」的边。工具 output 只进 `tool_results`，给生成节点当证据。

---

### 2.2 和标准 ReAct 差在哪？为什么客服场景不选逐步 ReAct？

**开口：** ReAct 每步 Thought→Action→Observation，适合探索；退款要可审计步骤和权限，所以一次 JSON 计划。读失败换工具是规则表，不是模型再 Thought 一轮。

**详细答案：**

|          | 标准 ReAct                | 本仓库 Agent 叉                    |
| -------- | ------------------------- | ---------------------------------- |
| 循环     | 每步让模型选下一个 Action | 一次计划，顺序执行                 |
| 停止     | 常靠模型输出 Finish       | 计数硬 break                       |
| 工具选择 | 每步全量或接近全量目录    | Skill 收缩后再规划                 |
| 失败后   | 模型看 Observation 再想   | 读工具按 `READ_FALLBACKS` 换下一个 |
| 写操作   | 容易在某一步直接 call     | HITL 拦住，未确认不执行            |

客服写操作要满足：步骤可测、权限可审、超时重试不退两次。逐步 ReAct 的失败模式是模型在 Observation 后「改主意」去调另一个写工具，HITL 和幂等都难套。

和 ReAct 最像的一点是 **执行层 Fallback**：`get_order` 失败 → `search_knowledge`。这是写死的规则，成功则 output 带 `fallback_from`，不是 LLM 再规划。

**别吹：** 不要说本仓库是标准 ReAct。

---

### 2.3 子任务怎么分解？计划最长几步？非法工具名怎么处理？

**开口：** LLM 按 Planner prompt 出 JSON 步骤；Skill 给推荐顺序。`_sanitize_plan` 丢掉不在白名单的工具名，截断到 6 步。

**详细答案：**

分解发生在 `Planner.create_plan`（`app/agents/nodes/planner.py`）：

1. `match_skill(query, intent)`：先扫 Skill JSON 的 `triggers`（如「退货」「7天无理由」），再按意图映射（`refund`/`return_exchange` → `return_handling`）。
2. 命中则 `_allowed_tools` = Skill 的 `tools` ∪ `{search_knowledge, escalate_to_human}`。Prompt 里 **只展示这些**。
3. DeepSeek `temperature=0`，`response_format=json_object`，`max_tokens=512`。
4. `parse_model(..., AgentPlan)` 后 `_sanitize_plan`：工具名必须在 `registry ∩ allowed`，否则丢掉该步；`steps = steps[:6]`。

Planner prompt（`app/prompts/planner.py`）约束：最多 6 步、优先 Skill 顺序、write/destructive 单独一步且默认只规划不执行、不编造订单号、政策步 `needs_retrieval=true`。

非法 / 幻觉工具名（例如编一个 `delete_user`）：sanitize 直接丢步。若丢完 steps 为空，走下一问的 Fallback，不会拿幻觉名字去 `registry.get` 炸执行器。

---

### 2.4 规划失败、JSON 解析失败、工具不在白名单时怎么办？

**开口：** 三层分解 Fallback：LLM 计划 → Skill JSON 落成步骤（从 query 抽 `ORD\d+`）→ 只调 `search_knowledge`。空转比乱调写工具更安全。

**详细答案：**

`create_plan` 的 try/except：

```text
LLM JSON 成功且 sanitize 后仍有 steps → 用它（rationale 前缀 skill:xxx）
LLM 挂 / 解析失败 / steps 空
    → 有 Skill：skill_to_plan（按 Skill.tools 顺序，参数从 query 抽 ORD）
    → 否则 _knowledge_fallback：单步 search_knowledge
    → 连知识工具都没有：空计划 rationale=empty
```

`skill_to_plan` 不会发明工具：名字必须已在 registry。订单类参数用 `_ORDER_RE = ORD\d+`；搜不到就给 `{}`，执行时由工具的 `input_model` 校验失败，再走读 Fallback 或变成 error 结果，而不是编一个假订单号。

这是简历里可以说的 **分解层 Fallback**，和执行层 `READ_FALLBACKS` 是两层。

---

### 2.5 读工具失败会不会换工具？写工具会不会走同一套 Fallback？

**开口：** 读可以换；写和权限拒绝 **绝不** 换。否则未确认退款可能被「换工具」偷偷跑掉。

**详细答案：**

`READ_FALLBACKS`（`app/agents/nodes/executor.py`）例如：

- `get_order` → `search_knowledge`
- `track_shipment` → `get_order` → `search_knowledge`
- `recommend_products` → `search_products` → `search_knowledge`

`execute_with_fallback`：主工具 `success=false` 或抛 `AppError` 时，按表依次试。成功则 output 合并 `fallback_from`、`fallback_error`，metrics 记 `status=fallback`。

**显式不走表：**

- `ToolPermissionError`：**re-raise**，不 Fallback。
- 写 / 破坏性工具走另一条分支（权限 + 幂等），根本不进 `execute_with_fallback`。

单测：`tests/unit/test_executor_fallback.py`。

---

### 2.6 HITL：什么操作要人确认？确认前执行器做什么？超时重试会不会退两次？

**开口：** `write`/`destructive` 要确认。未确认执行器空跑。同一 `action_id` 或幂等键 + 参数指纹命中则返回上次结果，`status=idempotent`。

**详细答案：**

风险枚举：`read` / `write` / `destructive` / `external`。`WRITE_RISKS = {WRITE, DESTRUCTIVE}`。`assert_permitted`：这类工具且 `confirmed=False` → `ToolPermissionError`。

时序：

1. Planner 扫 steps，遇到写工具且没有 `confirm_action_id` → 生成 `ActionProposal`，**break**（只提案第一个写操作）。
2. Executor：`if pending_action and not confirm_action_id: return {tool_results: []}`。
3. Generate：有 pending 则直接把 `summary`（「即将执行 xxx，需要你确认」）当答案，不调 LLM。
4. Faithfulness：pending 时跳过。
5. 客户端下一轮带 `confirm_action_id`。

幂等：写工具用 `confirmed_action_id or idempotency_key` 当键，指纹 `sha256(json({tool, arguments}))`。

- 键 + 指纹命中 → 返回首次 `output`，不重做，metrics `idempotent`。
- 键相同、指纹不同 → `IDEMPOTENCY_CONFLICT`（用户改了参数却复用确认 id）。

**超时退两次** 的防护：LLM 超时重试只包在 `generate()` 上，且规划阶段本来就不执行写；真正写发生在确认后的 `tool.run`。若确认请求超时重试，幂等表挡住第二次副作用。

**别吹：** 幂等依赖客户端带上同一个 key；没带 key 的两次确认仍可能跑两次。面试主动说这个限制。

---

### 2.7 Skill 按需加载是什么？15 个工具全塞进 prompt 会怎样？

**开口：** 三个 JSON Skill，命中后规划器只看见该流程的工具 + 知识检索 + 转人工。全量目录会让模型在退货场景里乱调 `cancel_order`。

**详细答案：**

`app/skills/definitions/`：`return_handling`、`order_tracking`、`product_recommend`。`match_skill` 先 trigger 短语，再 `INTENT_TO_SKILL`。

例如退货 Skill 只暴露：`get_order`、`get_order_items`、`search_knowledge`、`create_return_request`，外加永远可调用的 `escalate_to_human`。

15 个业务工具全塞进 Planner prompt 的失败模式：目录越长，模型越容易选「看起来相关」的写工具（退货场景取消订单、查券时申请退款）。按需加载 = 更短目录、更稳的步骤顺序。**不是**「LLM 失败才读 JSON」；Skill 在规划 **前** 就收缩目录，失败时才把 JSON **落成**步骤。

---

### 2.8 追问：观察结果会不会回流给 Planner 改计划？漏检 / 错工具怎么兜底？

**开口：** 不会回流。兜底靠三层：sanitize 白名单、读失败换工具、生成后忠实度；写错了有 HITL 挡着。

**详细答案：**

图上没有 `execute_tools → plan_tasks` 的边。漏检（该查订单却只搜了知识）时：生成节点仍可能根据知识回答，忠实度检查的是「有没有胡编」，不是「工具选得对不对」。

错工具但只读：用户看到次优答案，可再问；metrics 里 `fallback` 能观测。错到写工具：没有确认就执行不了。

这是刻意取舍：客服延迟吃不下「失败再规划一轮」。若面试被追「那规划错了怎么办」，答：Skill 模板降低错规划率；读 Fallback 保可用性；写必须 HITL；线上用 `intent`/`strategy`/工具 status 监控，而不是每步 Reflexion。

---

## 3. 统一接入核心工具

### 3.1 「统一接入」具体指什么？

**开口：** 本地 15 个工具和 MCP 代理都继承同一套 `Tool`：同一 Schema、同一 `run`（校验 → execute）、同一风险等级、同一 Registry，Planner/Executor **不区分**来源。

**详细答案：**

统一发生在四层，不是「一个 if 调所有 API」：

1. **接口：** `Tool.run` → `input_model` 校验 → `execute`。非法参数变 `InvalidRequestError`，执行异常变 `ToolExecutionError`。
2. **Schema：** `openai_schema()` 都是 `type=function`，给 Planner 当目录、给 MCP 当同一套 Function Calling。
3. **注册：** `build_tool_registry` 注册 15 个业务工具；`MCP_ENABLED` 时 `merge_mcp_tools` 再挂 `MCPToolProxy`。
4. **权限与执行：** Executor 只认 `registry.get(name)` 和 `tool.risk`，不管本地还是远程。

MCP（`app/mcp/adapter.py`）：`MCPToolProxy` 继承 `Tool`，`execute` 调 `call_mcp_tool`（local runtime 或 HTTP POST JSON）。本地 MCP 示例：营业时间、截单时间；读失败仍可走 `READ_FALLBACKS` 里的 `mcp_* → search_knowledge`。

---

### 3.2 工具怎么注册、怎么鉴权（读 / 写 / 破坏性）？

**开口：** 进程级 Registry 按 name 注册。读默认可跑；写和破坏性必须 `confirm_action_id`；转人工是 `external`。

**详细答案：**

15 个业务工具（启用 MCP 后还会多本地 MCP 工具）：

| 风险        | 工具                                                                  |
| ----------- | --------------------------------------------------------------------- |
| read        | 查单、明细、物流、退款状态、搜商品、SKU、推荐、券、库存、保修、搜知识 |
| write       | `create_return_request`                                               |
| destructive | `create_refund_request`、`cancel_order`                               |
| external    | `escalate_to_human`                                                   |

鉴权不是「用户角色 RBAC」，是 **风险 × 确认**：`assert_permitted(tool, confirmed=...)`。订单可见性另在仓储：`OrderRepository.get_visible_order` 按 `user_id` 隔离，无多租户。

Registry 进程级、启动注册一次。工具拿 DB 用 contextvars，见 3.3。

---

### 3.3 工具怎么拿到 DB？为什么用 contextvars 而不是把连接编进图？

**开口：** `get_db_session()` 从请求级 contextvars 取。图要可编译、可测、可序列化，不能持有 session。

**详细答案：**

见 1.5。补充：async 下 thread-local 不安全，contextvars 随 task 传播。`ChatService.stream` 里 graph 跑在 `asyncio.create_task`，仍在同一请求的 context 里，工具能取到同一个 session。不要把 session 塞进 `extra` 或闭包进 node（`partial` 只绑 retriever/llm/registry 等进程级依赖）。

---

### 3.4 幂等键怎么算？`ok | denied | error | idempotent | fallback` 各在什么时候出现？

**开口：** 指纹是 `sha256(tool+args)`；键是确认 id 或客户端幂等键。五个 status 对应成功、未确认、异常、命中缓存、读失败换工具。

**详细答案：**

Prometheus `TOOL_CALLS` 标签 `status`：

| status       | 何时                                                            |
| ------------ | --------------------------------------------------------------- |
| `ok`         | `tool.run` 成功（写路径首次执行，或读路径含 Fallback 前的成功） |
| `fallback`   | 主读工具失败，表内下一个成功                                    |
| `idempotent` | 写工具指纹命中，返回上次 output                                 |
| `denied`     | `ToolPermissionError`（未确认写）                               |
| `error`      | 其他 `AppError`                                                 |
| `conflict`   | `IDEMPOTENCY_CONFLICT`（同键不同指纹）                          |

读路径成功走 Fallback 时，metrics 记在 **fallback 工具名** 上、`status=fallback`，主工具不一定再记一次 ok。面试说「用 status 区分是权限问题还是下游挂了」即可。

---

### 3.5 MCP 工具和本地工具失败语义是否一致？

**开口：** 对 Planner/Executor 一致：都是 `ToolResult`。远程 MCP 多一层传输失败，映射成 `ToolExecutionError`，读工具仍可 Fallback。

**详细答案：**

本地工具：仓储异常 → `ToolExecutionError`。MCP：HTTP/runtime 失败同样进 `execute` 的异常路径。Executor 不 if `mcp_`。差别在运维：远程超时要单独看 endpoint；本地 MCP runtime 在进程内。`docs/12-limitations.md`：订单/物流是种子数据，无真实承运商——MCP 演示的是 **接入模型**，不是已经对接全部外部系统。

---

### 3.6 追问：LLM 编了一个不存在的工具名，系统行为是什么？

**开口：** sanitize 丢掉；不会 `registry.get` 抛 KeyError 把整张图打挂。

**详细答案：**

`_sanitize_plan` 过滤 `step.tool_name in names`。幻觉名字从计划中消失。若因此 steps 空，走 Skill 模板或 `search_knowledge`。执行器对 `tool_name` 为空的 step `continue`。这是白名单，不是「模型想调就调」。

---

## 4. 流式输出

### 4.1 流的是 token 还是节点进度？前端怎么展示「正在规划 / 正在调工具」？

**开口：** 两种都有。SSE：`started` → 多个 `node` → 生成阶段 `token` → 最终 `answer` → `done`。前端用 `node` 名推进度，用 `token` 打字。

**详细答案：**

端点 `POST /api/v1/chat/stream`（`POST /chat` 忽略 `stream` 字段）。`ChatService.stream`：

1. yield `started`（带 `trace_id`）。
2. `set_token_sink` 把 contextvar 指到一个 `asyncio.Queue`。
3. 独立 task 里 `graph.astream(..., stream_mode="updates")`：每个节点完成 yield `{"event":"node","node": "classify_intent", ...}`；若 payload 有 intent/strategy 一并带上。
4. `generate_node` 若存在 sink，调 `llm.stream`，每个 delta `queue.put({event:token, text})`。
5. 图结束后 yield `answer`（完整 `ChatResponse`）和 `done`。

token 与 node 通过同一 Queue 交错，所以用户能在「规划完成」之后看到打字，而不是等整图结束。

节点名可直接做进度文案：`classify_intent` → 正在识别意图；`plan_tasks` → 正在规划；`execute_tools` → 正在查询；`generate_answer` → 正在作答。

---

### 4.2 流式中途 LLM 断了会不会重试？为什么？

**开口：** **不会。** `generate()` 包了指数退避；`stream()` 没有。已经把半截 token 推给用户，重试会重复或错位。

**详细答案：**

`DeepSeekProvider.generate` 把 `_call` 包在 `with_exponential_backoff` 里。`stream` 是 `httpx` 流式 POST，状态码错误或超时直接抛 `LLMProviderError`，**没有** attempt 循环。

原因：SSE 已向客户端推过 `token` 事件。若重试整段 completion，用户会看到两段重叠文字；若从断点续，供应商 API 也不提供 token 级 resume。

生成节点在非流式失败时有抽取式回退；流式路径若中途抛错，由 `ChatService.stream` 的 `holder["error"]` 走错误事件，而不是默默再打一次 DeepSeek。

**面试加一句：** 意图 / 规划 / 忠实度走的是 `generate()`，那些 **可以** 重试，因为还没给用户打字。只有最终答案的 stream 不中途重试。

---

### 4.3 护栏拒答、HITL 待确认、工具错误，在流里分别是什么事件？

**开口：** 拒答仍可能有 `node`，最终 `answer.refused=true`；HITL 的 `answer` 带 `pending_action`、通常无 token；工具错误在 `tool_results` 里，生成仍会出一段解释。

**详细答案：**

| 情况                       | 流里看到什么                                                                                                                        |
| -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| 注入护栏                   | 可能很快 `answer`，`refused=true`，`error_code` 为护栏码；不一定经过 generate，故 **没有 token**                                    |
| 复杂度 REFUSE              | `node: refuse_answer`，固定话术，无 LLM token                                                                                       |
| HITL 待确认                | `node: plan_tasks`（含 pending）、`execute_tools`（空结果）、`generate_answer` **不调 LLM**，`answer.pending_action` 有 `action_id` |
| 读工具失败但 Fallback 成功 | `execute_tools` 的结果带 `fallback_from`，随后正常 token                                                                            |
| 写未确认                   | 不会出现写成功的 tool 输出；见 HITL                                                                                                 |
| 系统故障（LLM 超时等）     | HTTP 层 503 + `LLM_TIMEOUT`；已开始的 SSE 则以错误/中断结束，不编造成功答案                                                         |

业务拒答可以 **HTTP 200** + `refused=true`；系统故障走 4xx/5xx。不要把「拒答」说成 403。

---

### 4.4 忠实度检查发生在流结束前还是后？自纠错会不会撤回已推送的内容？

**开口：** 检查在 `generate_answer` **之后**。token 可能已经推过一版 JSON/正文；纠错只改 `final_answer`，**不会**删除已推 token。以最后的 `answer` 事件为准。

**详细答案：**

边：`generate_answer → check_faithfulness → compact_memory`。

`generate_node` 流式时边收边 `sink(token)`。当前实现 `response_format=json_object`，所以用户看到的增量可能是 `{"answer":"..."}` 的碎片，而不是纯散文——这是可以主动承认的产品瑕疵。

`faithfulness_node`：拒答或 pending 则跳过。否则裁判 `supported`。失败则 `self_correct_answer`：LLM 按证据重写 **一次**，再 check；仍不行就 `_extractive_fallback` 从 chunk 抽句子。`HALLUCINATION_FLAGS` +1。

自纠错 **没有** token 回放协议，前端必须：进度用 `node`，打字用 `token`（可当预览），**最终展示以** `answer` **为准**。若被问「用户会不会先看到幻觉再看到修正」：会，这是流式 + 后置校验的固有窗口；要消灭窗口只能生成后再开始推 token，牺牲首字延迟。

---

### 4.5 追问：第一个 token 的 P50/P95？流式和超时预算怎么拆？

**开口：** 仓库 **没有** 单独的 TTFB/首 token 分位。E2E 16 条整请求 P50 **4.9s** / P95 **5.8s**（n=16，最慢 e02 11.1s）。LLM 读超时默认 30s，connect 3s。

**详细答案：**

`httpx.Timeout(connect=3.0, read=LLM_TIMEOUT_SECONDS, write=10.0, pool=5.0)`，`llm_timeout_seconds` 默认 30。禁止默认无限读。

超时拆分的意义：卡在 TCP 握手不要占用 30s 读预算。Qdrant 另有 5s。sync 调用包 `asyncio.to_thread`。

流式路径下，首 token 延迟 ≈ 护栏 + 意图 + 路由 +（检索或规划执行）+ DeepSeek 开始吐 delta。Agent 叉会更慢，因为规划本身是一次非流式 `generate()`。

**别吹：** 不要把 4.9s 说成首 token。那是 16 条 E2E 全链路墙钟时间，样本很小，分位不稳定。

---

## 5. 指数退避 + 抖动重试

### 5.1 公式是什么？Full jitter 和 Equal / Decorrelated jitter 差在哪？

**开口：** Full jitter：`sleep = random(0, min(cap, base * 2^attempt))`。本仓库就是这个。Equal jitter 是在 `base*2^n` 附近抖；Decorrelated 用上次 sleep 做随机。

**详细答案：**

代码 `app/core/retry.py`：

```python
def _full_jitter_delay(attempt: int, base: float, cap: float) -> float:
    ceiling = min(cap, base * (2**attempt))
    return random.uniform(0.0, ceiling)
```

默认 `base=0.5s`，`cap=8s`，`max_attempts=3`（LLM 次数来自 `settings.llm_max_retries`）。

AWS 架构博客常见三种：

| 算法                      | 等待                                             |
| ------------------------- | ------------------------------------------------ |
| 无抖动指数                | `base * 2^attempt`，多实例对齐 → retry storm     |
| Equal jitter              | `exp/2 + random(0, exp/2)`，仍集中在指数曲线附近 |
| **Full jitter（本仓库）** | `random(0, exp)`，分散最开                       |
| Decorrelated              | `random(0, min(cap, 3*last))`，本仓库未用        |

面试画一条：attempt=0 ceiling=0.5；attempt=1 ceiling=1.0；attempt=2 ceiling=2.0；再被 cap=8 截住。三次尝试总等待最坏约 0.5+1+2=3.5s **之外**还要加三次请求本身的超时，所以 cap 必须远小于产品总超时。

---

### 5.2 为什么必须加 jitter？

**开口：** 多 replica 同一时刻失败，若睡相同的 1s/2s/4s，会一起醒来把下游再打挂，形成 retry storm。jitter 把唤醒打散。

**详细答案：**

客服多 worker、DeepSeek 429/503 往往相关（供应商过载）。无抖动时，所有进程的 attempt 时钟对齐。Full jitter 让期望负载从「尖峰」变成「在 [0, ceiling] 上均匀」。这是分布式系统常识，不是 LLM 特有；面试能接到「限流 + 重试」连环题。

---

### 5.3 哪些错误重试？哪些绝不重试？

**开口：** 重试瞬时：超时、连接错误、408/429/500/502/503/504。绝不重试 400/401/403/404/422。

**详细答案：**

```python
RETRYABLE_HTTP_STATUS = frozenset({408, 429, 500, 502, 503, 504})
NON_RETRYABLE_HTTP_STATUS = frozenset({400, 401, 403, 404, 422})
```

`DeepSeekProvider`：400 一类构造 `LLMProviderError(..., retryable=False)`；429 带 `rate_limited=True`（可重试）；超时 / 传输错误也可重试。`with_exponential_backoff` 只对 `AppError.retryable` 或 `TimeoutError/ConnectionError/OSError` 睡眠重试。

`500` 在集合里：有的网关把瞬时故障标 500。400 类是请求永远错（坏 JSON、坏密钥、没权限、没资源、校验失败），重试只会放大计费和锁账户风险。

---

### 5.4 401 若重试会怎样？429 的 Retry-After 有没有读？

**开口：** 401 重试 = 用坏密钥连续打账单。Retry-After **没读**，只靠 full jitter；这是可以承认的缺口。

**详细答案：**

401/403 固定 `retryable=False`，第一下就抛给上层，意图节点会降级到规则分类，不会把错误密钥打满 `max_attempts`。

429：当作可重试，但 **代码里没有解析** `Retry-After` **头**（全仓库搜不到）。供应商若要求「等 20 秒」，我们仍可能在 0–0.5s 就重试，触发更严的限流。改进方向：有 Retry-After 则 `sleep = max(jitter, header)`，仍要 cap。

---

### 5.5 重试包在 `generate` 上还是也包在 `stream` 上？Embedding 呢？

**开口：** 只包非流式 `generate` 和 Embedding 调用；stream 不包。

**详细答案：**

- `DeepSeekProvider.generate` → `with_exponential_backoff(..., operation_name="deepseek.generate")`
- `DeepSeekProvider.stream` → 无退避（见 4.2）
- `app/providers/embeddings.py` 的 embed 调用同样包退避（`embeddings.embed`）

规划、意图、复杂度、忠实度、自纠错都走 `generate`，享受重试。最终答案在 `/chat/stream` 下走 `stream`，不享受。非流式 `/chat` 的生成走 `generate`，可以重试。

---

### 5.6 写工具超时重试和 LLM 超时重试，幂等策略是否一样？

**开口：** 不一样。LLM 重试是无副作用的补全；写工具靠 HITL + 指纹幂等，**没有**套同一套 `with_exponential_backoff`。

**详细答案：**

工具 `run` 没有包指数退避。写路径超时若发生在 `tool.run` 之后、响应返回之前，客户端重试同一 `confirm_action_id`，幂等表返回首次结果。若超时发生在 **写入之前**，首次可能没落库，重试会真的写一次——这是「至少一次」语义，面试不要说成 exactly-once。

LLM 超时重试安全，因为 chat completion 无业务副作用（仍耗 token 钱，所以 401 绝不能重试）。

---

### 5.7 cap、base、max_attempts 怎么定？和 LLM 超时怎么配合？

**开口：** 默认 3 次、0.5s base、8s cap；单次读超时 30s。最坏是三次 30s 级请求加上数秒 jitter，所以必须只打瞬时错误。

**详细答案：**

最坏墙钟 ≈ `max_attempts * llm_timeout + sum(ceilings)`。3×30s + 0.5+1+2 已经超过一分钟，产品上不可接受。因此：

- 只重试真瞬时错误；
- connect 超时 3s，避免握手卡住吃满 30s；
- stream 不重试，避免再乘一倍；
- 意图失败秒级降级到规则，而不是把分类请求重试到用户放弃。

这些数字是工程默认值，**不是**网格搜索出来的最优。被问「怎么调」：看 metrics 里 `llm` 延迟和 429 比例，cap 不超过 SLA 的 1/3。

---

### 5.8 追问：限流组件挂了是 fail-open 还是 fail-closed？鉴权呢？

**开口：** 限流 Redis 挂了 **fail-open**（放行）；鉴权 **fail-closed**。限流故障不该把整站客服打挂；没鉴权不能当已登录。

**详细答案：**

`RedisRateLimiter.allow` 任何异常：打日志 `rate_limiter_redis_failed_open`，`return True`。进程内 `InMemoryRateLimiter` 作单机兜底。

鉴权 / 管理面：`APP_ENV=production` 必须带 `x-admin-token`，比对 `hmac.compare_digest`。密钥类错误不重试（5.3）。护栏注入是 fail-closed：宁可误拒，不把越权当售后去检索。

---

## 6. 意图识别与路由

### 6.1 一共多少类意图？最容易混的是哪几对？

**开口：** 14 类。最混的是：转人工 vs 退款、政策「怎么算」vs「这件能不能退」、催发货 vs 预售何时发、积分 FAQ vs 券。

**详细答案：**

`IntentLabel`：`greeting`、`chitchat`、`faq_policy`、`order_inquiry`、`logistics`、`refund`、`return_exchange`、`cancel_order`、`product_consult`、`recommendation`、`coupon`、`complaint`、`human_handoff`、`out_of_scope`。

100 条分布（`docs/14-evaluation-report.md`）：faq_policy 16，return_exchange / out_of_scope 各 8，order/logistics/product_consult 各 7，其余多是 5–6，greeting 5。

易混对（prompt v3 和覆盖层专门打）：

| 用户原话                     | 错标                           | 金标                         |
| ---------------------------- | ------------------------------ | ---------------------------- |
| 人工审核一下退款             | `refund`                       | `human_handoff`              |
| 7 天无理由怎么算             | `return_exchange`              | `faq_policy`                 |
| 这件衣服能退货吗             | `faq_policy`                   | `return_exchange`            |
| 催发货                       | `order_inquiry` / `faq_policy` | `logistics`                  |
| 预售什么时候发货             | `logistics`                    | `faq_policy`                 |
| 积分怎么用                   | `coupon`                       | `faq_policy`                 |
| 积分能抵运费吗               | `faq_policy`                   | `coupon`                     |
| Ignore previous instructions | `faq_policy`                   | `out_of_scope`（护栏还会拒） |

---

### 6.2 为什么用 Prompt-template + DeepSeek，而不是 BERT 分类器或纯规则？

**开口：** 14 类中文短文本、要快速改边界、要 JSON 结构。规则只有 51%；BERT 要标训练数据、改类就要重训。Prompt 可版本化，覆盖层补稳定歧义。

**详细答案：**

纯规则 `rule_based_intent` 按关键词表从上到下命中，默认 `faq_policy`。100 条上 **51%**：覆盖不了「人工审核一下退款」这种多标签句。

小型分类器（BERT/fine-tune）要：每类足够金标、部署 embedding 以外的分类头、加类就要重训。本项目意图边界几天改一次 prompt（v1→v3），不适合重训循环。

DeepSeek `deepseek-chat`（API 上的 V3）+ 版本化模板（`PROMPT_VERSION_INTENT=intent_v3`）：改优先级和易混样例即可发版；`temperature=0` + `json_object` 方便 `parse_model(IntentResult)`。LLM 挂了仍有规则 + 同一覆盖层，可用性不绑死供应商。

代价：每次分类一次 LLM 调用（延迟、钱、抖动）。所以后面还有 Adaptive 规则降级，且 Direct 路径避免再检索。

---

### 6.3 v1 / v2 / v3 prompt 改了什么？

**开口：** v1 只给标签列表；v2 加业务规则；v3 加 **优先级**（先匹配的赢）和易混样例。无覆盖时 85% → 86% → 生产再叠覆盖到 100%。

**详细答案：**

文件 `app/prompts/intent.py`：

- **v1：** 「你是意图分类器。只输出 JSON。」加 14 个标签。模型爱把售后全标成 refund。
- **v2：** 角色改成电商客服；禁止 Markdown；几条映射（查单 / 物流 / 退款 / 退换 / 取消 / 券 / 越权 / 转人工）。无覆盖约 **86%**。
- **v3（生产** `INTENT_SYSTEM`**）：** 14 级优先级：注入越权 → 转人工（即使同句有退款）→ 问候 → 闲聊 → 投诉 → 物流 → 查单 → 取消 → 退款 → 退换 → 政策 → 券 → 推荐 → 商品参数。并列出易混样例（见 6.1）。

评测可 `IntentClassifier(..., apply_overlay=False)` 对比纯 Prompt。简历写迭代时要报 **消融**，不要只报最终 100%。

---

### 6.4 「LLM 自主决策」具体指什么？是只分类，还是连拆任务、调工具一起做？

**开口：** 自主是 **分阶段的**：意图 LLM 只打标签；复杂度 LLM 选策略；**只有 Agent 叉** 的 Planner 才拆子任务、选工具。不是一个大模型一次决定所有事。

**详细答案：**

简历「通过 LLM 自主决策分解子任务并调用工具」容易被听成 ReAct 单环。实际：

1. **意图节点：** 只输出 `IntentResult`（label/confidence/rationale），不调工具。
2. **路由节点：** 输出 `strategy`，决定走不走 Planner。
3. **Planner：** 仅 `strategy=agent` 时运行；在 **收缩后的目录** 里选工具、填 arguments。
4. **Executor：** 按计划调用；写操作还要 HITL。sanitize 和权限是否定「完全自主」。

问候不会进 Planner。政策 SINGLE 不会调 `get_order`。这才是 Adaptive 的意义。

---

### 6.5 LLM 挂了走哪条降级？覆盖层做什么？会不会把 97%「刷」上去？

**开口：** LLM 挂 → 关键词规则 → **同一覆盖层**。覆盖层是高置信短语纠偏，不是按测试 id 写死。准确率数字 **含覆盖层**，面试必须主动说。

**详细答案：**

`IntentClassifier.classify`：先算 `rule_based_intent` 当 fallback；try LLM；`LLMProviderError` / `LLMOutputError` 则对 fallback 走 overlay。成功则对 LLM 结果走 overlay。

覆盖层 `app/agents/nodes/intent_overlay.py`：`high_precision_intent` 只在规则很有把握时返回标签（转人工短语、纯问候正则、越权词、易混政策句等），否则 `None` 不改 LLM。`apply_intent_overlay`：forced 存在且与 LLM 不同才改，rationale 追加 `overlay:xxx`，confidence 至少 0.93。

**会不会刷分：** 覆盖针对 **稳定中文客服歧义**，不是 `if query_id == i070`。但 100 条集和覆盖短语高度同源，存在过拟合风险（见第 7 节）。生产路径测到 **100%**；简历写 ≥97% 是留余量。关掉覆盖后历史 v1/v2 约 85%/86%。

「仅歧义覆盖层」在金标上单独也是 100%——说明这 100 条的易混样本恰好都能被短语规则打中。这是双刃剑：证明覆盖有效，也证明集合还不够「覆盖层打不中的新说法」。

---

### 6.6 意图之后谁决定 DIRECT / SINGLE / MULTI / AGENT / REFUSE？

**开口：** `AdaptiveRouter`，不是意图节点。意图是特征，策略是第二跳。

**详细答案：**

见 1.4。`intent_node` 只写 `intent`；`router_node` 调 `router.route(query, intent)` 写 `complexity`、`strategy`、`query_complexity`。图的条件边 **只看 strategy**。

即使意图是 `faq_policy`，路由器仍可能因多跳句式选 MULTI。即使意图是 `refund`，也是路由器（规则或 LLM）选 AGENT，而不是意图枚举硬编码成五路——硬编码会让「退款政策怎么算」无法走检索。当前规则对 `refund` 等事务意图会标 `TOOL_REQUIRED` → AGENT，政策解释更多靠 LLM 路由器或未命中 tool cue 时的默认 SINGLE。

---

### 6.7 追问三连：人工审核退款 / 7 天怎么算 vs 这件能退 / 注入

**开口：** 转人工优先于退款；「怎么算」是政策，「这件能不能」是退换；注入先被护栏拦，意图也会标 `out_of_scope`。

**详细答案：**

1. **「人工审核一下退款」** → `human_handoff`。v3 优先级第 2 条 + 覆盖层 `_HANDOFF`（含「人工审核」）。不要先去 `create_refund_request`。
2. **「7 天无理由怎么算」** → `faq_policy`（覆盖：「怎么算」）。**「这件衣服能退货吗」** → `return_exchange`。前者 SINGLE 检索政策；后者 AGENT + 退货 Skill。
3. **注入：** `apply_guardrail` 在意图 **之前**，命中则 `refused`，条件边直接 `refuse_answer`，不分类、不检索。即便护栏漏了，意图优先级第 1 条和覆盖层越权词仍标 `out_of_scope`，路由器 REFUSE。检索文档还有 `UNTRUSTED_CONTEXT_BANNER`：召回文本当数据不当指令。

---

## 7. 100 条 / 97% 数字口径

### 7.1 100 条怎么构造的？真实日志还是手写？类别是否均衡？

**开口：** 离线手写金标集 `eval/dataset/intent_100.jsonl`，14 类覆盖客服场景，**不是**线上抽样。faq_policy 偏多（16），greeting 最少（5），不是严格均衡。

**详细答案：**

每条形如 `{"id":"i011","query":"怎么开发票","intent":"faq_policy"}`。用途：分类准确率与 prompt 消融。评测命令：`python -m eval.runner --task intent --llm`。

不均衡是有意的：政策问法最多、问候最少。面试不要说「分层随机抽样自生产日志」——仓库没有这条流水线。这是 **能力集**，用来回归「改 prompt 有没有把转人工打成退款」。

---

### 7.2 金标谁标的？有没有双人标注和分歧处理？

**开口：** 项目内单人金标，**没有**双人标注 κ。这是限制，主动说。

**详细答案：**

`docs/14-evaluation-report.md` 范围外写了「人工标注一致性」未做。金标与 prompt 易混样例同源，存在「出题人即评分人」偏差。补强：双盲标注、争议样本仲裁、时间外推集。在此之前不要把 100% 说成「人类一致性上的 SOTA」。

---

### 7.3 97% 是生产路径还是纯 LLM？关掉覆盖层剩多少？

**开口：** 简历 ≥97% 对应生产路径 **intent_v3 + 覆盖层**，实测 **100%**。无覆盖历史：规则 51%，v1 85%，v2 86%。必须说含覆盖层。

**详细答案：**

| 版本                           | 准确率                  |
| ------------------------------ | ----------------------- |
| 关键词规则                     | 51%                     |
| `intent_v1`（无覆盖，历史）    | 85%                     |
| `intent_v2`（无覆盖，历史）    | 86%                     |
| 仅歧义覆盖层                   | 100%                    |
| `intent_v3` **+ 覆盖（生产）** | **100%**（简历写 ≥97%） |

`accuracy = 命中数 / 100`。生产 `IntentClassifier` 默认 `apply_overlay=True`。评测对比纯 Prompt 时关掉 overlay。

---

### 7.4 消融怎么讲？评测是否 temperature=0、强制 JSON？解析失败算错还是重试？

**开口：** 上表就是消融。分类 `temperature=0` + `json_object`。LLM/解析失败降级规则 + overlay，**按最终标签计**，不是把解析失败直接当错（除非降级也错）。

**详细答案：**

意图调用见 `intent.py`：`temperature=0.0`，`max_tokens=256`，`response_format={"type":"json_object"}`。`parse_model` 能剥 markdown fence。解析失败进 `except`，用规则结果再 overlay。

因此「准确率」是 **系统准确率**（LLM+规则+覆盖），不是「模型每次都 parse 成功的条件准确率」。面试被问「LLM 输出不是 JSON 怎么办」：当瞬时/格式失败，走规则，不把用户卡住。

---

### 7.5 有没有 held-out / 时间外推？改 prompt 会不会过拟合这 100 条？

**开口：** **没有** held-out。v3 样例和覆盖短语与金标高度重叠，过拟合风险真实存在。改 prompt 必须看 `mismatches` 而不是只看 100%。

**详细答案：**

同一 100 条既是开发参照又是报表数字。覆盖层在这 100 条上单独 100%，说明「新说法」（例如「帮我找个真人看看能不能把钱打回来」）可能既不中 overlay 也不中 v3 样例。

工程约束：Prompt 变更跑 `--task intent --llm`，看 JSON 里的 mismatches；不要为了 100% 把 query 原文写进代码。`docs/10-evaluation.md`：覆盖针对稳定歧义，不是按 query id 写死——这是纪律，不是数学保证。

---

### 7.6 准确率是 micro 还是 macro？哪一类最差？错在哪几条？

**开口：** Micro：命中数/100。生产路径 100% 时没有「最差类」。无覆盖的历史误差集中在转人工 vs 退款、政策 vs 退换。

**详细答案：**

没有按类平均的 macro-F1 出现在 MEASURED 里。类别不均衡时 micro 会被 faq_policy 拉高。若以后不是 100%，应同时报每类 recall，避免「总体 97% 但转人工 60%」。

当前生产路径 mismatches 为空，所以不要编「错在 i0xx」。无覆盖 v1/v2 的错，用 6.1 的易混对讲即可。

---

### 7.7 上线后用什么监控意图漂移？

**开口：** 离线集回归 + 线上 `intent` 标签分布、覆盖层触发率、转人工率和用户改口（同一 session 先退款后转人工）。

**详细答案：**

`GET /metrics`：请求量、策略/意图计数、intent/retrieval/llm/tool 分段延迟。可观测：

- 某意图占比突然变（活动期退款暴涨 vs 分类器崩了）；
- `rationale` 含 `overlay:` 的比例（覆盖是否在扛 LLM）；
- 护栏拒答率；
- 工具 `denied`（HITL 没确认却走到写）。

没有单独的「在线意图准确率」——没有线上金标。漂移检测是分布 + 抽样人工质检，不是再报一个 97%。

---

### 7.8 口径陷阱清单（答辩主动说）

1. 100% / ≥97% **含覆盖层**，不是纯 DeepSeek。
2. 金标手写、无双人标注、无 held-out。
3. pytest **不打**真实 LLM；简历数字必须来自 `eval.runner` JSON。
4. 不要把 E2E 关键词 9/11（81.8%）说成 100%。
5. Faithfulness 与生成器同模型，裁判偏乐观。
6. 稠密路是 `bge-small-zh-v1.5`，不是 bge-m3。

---

## 8. 跨模块综合题

### 8.1 画一次「我要退 ORD10001 的钱」

**开口：** 护栏过 → 意图 refund → 策略 AGENT → Skill 缩到售后工具 → 计划含查单+退款 → HITL 提案 → 用户确认后幂等执行 → 生成 → 忠实度。

**详细答案（逐步）：**

1. **HTTP** `ChatService`：限流、开 session、组初始 state（query、user_id、session）。
2. **apply_guardrail**：普通售后，不 refused。
3. **classify_intent：** LLM 可能标 `refund`；若用户说「人工审核退款」则 overlay 成 `human_handoff`（本问按直接退款）。
4. **route_complexity：** 事务意图 → `TOOL_REQUIRED` / `AGENT`。
5. **plan_tasks：** `match_skill` → `return_handling`；目录含 `get_order`、`create_refund_request` 等。LLM 或 Skill 模板抽出 `order_id=ORD10001`。扫到 destructive 工具 → `pending_action`（`act_...`）。
6. **execute_tools：** 一旦存在 `pending_action` 且没有 `confirm_action_id`，**直接返回空** `tool_results`，读工具也不会在本轮跑。确认后的请求才会真正执行计划中的步骤。
7. **generate_answer：** 返回确认文案，无 token 或很少。
8. **check_faithfulness：** pending，跳过。
9. **compact_memory → END**，响应带 `pending_action`。
10. 第二轮 `confirm_action_id`：执行器 `assert_permitted(confirmed=True)`，指纹幂等，真正 `create_refund_request`。
11. 生成结合 `tool_results`；忠实度防止说「已经到账」但工具只是「已受理」。

---

### 8.2 意图错了（refund 标成 return_exchange），后面规划器会怎样？有没有纠偏？

**开口：** 没有专门的「意图纠错节点」。两者都映射到同一 Skill `return_handling`，工具目录相近，伤害被 Skill 收窄；生成仍可能说「退货」而不是「退款」。

**详细答案：**

`INTENT_TO_SKILL` 里 `refund` 和 `return_exchange` 都是 `return_handling`。分错后仍看到退货/退款相关工具。真正伤的是：Planner 可能选 `create_return_request` 而不是 `create_refund_request`。HITL 文案会暴露「即将执行 create_return_request」，用户可拒绝。这是人在回路补分类错误，不是图内自动纠偏。

覆盖层会修 **高置信易混句**；修不了的就靠 Skill 重叠 + HITL。

---

### 8.3 工具调用成功但生成时说「已经退了」，忠实度怎么拦？

**开口：** 生成后裁判对照 chunk 和 `tool_results`。`supported=false` 则重写一次，再不行抽取式回退，避免把「已受理」说成「已到账」。

**详细答案：**

`FaithfulnessChecker` 输出 `supported` / `hallucinated_spans`。证据含工具 JSON。自纠错 prompt 带 critique。65 条同模型裁判：无检索幻觉 20% → RAG 3.1% → RAG+自纠错 **0%**（<4% 口径）。**同模型裁判偏乐观**，主动说。

抽取式回退 `_extractive_fallback`：从证据截一段 + 「请补充订单号」，宁可不流畅，不编状态机。

---

### 8.4 流式已经吐出半句，忠实度失败，用户看到什么？

**开口：** 半句 token 已经在路上；随后 `answer` 是纠错后的全文。前端应以 `answer` 覆盖预览。仓库没有撤回事件。

**详细答案：** 见 4.4。产品上两种诚实方案：等忠实度通过再 stream（首字更慢）；或 UI 把 token 标成「草稿」直到 `done`。当前 API 只保证最后 `answer` 是纠错后的，不保证 token 与 answer 逐字相同。

---

### 8.5 为什么问候不检索、政策走 Hybrid、退款走 Agent？各优化什么？

**开口：** 问候优化延迟和费用；政策优化召回（BM25 抓条款数字，向量抓同义，CE 精排）；退款优化正确性与安全（工具 + HITL），不是相似度。

**详细答案：**

| 路径        | 优化目标                 | 不这么做的代价                                       |
| ----------- | ------------------------ | ---------------------------------------------------- |
| Direct      | 延迟、token、幻觉面      | 「你好」也打向量，P95 被拖死                         |
| Hybrid 政策 | 条款里的「7 天」「运费」 | 纯向量漏关键词；纯 BM25 漏同义                       |
| Agent 退款  | 副作用可控、步骤可测     | similarity_search 不会真退款，但模型会 **假装** 退了 |

Adaptive-RAG 的论文映射在 `adaptive.py` 注释里：simple→DIRECT/REFUSE，single_hop→SINGLE，multi_hop→MULTI，tool→AGENT。

---

### 8.6 如果只能砍一个模块保上线，砍规划器、覆盖层还是重试？

**开口：** 先保 **重试 + HITL/幂等**（可用性与资金安全）；覆盖层可用更严规则顶一阵；规划器可退化成纯 Skill 模板。最不能砍的是写操作确认。

**详细答案：**

- **砍 Planner LLM：** `skill_to_plan` 已存在，Agent 叉仍能跑，只是不会「自主」填复杂 arguments。上线可接受。
- **砍覆盖层：** 纯 v3 历史上约 86% 量级（v2 无覆盖 86%），转人工会漏到退款路径，**危险**，要用规则把 `_HANDOFF` 提前。
- **砍重试：** 429/503 直接 5xx，活动峰值客服不可用。
- **砍 HITL：** 绝对不行。

所以「保上线」排序：HITL/幂等 > 限流与重试 > 意图覆盖/规则 > Planner LLM > 流式打字（可先全量非流式）。

---

## 9. 面试官在验证什么

| 简历用词               | 其实在验证                          | 开口锚点                          |
| ---------------------- | ----------------------------------- | --------------------------------- |
| LangGraph 状态机       | 会不会画条件边、为何可测            | 五路路由 + 节点名 ≠ key           |
| 规划器与执行器         | Plan-and-Execute vs ReAct、停止条件 | 一次 JSON、硬 break、不回流       |
| 统一接入工具           | Schema、风险、MCP 同一 `Tool`       | Registry + `Tool.run`             |
| 流式                   | 事件模型、**stream 不中途重试**     | `node` + `token`，generate 才退避 |
| 指数退避 + 抖动        | 公式、可重试集合、retry storm       | Full jitter；401 不重试           |
| Prompt + DeepSeek 路由 | 分类边界、降级                      | v3 优先级 + 规则 fallback         |
| LLM 拆任务调工具       | 白名单、Skill、HITL                 | sanitize ≤6；写要确认             |
| 100 条 / 97%           | 数据集、消融、是否含规则            | v3+覆盖 100%，**含 overlay**      |

准备三件套：**白板画出图**、**背出重试公式和不可重试状态码**、**解释 97% 口径和覆盖层**。被追问时宁可说限制（无 held-out、流式不重试、同模型裁判偏乐观），不要把仓库没有的能力编出来。

---

返回 [16 · 项目面试地图](../16-interview-bagu-map.md)
