# LangGraph 工作流与状态

本文是第九部分的第一篇正文，它讲清如何用状态机组织流程。全文分为五节：前两节讲图的结构与节点拆分，中间两节讲条件边与状态设计，最后一节给出反例与练习。

---

## 一、为什么用一个图而不是一个大函数

最朴素的实现方式是把整个处理过程写成一个函数：先检查安全，再识别意图，再判断复杂度，再检索或调用工具，再生成答案。

这个函数能跑，但它有三个难以回避的问题。

- **分支混乱。** 五条策略意味着五段不同的处理逻辑，全部塞进一个函数后，条件判断会层层嵌套，很难看清。
- **无法单独测试。** 系统只能测试整个函数，无法只测试其中的路由环节。
- **不可观测。** 一个函数是一个黑盒，系统无法知道当前进行到哪一步。

**LangGraph** 是一个状态机框架，它把这些环节拆成独立的节点，用边把它们连接起来。这样做的好处是**结构清晰、节点可测、进度可观测**。

> 本项目的整个处理流程，就是一张用 LangGraph 编译出来的图。

---

## 二、节点如何拆分

`app/agents/graph.py` 中的 `build_graph` 定义了九个节点，它们按职责拆分：`apply_guardrail` 负责安全检查，`classify_intent` 负责意图识别，`route_complexity` 负责复杂度路由，`retrieve_docs` 负责检索，`plan_tasks` 负责规划。

其余节点依次是 `execute_tools` 负责执行工具，`generate_answer` 负责生成，`refuse_answer` 负责拒答，`check_faithfulness` 负责忠实度检查，`compact_memory` 负责记忆压缩。

这九个节点里有一条必须遵守的命名规则：**节点名不能与状态中的字段名相同**。因此意图节点叫 `classify_intent`，而不是 `intent`，因为状态里已经有一个 `intent` 字段。

> 这条规则来自 LangGraph 的实现约束。读者在阅读代码时如果不理解这一点，会觉得节点命名有些别扭。

`app/agents/graph.py` —— `build_graph` 的节点注册

```python
    graph = StateGraph(AgentState)
    graph.add_node("apply_guardrail", guardrail_node)
    graph.add_node("classify_intent", partial(intent_node, classifier=classifier))
    graph.add_node("route_complexity", partial(router_node, router=adaptive))
    graph.add_node(
        "retrieve_docs",
        partial(
            retrieval_node,
            retriever=retriever,
            reranker=reranker,
            rewriter=rewriter,
            self_rag=self_rag,
            settings=settings,
        ),
    )
    graph.add_node("plan_tasks", partial(planner_node, planner=planner))
    graph.add_node("execute_tools", partial(executor_node, registry=registry, settings=settings))
    graph.add_node("generate_answer", partial(generate_node, llm=llm))
    graph.add_node("refuse_answer", refuse_node)
    graph.add_node("check_faithfulness", partial(faithfulness_node, checker=checker, llm=llm))
    graph.add_node("compact_memory", partial(memory_node, settings=settings, summarizer=summarizer))
```

`build_graph` 先用 `StateGraph(AgentState)` 建图，再逐个调用 `add_node` 注册节点。每个节点都通过 `functools.partial` 把依赖（检索器、规划器、工具注册表等）绑定进节点函数，这样节点本身只需接收状态，依赖在编译期就已固定。节点名（如 `classify_intent`）与状态字段名（`intent`）刻意区分，正是为了避开 LangGraph 的命名约束。

---

## 三、流程如何流动

### 3.1 主流程

流程从 `START` 进入，先经过 `apply_guardrail`。如果安全检查判定请求越界，流程转到 `refuse_answer`；否则流程转到 `classify_intent`，再经过 `route_complexity`。

路由之后，流程按策略分成五条。

| 策略 | 分派路径 |
| --- | --- |
| `DIRECT` | 直接去生成 |
| `REFUSE` | 去拒答 |
| `SINGLE` / `MULTI` | 去检索再生成 |
| `AGENT` | 去规划，再执行工具，再生成 |

所有生成或拒答的出口都汇入 `check_faithfulness` 或 `compact_memory`，最后到 `END`。

### 3.2 条件边

分派由条件边完成。`app/agents/graph.py` 中的 `_route_after_complexity` 读取状态里的策略，用一个映射把它转成下一个节点名。

这段代码只有几行，却承担了整条流程的分派职责。

项目把分派写成一个纯函数，而不是散落在各处，是因为纯函数易于测试：给定一个状态，它必然返回确定的下一个节点。

这里还有一条设计细节：`SINGLE` 与 `MULTI` 共用同一个检索节点 `retrieve_docs`，节点内部再根据策略决定是否走 Self-RAG。

> 这样做避免了为两种检索深度各写一套边与节点，让图保持简洁。

`app/agents/graph.py` —— `build_graph` 的条件边

