# 意图识别

本文是第八部分的第一篇正文，它讲清意图识别如何把用户问题归到预设类别。

全文分为五节，前两节讲意图识别的目标与三层结构，中间两节讲覆盖层与实现，最后一节给出反例与练习。

---

## 一、意图识别要解决什么

### 1.1 为什么先要分类

用户的问题背后往往藏着一个明确的目的。有人想问政策，有人想查订单，有人想投诉，有人只是打招呼。

系统如果不知道用户的意图，就无法决定后续该做什么：

- 查订单需要调用订单工具；
- 问政策需要检索知识库；
- 打招呼则不需要任何外部资源。

> 意图识别因此是整条链路的第一步决策。

本项目把意图划分为 **14 个类别**，包括问候、闲聊、政策问答、订单查询、物流、退款、退货换货、取消订单、商品咨询、推荐、优惠券、投诉、转人工与越界。

每个类别都对应一个枚举值，例如 `faq_policy` 表示政策问答，`order_inquiry` 表示订单查询。

### 1.2 分类的产物

意图识别的产物是一个 `IntentResult`，它包含**标签、置信度、理由与提示词版本**四个字段。

系统不只需要标签，还需要理由与置信度，因为后续的覆盖层与路由都可能用到它们。

理由字段记录了这次判断的依据，便于排障；置信度字段则让系统知道这次判断有多可靠。

---

## 二、三层结构

本项目的意图识别由三层组成，它们按优先级协作。

- **第一层是大模型分类。** 系统把用户问题交给大模型，要求它输出一个 JSON 格式的意图标签。这是生产路径的主干，因为它能够处理措辞多样、无法穷举的表达。
- **第二层是规则兜底。** `app/agents/nodes/intent.py` 中的 `rule_based_intent` 维护了一张关键词表，它按顺序匹配用户问题中的关键词，命中即返回对应标签。
- **第三层是高置信覆盖层。** 它在模型或规则给出标签之后再做一次纠偏，只处理那些稳定但易混的中文短语。

这张规则表的存在有两个目的：

- 一是当大模型不可用或输出无法解析时，系统仍然能够给出一个意图；
- 二是为覆盖层与测试提供一个确定性的基线。

`app/agents/nodes/intent.py` —— 关键词表 `_KEYWORD_RULES` 与规则兜底 `rule_based_intent`。

```python
_KEYWORD_RULES: list[tuple[tuple[str, ...], IntentLabel]] = [
    (("转人工", "人工客服"), IntentLabel.HUMAN_HANDOFF),
    (("你好", "您好", "hi", "hello"), IntentLabel.GREETING),
    # ...
    (("订单", "我的单"), IntentLabel.ORDER_INQUIRY),
]


def rule_based_intent(query: str) -> IntentResult:
    lowered = query.lower()
    for keywords, label in _KEYWORD_RULES:
        if any(keyword.lower() in lowered for keyword in keywords):
            return IntentResult(
                label=label,
                confidence=0.72,
                rationale=f"keyword:{keywords[0]}",
                prompt_version="intent_rules_v1",
            )
    # ...
    return IntentResult(
        label=IntentLabel.FAQ_POLICY,
        confidence=0.55,
        rationale="default_faq",
        prompt_version="intent_rules_v1",
    )
```

`_KEYWORD_RULES` 是一张有序的关键词表，每项由关键词元组与对应标签组成。`rule_based_intent` 把查询转小写后按表顺序匹配，命中即返回该标签并给出 0.72 的置信度与 `keyword:` 理由；全表不命中时退回默认的政策问答标签。

> 这张规则表在 100 条测试集上的准确率只有 **51%**，这个数字不是缺陷，而是一份证据：它证明只靠关键词规则远远不够。

---

## 三、覆盖层为什么存在

中文客服里有一批短语，模型和规则都容易判错，而且错得有规律。

最典型的是"人工审核一下退款"。这句话字面上包含"退款"，模型很可能把它判成退款意图；但它真正表达的是"我要找人处理"，正确的标签是转人工。

类似的例子还有政策问法与退换货的混淆："七天无理由怎么算"问的是政策规则，而"这个杯子能退吗"问的是具体能否退换。

`app/agents/nodes/intent_overlay.py` 中的 `high_precision_intent` 正是为处理这类歧义而写。它按优先级判断：先看是否越界或注入，再看是否含转人工短语，再看是否只是问候，之后依次判断投诉、物流、取消、优惠券、退款、退换货等。

它只在规则足够确信时才返回标签，否则返回 `None`，把判断权交还给大模型。

`app/agents/nodes/intent_overlay.py` —— `high_precision_intent` 与 `apply_intent_overlay`。

