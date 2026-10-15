# 查询改写与自适应

> 本文是第六部分的第一篇正文，它讲清查询改写与复杂度判定两项技术。

全文分为五节。前两节讲查询改写，中间两节讲复杂度判定，最后一节给出反例与练习。

---

## 一、查询改写解决什么

### 1.1 措辞鸿沟

用户提问用的是口语，知识库用的是规范表述。

用户说"东西不想要了"，文档写"七天无理由退货"；用户说"这个杯子有货没"，文档写"库存状态"。

这道措辞鸿沟会让召回打折扣：即使系统拥有语义召回能力，一个过于口语化、过于省略的查询，仍然可能命中不到最相关的切片。

查询改写要做的，就是在检索之前把用户问题翻译一遍。它把口语补成完整表达，把省略的主语补回来，把口语词换成规范词。

> 改写之后，查询与文档在措辞上更接近，召回也就更容易命中。

### 1.2 拆分为子查询

查询改写还有第二种形式：把一个复合问题拆成若干子查询。

用户问"定制商品过了七天还有质量问题能不能退"，这一句话里其实藏着三个约束：**定制商品**、**已过七天**、**存在质量问题**。

如果系统把它当成一个整体去检索，很可能只命中退货总则，因为总则覆盖了"退货"这个大类。

如果把三个约束分别作为子查询去检索，系统就能分别命中定制商品的例外条款与质量问题的特殊处理，证据因此更完整。

---

## 二、本项目的改写实现

`app/retrieval/query_rewrite.py` 中的 `QueryRewriter.rewrite` 调用大模型生成改写结果。它要求模型输出一个 JSON，其中 `queries` 字段是一个列表。

代码对结果做了两层约束：它先过滤掉空字符串，再截取前三条；如果模型返回为空或者调用失败，它就退回原始查询。

> 也就是说，改写最多产生三条查询，且永远有一个保底结果。

这两层约束体现了一个工程判断：改写是"锦上添花"，不是"必要条件"。系统宁愿用一个未改写的查询继续检索，也不愿意因为改写失败而中断整个流程。

`app/retrieval/query_rewrite.py` —— `QueryRewriter.rewrite`

```python
    async def rewrite(self, query: str, *, missing_aspect: str = "") -> list[str]:
        try:
            response = await self._llm.generate(
                [
                    {"role": "system", "content": REWRITE_SYSTEM},
                    {
                        "role": "user",
                        "content": REWRITE_USER.format(
                            query=query, missing_aspect=missing_aspect or "none"
                        ),
                    },
                ],
                temperature=0.0,
                max_tokens=256,
                response_format={"type": "json_object"},
            )
            payload = extract_json_object(response.content)
            queries = payload.get("queries") or []
            cleaned = [str(item).strip() for item in queries if str(item).strip()]
            return cleaned[:3] or [query]
        except (LLMProviderError, LLMOutputError):
            return [query]
```

`rewrite` 以 `temperature=0.0` 与 `json_object` 格式调用大模型，再把 `queries` 字段逐条 `strip`、丢弃空串，最后截取前三条。它用 `or [query]` 保证结果非空，并在捕获 `LLMProviderError` 与 `LLMOutputError` 时退回原始查询。

---

## 三、复杂度判定与检索深度

### 3.1 两种检索深度

并非所有问题都需要同样深的检索。一句简单的政策问答，检索一次就够了；一个含多个约束的售后问题，可能需要检索多次。

系统因此需要先判断问题的复杂度，再决定检索深度。本项目把检索深度分为两档。

| 档位 | 检索方式 | top_k |
| --- | --- | --- |
| `single` | 一次混合检索 | 3 |
| `multi` | Self-RAG 多跳检索 | 8 |

### 3.2 判定的依据

`app/retrieval/adaptive.py` 中的 `rule_based_complexity` 给出了一套规则。它依次看三个线索。

- **先看意图。** 越界意图走拒答，问候与闲聊走直接回答，订单、物流、退款、取消等交易类意图走工具路径。
- **再看订单号。** 查询里出现 `ORD` 加数字时，系统优先走工具路径。
- **最后看多跳线索。** 查询里出现"同时""并且""但是已经""过了"这类连接词，且长度超过 **18 个字**时，系统判为多跳。

`app/retrieval/adaptive.py` —— `rule_based_complexity`

