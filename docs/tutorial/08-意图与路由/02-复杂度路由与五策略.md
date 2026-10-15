# 复杂度路由与五策略

本文是第八部分的第二篇正文，它讲清意图如何转成处理策略。

全文分为五节，前两节讲五条策略，中间两节讲路由的实现与容错，最后一节给出反例与练习。

---

## 一、从意图到路径

意图识别的产物是"用户想干什么"，它还不是一个可执行的路径。

同样是想查订单，有的问题只读一次系统就够，有的问题需要组合多个工具；同样是政策问答，有的一跳检索就够，有的需要多跳。

> 因此系统还需要一步：把意图与查询特征结合起来，判定复杂度，再选择一条处理策略。

这个环节称为**复杂度路由（Complexity Routing）**。它的产物是一个 `ComplexityResult`，其中同时包含**复杂度**与**策略**两个字段。

`app/core/enums.py` —— 复杂度枚举 `QueryComplexity`。

```python
class QueryComplexity(str, Enum):
    SIMPLE = "simple"
    SINGLE_HOP = "single_hop"
    MULTI_HOP = "multi_hop"
    TOOL_REQUIRED = "tool_required"
    OUT_OF_SCOPE = "out_of_scope"
```

`QueryComplexity` 把复杂度分成五档：`SIMPLE` 表示可直接回答，`SINGLE_HOP` 与 `MULTI_HOP` 分别对应单跳与多跳检索，`TOOL_REQUIRED` 表示必须调用工具，`OUT_OF_SCOPE` 表示越界。

---

## 二、五条策略

本项目定义了五条处理策略，它们覆盖了从最简单到最复杂的全部情况。

| 策略 | 适用场景 | 处理方式 |
| --- | --- | --- |
| `DIRECT` | 可以直接回答的问题，如问候与闲聊 | 不经过检索，直接生成回答，延迟最低 |
| `SINGLE` | 一次检索即可回答的问题，如单条政策问答 | 一次混合检索，`top_k` 取 3，再精排取前若干条 |
| `MULTI` | 需要多跳检索、组合多条依据的问题 | 走 Self-RAG 循环，`top_k` 取 8，最多检索三跳 |
| `AGENT` | 需要调用外部工具的请求，如查订单、查物流、取消订单 | 进入计划与工具执行流程 |
| `REFUSE` | 越界或无法处理的请求，如注入攻击、违法话题 | 明确拒答，而不是勉强生成 |

上一部分讲的"定制商品过了七天还有质量问题"就属于 `MULTI` 这一类。

这五条策略收在一个枚举 `RetrievalStrategy` 里，它的取值是 `DIRECT`、`SINGLE`、`MULTI`、`AGENT`、`REFUSE`。

`app/core/enums.py` —— 策略枚举 `RetrievalStrategy`。

```python
class RetrievalStrategy(str, Enum):
    """Adaptive-RAG routing targets.

    DIRECT: parametric / greeting answers, no retrieval.
    SINGLE: one-shot hybrid retrieval.
    MULTI: Self-RAG iterative retrieval for multi-hop questions.
    AGENT: planner + tools, optionally with retrieval.
    REFUSE: query boundary / policy refusal.
    """

    DIRECT = "direct"
    SINGLE = "single"
    MULTI = "multi"
    AGENT = "agent"
    REFUSE = "refuse"
```

`RetrievalStrategy` 继承 `str` 与 `Enum`，五个取值与上表一一对应。枚举上方的 docstring 逐条说明了每条策略的含义，让路由目标在代码里自解释。

> 把路径收成枚举，而不是散落在各处的字符串判断，是本项目的一个基本设计：只有这样，系统才能单独测试路由、在流式响应里暴露策略、在监控里按策略打点。

---

## 三、路由如何决策

### 3.1 模型优先，规则兜底

`app/retrieval/adaptive.py` 中的 `AdaptiveRouter.route` 采用"模型优先、规则兜底"的结构。

它先让大模型输出一个复杂度判定，如果模型调用失败或输出无法解析，就退回规则 `rule_based_complexity`。

规则本身的判断顺序值得读者留意：

