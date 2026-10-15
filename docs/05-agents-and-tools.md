# 05 · 智能体、工具与 HITL

> 一句话：意图 LLM + 覆盖层；Skill 按需收缩工具目录；写操作 HITL + 幂等；读失败换工具；MCP 与本地工具同一套 Function Calling。

## 本章目录

1. [节点拆分](#节点拆分)
2. [意图](#意图)
3. [Skill 按需加载](#skill-按需加载)
4. [规划器](#规划器)
5. [执行器与 Fallback](#执行器与-fallback)
6. [15 个业务工具](#15-个业务工具)
7. [HITL 与幂等](#hitl-与幂等)
8. [忠实度自纠错](#忠实度自纠错)
9. [记忆压缩](#记忆压缩)
10. [MCP](#mcp)
11. [Token 流式](#token-流式)

对应：`app/agents/`、`app/tools/`、`app/skills/`、`app/mcp/`、`app/memory/`。

## 节点拆分

意图、路由、检索、规划、执行、生成、忠实度、压缩各一个节点，才能单独 mock、限制步数、SSE 按节点推进度。步数上限：`MAX_AGENT_STEPS=8`，`MAX_TOOL_CALLS=6`。

## 意图

### 要点

生产路径：DeepSeek 输出 JSON → `intent_v3` prompt → **高置信覆盖层**纠偏易混标签。LLM 挂了走关键词规则，再走同一覆盖层。

100 条实测：规则 51% → 无覆盖 v1/v2 约 85%/86% → **v3+覆盖 100%**（≥97%）。

### 代码摘要

```python
# app/agents/nodes/intent.py
async def classify(self, query: str) -> IntentResult:
    fallback = rule_based_intent(query)
    try:
        parsed = parse_model(response.content, IntentResult)
        return self._maybe_overlay(query, parsed)
    except (LLMProviderError, LLMOutputError):
        return self._maybe_overlay(query, fallback)

def _maybe_overlay(self, query, parsed):
    label, overlay_note = apply_intent_overlay(query, parsed.label)
    if overlay_note:
        parsed.label = label
        parsed.rationale = f"{parsed.rationale};{overlay_note}"
    return parsed
```

覆盖层优先处理：注入/越权 → 转人工（压过退款/投诉）→ 政策「怎么算」vs 「这件能不能退」等。实现：`app/agents/nodes/intent_overlay.py`。Prompt：`app/prompts/intent.py`。标签：`IntentLabel`。

评测可关覆盖：`IntentClassifier(..., apply_overlay=False)`，用来对比纯 Prompt。

### 为什么

中文客服里「人工审核一下退款」会被模型标成 `refund`，金标是 `human_handoff`。覆盖层是稳定短语规则，不是按 `i070` 写死。面试要主动说：准确率含覆盖层。

## Skill 按需加载

### 要点

三个 JSON：`return_handling`、`order_tracking`、`product_recommend`。  
先匹配 trigger 短语，再按意图映射。命中后规划器 **只展示该 Skill 的工具** + `search_knowledge` + `escalate_to_human`。

### 代码摘要

```python
# app/skills/loader.py
INTENT_TO_SKILL = {
    "return_exchange": "return_handling",
    "refund": "return_handling",
    "logistics": "order_tracking",
    "order_inquiry": "order_tracking",
    "recommendation": "product_recommend",
    ...
}

def match_skill(query: str, intent_label: str = "") -> dict | None:
    for skill in load_skills():
        if any(trigger in query for trigger in skill.get("triggers", [])):
            return skill
    return skill_by_name(INTENT_TO_SKILL.get(intent_label))
```

```json
# app/skills/definitions/return_handling.json
{
  "name": "return_handling",
  "triggers": ["退货", "换货", "7天无理由"],
  "tools": ["get_order", "get_order_items", "search_knowledge", "create_return_request"]
}
```

### 为什么

15 个工具全塞进 Planner prompt 会让模型乱调 `cancel_order`。按需加载 = 更短目录、更稳的步骤顺序。不是「LLM 失败才读 JSON」。

## 规划器

### 要点

LLM 把问题拆成 ≤6 步；工具名必须在收缩后的目录里。失败则 `skill_to_plan`（从 query 抽 `ORD\d+`），再失败才 `search_knowledge`。

写/破坏性工具若尚未确认：生成 `ActionProposal`，执行器本轮不跑写。

### 代码摘要

```python
# app/agents/nodes/planner.py
async def create_plan(self, query, intent_label, summary):
    skill = match_skill(query, intent_label)
    allowed = _allowed_tools(skill, self._registry)
    try:
        plan = parse_model(response.content, AgentPlan)
        plan = _sanitize_plan(plan, self._registry, allowed)
        if plan.steps:
            return plan
    except (LLMOutputError, LLMProviderError):
        pass
    if skill:
        return skill_to_plan(skill, query, self._registry)
    return _knowledge_fallback(query, self._registry)
```

这是简历里的 **分解层 Fallback**。

## 执行器与 Fallback

### 要点

读工具失败 → 按表换下一个（`get_order` → `search_knowledge`）。  
**权限拒绝、写操作不走这张表**，避免未确认退款被「换工具」偷偷执行。

### 代码摘要

```python
# app/agents/nodes/executor.py
READ_FALLBACKS = {
    "get_order": ["search_knowledge"],
    "track_shipment": ["get_order", "search_knowledge"],
    "mcp_store_hours": ["search_knowledge"],
    ...
}

async def execute_with_fallback(tool, step, context, registry, query):
    try:
        result = await tool.run(step.arguments, context)
        if result.success:
            return result
        raise ToolExecutionError(...)
    except ToolPermissionError:
        raise
    except (AppError, InvalidRequestError) as exc:
        for fallback_name in READ_FALLBACKS.get(tool.name, []):
            fb_result = await registry.get(fallback_name).run(...)
            if fb_result.success:
                return fb_result.model_copy(update={"output": {..., "fallback_from": tool.name}})
        raise
```

工具入口统一 `Tool.run`：先 `input_model` 校验，再 `execute`。这是 **执行层 Fallback**。

单测：`tests/unit/test_executor_fallback.py`。

## 15 个业务工具

| 名称 | 风险 | 作用 |
|---|---|---|
| `get_order` | read | 订单状态 |
| `get_order_items` | read | 明细 |
| `track_shipment` | read | 物流事件 |
| `get_refund_status` | read | 退款单 |
| `create_refund_request` | destructive | 申请退款 |
| `create_return_request` | write | 申请退货 |
| `cancel_order` | destructive | 取消未发货 |
| `search_products` | read | 搜商品 |
| `get_product_detail` | read | SKU |
| `recommend_products` | read | 推荐 |
| `get_coupon` | read | 券规则 |
| `check_inventory` | read | 库存 |
| `get_warranty` | read | 保修 |
| `search_knowledge` | read | 政策检索 |
| `escalate_to_human` | external | 转人工占位 |

Registry 进程级；DB 经 `get_db_session()` 懒解析。工厂：`app/tools/factory.py`。启用 MCP 后还会多 2 个本地 MCP 工具，见下。

## HITL 与幂等

### 要点

`write` / `destructive` 无 `confirm_action_id` → `ToolPermissionError`。  
Planner 先返回 `pending_action`；客户端再带 `confirm_action_id`。  
同一 `action_id`/`idempotency_key` + 参数指纹：第二次返回首次结果。指纹不同 → `IDEMPOTENCY_CONFLICT`。

### 代码摘要

```python
# app/tools/permissions.py
WRITE_RISKS = {ToolRisk.WRITE, ToolRisk.DESTRUCTIVE}

def assert_permitted(tool: Tool, *, confirmed: bool) -> None:
    if tool.risk in WRITE_RISKS and not confirmed:
        raise ToolPermissionError(
            f"{tool.name} is {tool.risk.value} and requires explicit user confirmation"
        )
```

```python
# app/agents/nodes/planner.py  （生成待确认）
if tool.risk in WRITE_RISKS and not state.get("confirm_action_id"):
    pending = ActionProposal(
        action_id=new_id("act_"),
        tool_name=tool.name,
        arguments=step.arguments,
        risk=tool.risk,
        summary=f"即将执行 {tool.name}，需要你确认后才会真正提交。",
    )
```

执行器对写工具：`IdempotencyRepository.get_if_matches(key, sha256(tool+args))`。

### 为什么

LLM 超时重试如果没有幂等，会生成两笔退款。HITL 把「模型想退」和「用户同意退」拆开，面试必问。

## 忠实度自纠错

### 要点

生成后裁判 `supported`。失败：先 LLM 按证据重写一轮，再抽取式回退。65 条上 RAG 幻觉 1.5% → 自纠错后 0%。

### 代码摘要

```python
# app/agents/nodes/faithfulness.py
result = await checker.check(query=..., answer=..., chunks=..., tool_results_text=...)
if result.supported:
    return {"extra": extra}
HALLUCINATION_FLAGS.inc()
patched, judged, corrected = await self_correct_answer(...)  # LLM 重写，失败则 extractive
return {"final_answer": patched, "extra": {"self_corrected": corrected}}
```

## 记忆压缩

预算 `TOKEN_BUDGET=128000`（启发式，约 1.5 汉字/token，**不是**官方 tokenizer）。

| 利用率 | 级别 | 行为 |
|---|---|---|
| &lt;50% | none | 不压 |
| 50%–70% | soft | 工具结果截断到 400 字 |
| 70%–85% | hard | 160 字 + 滑动窗口 |
| &gt;85% | auto-compact | 最近 4 轮 + 摘要 |

### 代码摘要

```python
# app/memory/compression.py
KEEP_RECENT_TURNS = 4
TOOL_SOFT_CHARS, TOOL_HARD_CHARS = 400, 160

def apply_compression(messages, tool_results, summary, settings):
    used = messages_tokens(messages) + estimate_tokens(summary)
    level = decide_level(used, settings)
    tools = compress_tool_results(tool_results, level)
    if level in {HARD_COMPRESS, AUTO_COMPACT}:
        window = sliding_window(messages)  # 最近 4 轮
        ...
```

单测：`tests/unit/test_compression.py`。

## MCP

### 要点

`MCPToolProxy` 继承 `Tool`，Planner/Executor **不区分**本地还是远程。本地 Runtime 真返回营业时间/截单；远程 POST JSON。

### 代码摘要

```python
# app/mcp/adapter.py
class MCPToolProxy(Tool):
    async def execute(self, parsed, context) -> ToolResult:
        output = await call_mcp_tool(
            name=self.name,
            arguments=parsed.payload,
            transport=self._transport,  # "local" | "http"
            endpoint=self._endpoint,
        )
        return ToolResult(name=self.name, success=True, output=output, risk=self.risk)

    def openai_schema(self) -> dict:
        # 与本地工具同一套 type=function
```

启动：`settings.mcp_enabled` 时 `merge_mcp_tools(registry, LOCAL_CATALOG)`。单测：`tests/unit/test_mcp.py`。

## Token 流式

### 要点

`generate_node` 先解析模型返回的结构化 JSON，`check_faithfulness` 可进一步纠正或拒答。`ChatService.stream` 随后只把最终可展示的答案拆成 `token` 事件，避免向用户短暂显示内部 JSON 或未校验的草稿。SSE 事件：`started` → `node` → `token` → `answer` → `done`。生成与校验期间客户端显示等待状态。

### 代码摘要

```python
# app/services/chat_service.py（摘要）
response = self._to_response(merged, session_id=session_id, trace_id=trace_id)
for index in range(0, len(response.answer), 48):
    yield {"event": "token", "text": response.answer[index : index + 48]}
yield {"event": "answer", "data": response.model_dump(mode="json")}
```

Graph 在独立 task 里跑，节点进度通过 `asyncio.Queue` 传给客户端；答案 token 在 Graph 完成后发送（`app/services/chat_service.py`）。

---

上一章 [04](04-adaptive-rag.md) · 下一章 [06 · API](06-api-reference.md)