```python
def rule_based_complexity(query: str, intent: IntentResult) -> ComplexityResult:
    text = query.strip()
    if intent.label == IntentLabel.OUT_OF_SCOPE:
        return ComplexityResult(
            complexity=QueryComplexity.OUT_OF_SCOPE,
            strategy=RetrievalStrategy.REFUSE,
            confidence=0.95,
            rationale="intent_out_of_scope",
        )
    if intent.label in {IntentLabel.GREETING, IntentLabel.CHITCHAT}:
        return ComplexityResult(
            complexity=QueryComplexity.SIMPLE,
            strategy=RetrievalStrategy.DIRECT,
            confidence=0.9,
            rationale="social_or_greeting",
        )
    if (
        intent.label
        in {
            IntentLabel.ORDER_INQUIRY,
            IntentLabel.LOGISTICS,
            IntentLabel.REFUND,
            IntentLabel.RETURN_EXCHANGE,
            IntentLabel.CANCEL_ORDER,
            IntentLabel.HUMAN_HANDOFF,
        }
        or _ORDER_ID.search(text)
        or any(cue in text for cue in _TOOL_CUES)
    ):
        return ComplexityResult(
            complexity=QueryComplexity.TOOL_REQUIRED,
            strategy=RetrievalStrategy.AGENT,
            confidence=0.8,
            rationale="entity_or_transactional_intent",
        )
    hop_cues = sum(1 for cue in _MULTI_HOP_CUES if cue in text)
    if hop_cues >= 1 and len(text) > 18:
        return ComplexityResult(
            complexity=QueryComplexity.MULTI_HOP,
            strategy=RetrievalStrategy.MULTI,
            confidence=0.7,
            rationale="multi_constraint_query",
        )
    return ComplexityResult(
        complexity=QueryComplexity.SINGLE_HOP,
        strategy=RetrievalStrategy.SINGLE,
        confidence=0.75,
        rationale="single_policy_or_faq",
    )
```

`rule_based_complexity` 依次判断意图、订单号与多跳线索：越界意图返回 `REFUSE`，问候与闲聊返回 `DIRECT`，交易类意图或命中 `_ORDER_ID`、`_TOOL_CUES` 时返回 `AGENT`。它用 `hop_cues >= 1 and len(text) > 18` 判定多跳，最后的兜底是 `SINGLE`。

这套规则是 `AdaptiveRouter.route` 的兜底。生产路径会先让大模型输出一个复杂度判定，只有当模型调用失败或输出无法解析时，系统才退回规则。

`app/retrieval/adaptive.py` —— `AdaptiveRouter.route`

```python
    async def route(self, query: str, intent: IntentResult) -> ComplexityResult:
        fallback = rule_based_complexity(query, intent)
        try:
            response = await self._llm.generate(
                [
                    {"role": "system", "content": COMPLEXITY_SYSTEM},
                    {
                        "role": "user",
                        "content": COMPLEXITY_USER.format(
                            query=query,
                            intent=intent.label.value,
                            prompt_version=PROMPT_VERSION_COMPLEXITY,
                        ),
                    },
                ],
                temperature=0.0,
                max_tokens=256,
                response_format={"type": "json_object"},
            )
            parsed = parse_model(response.content, ComplexityResult)
            return parsed
        except (LLMProviderError, LLMOutputError):
            return fallback
```

`AdaptiveRouter.route` 先算出规则兜底结果 `fallback`，再尝试让大模型返回结构化判定：成功时用 `parse_model` 解析成 `ComplexityResult`，失败时返回兜底结果。它把规则与模型两条路径合在一起，保证路由在任何情况下都有结果。

> 规则兜底的意义有两层：它让系统在模型不可用时仍然能够路由，也让单元测试不必联网就能验证路由逻辑。

---

## 四、改写与多跳的分工

本项目的改写有一个容易混淆的细节，读者需要分清。

`single` 档的改写发生在检索节点里，它对原查询改写一次，用改写结果去检索；`multi` 档的改写发生在 Self-RAG 的每一跳里，它带着"上一跳还缺什么"这个信息去改写。

> 两者的区别在于，前者的改写是静态的、只做一次，后者的改写是动态的、随每一跳的结果调整。

下一篇正文会详细讲后者的机制。

---

## 五、反例与练习

假设系统去掉复杂度判定，对所有问题都走同一条检索链路。

问候语"你好"也会被送进检索，浪费一次延迟；而含三个约束的复杂售后只做一次检索，很可能只命中总则，证据不足。

前者浪费资源，后者导致答案不完整。

> 这个反例说明，复杂度判定的价值在于让检索资源与问题难度匹配。

本部分的练习有两项。

- **改写练习。** 读者应取"买回来的东西不想要了怎么办"，把它改写成两条适合检索的查询，例如"七天无理由退货条件"与"商品退货流程"。
- **深度判断。** 读者应取"定制商品过了七天还有质量问题能不能退"，指出它需要多跳检索的理由，并说明第一跳应当搜退货总则、第二跳应当搜定制商品例外与质量问题处理。

本篇对应的指标是第 11 部分"评测体系"中的检索 Precision@1 与生成幻觉率。改写与复杂度判定共同决定了进入生成阶段的证据质量，读者在阅读下一篇时，可以对照理解多跳检索如何进一步补足证据。

---

**本篇涉及的源码：** `app/retrieval/query_rewrite.py`、`app/retrieval/adaptive.py`