- 它先看越界意图，命中即返回 `REFUSE`；
- 再看问候与闲聊，命中即返回 `DIRECT`；
- 接着看交易类意图与订单号，命中即返回 `AGENT`。

这三步之后，它统计查询中的多跳线索，例如"同时""并且""但是已经""过了"，当线索出现且查询长度超过 **18 个字**时，返回 `MULTI`；其余情况返回 `SINGLE`。

### 3.2 有订单号时 Agent 优先

规则里有一条容易被忽略但很重要的优先级：**当查询里出现订单号时，系统优先走 `AGENT`，而不是 `MULTI`**。

原因在于，有订单号的问题多半是"我的这个单怎么了"，答案在系统数据里，而不在政策文档里。

> 系统应当先去查系统，而不是先去搜政策。这条优先级避免了"明明有确切订单却去翻政策"的错配。

---

## 四、条件边如何分派

路由的产物最终由 LangGraph 的条件边使用。

`app/agents/graph.py` 中的 `_route_after_complexity` 读取状态里的策略，用一个映射把它转成下一个节点名。

`app/agents/graph.py` —— `_route_after_complexity`。

```python
def _route_after_complexity(state: AgentState) -> str:
    strategy = state.get("strategy") or RetrievalStrategy.SINGLE
    mapping = {
        RetrievalStrategy.DIRECT: "generate_answer",
        RetrievalStrategy.REFUSE: "refuse_answer",
        RetrievalStrategy.SINGLE: "retrieve_docs",
        RetrievalStrategy.MULTI: "retrieve_docs",
        RetrievalStrategy.AGENT: "plan_tasks",
    }
    return mapping[strategy]
```

`_route_after_complexity` 先从状态取出 `strategy`，缺省时按 `SINGLE` 处理，再用字典把策略映射成下一个节点名。注意 `SINGLE` 与 `MULTI` 都映射到 `retrieve_docs`，两者共用同一个检索节点。

| 策略 | 下一个节点 |
| --- | --- |
| `DIRECT` | `generate_answer` |
| `REFUSE` | `refuse_answer` |
| `SINGLE` | `retrieve_docs` |
| `MULTI` | `retrieve_docs` |
| `AGENT` | `plan_tasks` |

这里有一个设计细节：`SINGLE` 与 `MULTI` 共用同一个检索节点 `retrieve_docs`，节点内部再根据策略决定是否走 Self-RAG 循环。

> 这样做的好处是避免了两套几乎相同的边与节点，让图更简洁。如果系统为两种检索深度各写一个节点，不仅代码重复，测试也要写两遍。

---

## 五、反例与练习

**反例。** 假设系统去掉复杂度路由，对所有问题都走 `SINGLE`。

问候语"你好"也会经过一次检索，浪费延迟；而"帮我取消订单"只做检索而不调工具，系统会去政策库里找"如何取消订单"，却不去真正执行取消。前者浪费资源，后者答非所问。

> 这个反例说明，路由的价值在于让处理方式与请求的真实需求匹配。

本部分的练习有两项：

- **练习一：判断策略。** 读者应取五句话术，分别判断策略。"你好"走 `DIRECT`，"ORD10001 到哪了"走 `AGENT`，"定制商品过了七天还能退吗"走 `MULTI`，"帮我把这个订单取消"走 `AGENT`，"帮我写作业"走 `REFUSE`。
- **练习二：解释优先级。** 读者应说明为什么有订单号时系统优先走 `AGENT` 而不是 `MULTI`。

> **指标回指。** 本篇对应的指标是第 11 部分"评测体系"中的端到端策略分布与延迟。在 16 条端到端用例中，问候走 `DIRECT` 约 3.1 秒，多跳的 `e02` 约 11.1 秒，注入的 `e10` 因正则拦截仅约 10 毫秒。这组分布直观地展示了路由如何让延迟与问题难度匹配。读者在阅读第 9 部分"工作流与工具"时，可以对照理解这些策略在图中如何被编排。

---

**本篇涉及的源码：** `app/core/enums.py`、`app/retrieval/adaptive.py`、`app/agents/graph.py`