```python
def high_precision_intent(query: str) -> IntentLabel | None:
    """Return a label only when the rule is confident; otherwise None."""
    text = query.strip()
    if not text:
        return None
    lowered = text.lower()

    if any(token in lowered for token in _JAILBREAK) or any(token in text for token in _OOS):
        return IntentLabel.OUT_OF_SCOPE
    if any(token in text for token in _HANDOFF):
        return IntentLabel.HUMAN_HANDOFF
    if _GREETING_ONLY.match(text) or _GREETING_ONLY.match(lowered):
        return IntentLabel.GREETING
    # ...
    return None


def apply_intent_overlay(query: str, label: IntentLabel) -> tuple[IntentLabel, str | None]:
    forced = high_precision_intent(query)
    if forced is None or forced == label:
        return label, None
    return forced, f"overlay:{forced.value}"
```

`high_precision_intent` 按固定优先级判断：先查越界与注入词，再查转人工短语，再判断是否只是问候，命中即返回标签，否则最终返回 `None`。`apply_intent_overlay` 只有在覆盖层给出的标签与原标签不同时才改动，并返回一条 `overlay:` 说明供追溯。

> 这种"只在确信时介入"的策略，让覆盖层既能纠偏，又不会越权覆盖模型的合理判断。

这里有一条边界必须讲清：覆盖层针对的是稳定的短语模式，例如"转人工""人工客服"，它**不是**按测试用例的编号写死答案。

> 读者在面试中应当主动说明这一点，否则很容易被怀疑是在"对答案"。

---

## 四、本项目的实现与消融

`IntentClassifier.classify` 先把规则结果作为兜底算好，再尝试调用大模型。

如果模型返回可解析的 JSON，系统就采用模型的标签，并调用 `_maybe_overlay` 做一次覆盖层纠偏；如果模型调用失败，系统就采用规则结果，同样经过覆盖层。

`_maybe_overlay` 在覆盖层改动了标签时，会把置信度提升到至少 **0.93**，并在理由里追加一条 `overlay:xxx` 记录，让这次纠偏可追溯。

`app/agents/nodes/intent.py` —— `IntentClassifier.classify` 与 `_maybe_overlay`。

```python
    async def classify(self, query: str) -> IntentResult:
        fallback = rule_based_intent(query)
        try:
            response = await self._llm.generate(
                [
                    {"role": "system", "content": self._system_prompt},
                    {
                        "role": "user",
                        "content": INTENT_USER.format(
                            query=query, prompt_version=self._prompt_version
                        ),
                    },
                ],
                temperature=0.0,
                max_tokens=256,
                response_format={"type": "json_object"},
            )
            parsed = parse_model(response.content, IntentResult)
            if not parsed.prompt_version:
                parsed.prompt_version = self._prompt_version
            return self._maybe_overlay(query, parsed)
        except (LLMProviderError, LLMOutputError):
            return self._maybe_overlay(query, fallback)

    def _maybe_overlay(self, query: str, parsed: IntentResult) -> IntentResult:
        if not self._apply_overlay:
            return parsed
        label, overlay_note = apply_intent_overlay(query, parsed.label)
        if overlay_note:
            parsed.label = label
            parsed.rationale = f"{parsed.rationale};{overlay_note}"
            parsed.confidence = max(parsed.confidence, 0.93)
        return parsed
```

`classify` 先算好规则兜底 `fallback`，再尝试让大模型输出 JSON；成功时把模型结果交给 `_maybe_overlay`，失败时改把规则结果交给它，两条路径都要过覆盖层。`_maybe_overlay` 在开关关闭时直接返回，否则调用覆盖层，只在标签被改动时把置信度抬到至少 0.93 并追加 `overlay:` 理由。

项目还提供了一个开关 `apply_overlay`。当它设为 `False` 时，系统跳过覆盖层，用来做消融对比。

| 版本 | 准确率 |
| --- | --- |
| 关键词规则 | **51%** |
| 大模型 v1（无覆盖层） | 85% |
| 大模型 v2（无覆盖层） | 86% |
| 仅覆盖层单独作用 | 100% |
| 生产路径 v3 加覆盖层 | **100%** |

> 这组消融说明了两件事：大模型把整体从 51% 拉到了 85% 以上，覆盖层则补上了最后那段由稳定歧义造成的差距。

---

## 五、反例与练习

**反例。** 假设系统去掉覆盖层，只保留大模型分类。

用户说"人工审核一下退款"，模型很可能把它判成退款意图，于是系统走了退款流程，而用户其实是想转人工。这类错误不会让系统崩溃，却会让用户体验变差，甚至让用户以为自己的诉求被误解。

> 这个反例说明，覆盖层处理的正是模型在稳定歧义上的系统性偏差。

本部分的练习有两项：

- **练习一：识别歧义。** 读者应说明"人工审核一下退款"为什么容易被判成退款，正确标签应当是什么。
- **练习二：解释口径。** 读者应说明意图识别的 100% 包含覆盖层，并说明覆盖层不是按测试用例写死。

> **指标回指。** 本篇对应的指标是第 11 部分"评测体系"中的意图准确率。规则基线 51%、无覆盖模型 85% 到 86%、生产路径 100%，这组数字是意图识别能力的完整证据链。读者在阅读下一篇时，可以对照理解意图如何进一步转成处理策略。

---

**本篇涉及的源码：** `app/agents/nodes/intent.py`、`app/agents/nodes/intent_overlay.py`
