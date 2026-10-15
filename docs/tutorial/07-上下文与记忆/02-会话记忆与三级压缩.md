# 会话记忆与三级压缩

本文是第七部分的第二篇正文，它讲清多轮对话的历史如何管理。

全文分为五节，前两节讲记忆的两种形态，中间两节讲三级压缩与状态设计，最后一节给出反例与练习。

---

## 一、为什么需要会话记忆

客服对话很少是一问一答就结束的。用户往往先问一个宽泛的问题，再在后续轮次里补充细节。

例如用户先问"能退吗"，系统回答需要更多信息，用户接着说"定制杯，上周买的，有裂纹"。如果系统不记住前文，它就不知道"定制杯"是在回应"什么商品"这个追问，对话会变得无法进行。

> 会话记忆要解决的就是这个问题：让系统记住之前说过的话，从而理解后续的省略式追问。

但记忆带来一个新的问题：如果系统把每一轮对话都原样保留，消息列表会不断增长，最终撑爆模型的上下文预算。

---

## 二、短期记忆与长期记忆

### 2.1 两种形态，同一条列表

本项目对记忆的处理有一条清晰的思路：**短期记忆与长期记忆不是两套存储，而是同一条消息列表在不同压缩程度下的两种形态**。

压缩之前，消息列表包含最近若干轮的完整对话，这就是短期记忆；压缩之后，列表被截断成最近几轮，再配上一条摘要，这就是长期记忆。

摘要承担了"记住更早的事"的职责，窗口承担了"记住最近的事"的职责。

### 2.2 预算的度量

系统需要一个方式来判断"消息列表有多长"。

由于 DeepSeek 的分词器不公开，本项目在 `app/memory/budget.py` 中使用一个**启发式估算**：按约 **1.5 个汉字等于 1 个 token** 来估算长度。

> 这是一个近似值，不是官方分词结果，读者在面试中应当主动说明这一点，避免把估算说成精确计数。

系统的总预算 `token_budget` 默认是 **128000**。系统用"已用 token 除以总预算"得到一个利用率，再根据利用率决定是否压缩、压缩到哪一级。

`app/memory/budget.py` —— 估算长度与计算利用率。

```python
def estimate_tokens(text: str) -> int:
    """DeepSeek tokenizer is not public; CJK-heavy heuristic: ~1 token / 1.5 chars."""
    if not text:
        return 0
    return max(1, int(len(text) / 1.5))


def messages_tokens(messages: list[ChatMessage]) -> int:
    return sum(estimate_tokens(message.content) for message in messages)


def chunks_tokens(chunks: list[RetrievedChunk]) -> int:
    return sum(estimate_tokens(chunk.content) for chunk in chunks)


def utilization(used: int, budget: int) -> float:
    if budget <= 0:
        return 1.0
    return used / budget
```

`estimate_tokens` 把字符数除以 1.5 得到 token 估计，空串返回 0、非空至少返回 1。`utilization` 用已用 token 除以总预算得到利用率，预算非正时直接返回 1.0，避免除零。

---

## 三、三级压缩

### 3.1 三档阈值

`app/memory/budget.py` 中的 `decide_level` 按利用率返回四档之一。

| 利用率区间 | 档位 | 动作 |
| --- | --- | --- |
| 低于 50% | `NONE` | 不压缩 |
| 50% 到 70% | `SOFT_TRUNCATE` | 软截断 |
| 70% 到 85% | `HARD_COMPRESS` | 硬压缩 |
| 超过 85% | `AUTO_COMPACT` | 自动压缩 |

这四个档位对应 `CompressionLevel` 枚举中的 `NONE`、`SOFT_TRUNCATE`、`HARD_COMPRESS` 与 `AUTO_COMPACT`。

`app/memory/budget.py` —— `decide_level`。

```python
def decide_level(used: int, settings: Settings) -> CompressionLevel:
    ratio = utilization(used, settings.token_budget)
    if ratio >= settings.auto_compact_ratio:
        return CompressionLevel.AUTO_COMPACT
    if ratio >= settings.compress_hard_ratio:
        return CompressionLevel.HARD_COMPRESS
    if ratio >= settings.compress_soft_ratio:
        return CompressionLevel.SOFT_TRUNCATE
    return CompressionLevel.NONE
```

`decide_level` 先算利用率，再从高到低依次比较三档阈值：先判是否达到自动压缩，再判硬压缩、软截断，都不满足时返回 `NONE`。阈值本身来自 `Settings`，因此档位边界可配置。

### 3.2 每一档做什么

`app/memory/compression.py` 定义了每一档的动作。

- **软截断**只处理工具结果：它把过长的工具输出截到 **400 字**。
- **硬压缩**进一步把工具输出截到 **160 字**，并对消息列表做滑动窗口，只保留最近 **4 轮**。
- **自动压缩**在硬压缩的基础上再做一步：它调用摘要器 `ConversationSummarizer`，把较早的对话压成一段摘要，然后把摘要作为一条系统消息放到窗口之前。

`app/memory/compression.py` —— 三档的字数阈值与工具结果压缩。