```python
    def _after_guardrail(state: AgentState) -> str:
        return "refuse_answer" if state.get("refused") else "classify_intent"

    graph.add_edge(START, "apply_guardrail")
    graph.add_conditional_edges(
        "apply_guardrail",
        _after_guardrail,
        {"refuse_answer": "refuse_answer", "classify_intent": "classify_intent"},
    )
    graph.add_edge("classify_intent", "route_complexity")
    graph.add_conditional_edges(
        "route_complexity",
        _route_after_complexity,
        {
            "generate_answer": "generate_answer",
            "refuse_answer": "refuse_answer",
            "retrieve_docs": "retrieve_docs",
            "plan_tasks": "plan_tasks",
        },
    )
```

条件边由 `add_conditional_edges` 注册，它接收三个参数：源节点、判定函数、以及"返回值到目标节点"的映射表。`_after_guardrail` 读取状态的 `refused` 字段决定去向，`_route_after_complexity` 则把路由结果映射到 `retrieve_docs` 或 `plan_tasks` 等节点。两条 `add_edge` 是普通边，分别固定 `START` 到护栏、以及意图节点到复杂度节点。

---

## 四、状态如何设计

### 4.1 状态是什么

`app/agents/state.py` 中的 `AgentState` 是一个 `TypedDict`，它定义了流程中流转的全部数据。

这些字段包括查询、意图、策略、检索切片、计划、工具结果、待确认动作、最终答案、引用、token 用量与延迟分段等。每个节点读取它需要的字段，返回它更新的字段。

`app/agents/state.py` —— `AgentState`

```python
class AgentState(TypedDict, total=False):
    """LangGraph state. Partial updates replace listed keys; no infinite append reducer.

    Messages are compressed explicitly in the memory node instead of Annotated[add]
    so the graph cannot silently blow the 128k budget.
    """

    trace_id: str
    session_id: str
    user_id: str
    user_query: str
    messages: list[ChatMessage]
    summary: str
    intent: IntentResult | None
    complexity: ComplexityResult | None
    strategy: RetrievalStrategy | None
    # ...
    final_answer: str | None
    citations: list[Citation]
    refused: bool
    error: str | None
    step_count: int
    token_usage: TokenUsage
    latency: LatencyBreakdown
    extra: dict[str, Any]
```

`AgentState` 继承自 `TypedDict` 并声明 `total=False`，因此所有键都是可选的，节点只需返回自己更新的那部分。类文档字符串明确写下了设计取舍：消息在记忆节点里被显式压缩，而不是用 `Annotated[add]` 自动追加，以免图在长会话里无声地撑爆 128k 预算。

### 4.2 替换而非追加

`AgentState` 有一个关键特性：它是 `total=False` 的 `TypedDict`，节点返回的字典会**替换**它列出的键，而不是追加。项目**没有**使用 `Annotated[list, add]` 这种自动追加的写法。

这个选择是刻意的。如果系统使用自动追加，那么每一轮对话都会把新消息追加到消息列表，列表会在长会话里无声地膨胀，最终撑爆 128k 的上下文预算。

更麻烦的是，这种膨胀是隐式的，系统难以在某个节点断言"消息列表现在有多长"。

> 把压缩放在显式的 `compact_memory` 节点里，系统就能清楚地知道何时摘要、摘要了什么，也让压缩逻辑变得可测、可观测。

### 4.3 图内部用 TypedDict，边界用 Pydantic

项目在边界处使用 Pydantic 模型，例如请求体 `ChatRequest`、计划步骤 `PlanStep`、各工具的输入模型。

这些边界需要严格校验，因为它们接收的是外部或模型生成的**不可信数据**。而图内部的状态流转使用 `TypedDict`，因为内部数据已经过校验，不需要重复付出校验开销。

> 这种"边界严、内部松"的分工，是性能与安全的折中。

---

## 五、反例与练习

假设系统不用图，而把所有逻辑写进一个大函数。当需要修改某一步时，读者必须在一个几百行的函数里定位对应的分支；当需要测试路由时，读者只能构造完整的输入，跑通整条链路；当线上出现问题时，读者只能看到一个整体的耗时，无法知道是哪一步慢。

> 这个反例说明，图的价值不只在于"能跑"，更在于它让流程可读、可测、可观测。

本部分的练习有两项。

- 第一项是**画流程图**。读者应根据 `build_graph` 的节点与边，画出从入口到出口的完整流程，标出所有条件分支。
- 第二项是**解释设计**。读者应说明为什么本项目不使用自动追加的 reducer，而选择在独立节点里显式压缩。

> **指标回指。** 本篇对应的指标是第 11 部分"评测体系"中的端到端延迟分段。在 16 条用例中，意图分段的中位延迟约 **803 毫秒**，生成分段约 **1084 毫秒**，这些分段正是由图中的节点边界产生的。读者在阅读下一篇时，可以对照理解工具节点内部的约束。

---

**本篇涉及的源码：** `app/agents/graph.py`、`app/agents/state.py`