```python
KEEP_RECENT_TURNS = 4
TOOL_SOFT_CHARS = 400
TOOL_HARD_CHARS = 160


def compress_tool_results(
    results: list[ToolResult],
    level: CompressionLevel,
) -> list[ToolResult]:
    limit = {
        CompressionLevel.NONE: 10_000,
        CompressionLevel.SOFT_TRUNCATE: TOOL_SOFT_CHARS,
        CompressionLevel.HARD_COMPRESS: TOOL_HARD_CHARS,
        CompressionLevel.AUTO_COMPACT: TOOL_HARD_CHARS,
    }[level]
    compressed: list[ToolResult] = []
    for result in results:
        cloned = result.model_copy(deep=True)
        text = str(cloned.output)
        if len(text) > limit:
            cloned.output = {"truncated": True, "preview": text[:limit]}
            cloned.truncated = True
        compressed.append(cloned)
    return compressed
```

三个常量给出了窗口保留轮数 `KEEP_RECENT_TURNS` 与软、硬两档的字符上限 `TOOL_SOFT_CHARS`、`TOOL_HARD_CHARS`。`compress_tool_results` 按档位查表取上限，超过上限就把工具输出替换成带 `truncated` 标记的预览。

`app/memory/compression.py` —— `apply_compression`。

```python
def apply_compression(
    messages: list[ChatMessage],
    tool_results: list[ToolResult],
    summary: str,
    settings: Settings,
) -> tuple[list[ChatMessage], list[ToolResult], CompressionLevel, str]:
    used = messages_tokens(messages) + estimate_tokens(summary)
    level = decide_level(used, settings)
    tools = compress_tool_results(tool_results, level)
    if level in {CompressionLevel.HARD_COMPRESS, CompressionLevel.AUTO_COMPACT}:
        window = sliding_window(messages)
        if summary:
            window = [ChatMessage(role="system", content=f"对话摘要：{summary}")] + window
        return window, tools, level, summary
    if level == CompressionLevel.SOFT_TRUNCATE:
        return messages, tools, level, summary
    return messages, tools, level, summary
```

`apply_compression` 把消息长度与摘要长度相加得到已用量，再据此定档。只有硬压缩与自动压缩两档才启用滑动窗口，并在有摘要时把摘要作为一条 `system` 消息插到窗口之前；软截断档只压工具结果，不动消息列表。

> 这三档是递进的：利用率越高，动作越激进。

这样设计的好处是，系统在预算宽松时不浪费算力，在预算紧张时才逐步加码，避免一上来就做昂贵的摘要。

### 3.3 摘要器

`app/memory/summarizer.py` 中的 `ConversationSummarizer.summarize` 取最近 **16 条**消息，调用大模型生成一段不超过 **800 字**的摘要。

当调用失败时，它退回一个简单方案：把最近 **4 条**消息各截取前 **40 字**拼接。

> 这条兜底保证了即使模型不可用，摘要也不会为空。

---

## 四、压缩发生在哪里

`app/agents/nodes/memory.py` 中的 `memory_node` 是压缩的执行点。

它把当前查询与最终答案追加到消息列表，然后调用 `apply_compression`。如果判定为自动压缩，它再调用摘要器生成新摘要，并把压缩过程重跑一遍。

节点的返回只包含**消息列表、工具结果与摘要**三项，其余状态不变。

这里有一处与状态设计相关的关键决定，读者需要理解。`app/agents/state.py` 中的 `AgentState` 是 `TypedDict`，节点返回的字典会**替换**列出的键，而不是追加。

> 项目**没有**使用 `Annotated[list, add]` 这种自动追加的写法。

之所以这样选择，是因为自动追加会让消息列表在长会话里无声地膨胀，直到撑爆 **128k** 预算，而且难以断言与观测。

把压缩放在显式的 `compact_memory` 节点里，系统就能清楚地知道"何时摘要、摘要了什么"，这也让压缩逻辑可测试。

---

## 五、反例与练习

**反例。** 假设系统使用自动追加的 reducer，不做显式压缩。

一段长会话进行到二十轮之后，消息列表累积了全部历史，token 用量悄然逼近上限。某一次请求中，系统把超长的上下文发给模型，模型返回长度错误，整轮对话失败。

更糟的是，这个失败发生在会话中途，用户此前积累的上下文也随之丢失。

> 这个反例说明，记忆管理必须是显式的、可观测的，而不能依赖一个隐式的自动追加。

本部分的练习有两项：

- **练习一：推演压缩。** 读者应假设会话已占预算的 80%，说明系统会触发硬压缩、把工具结果截到 160 字并只保留最近 4 轮。
- **练习二：解释设计。** 读者应说明为什么本项目不使用自动追加的 reducer，而选择在独立节点里显式压缩。

> **指标回指。** 本篇对应的指标是第 11 部分"评测体系"中的端到端延迟。记忆管理直接影响每轮请求的输入规模，而输入规模又影响生成延迟。读者在阅读第 12 部分"工程化与上线"时，可以对照理解 token 用量如何被上报与观测。

---

**本篇涉及的源码：** `app/memory/budget.py`、`app/memory/compression.py`、`app/memory/summarizer.py`、`app/agents/nodes/memory.py`、`app/agents/state.py`
