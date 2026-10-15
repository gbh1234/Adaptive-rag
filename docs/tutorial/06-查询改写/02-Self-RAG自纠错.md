# Self-RAG 自纠错

> 本文是第六部分的第二篇正文，它讲清检索后的证据评分与迭代补检索。

全文分为五节。前两节讲 Self-RAG 的思路，中间两节讲本项目的实现与它带来的效果，最后一节给出反例与练习。

---

## 一、一次检索为什么可能不够

多约束问题很难被一次检索覆盖。

以"定制商品过了七天还有质量问题能不能退"为例，第一跳检索很可能只命中退货总则，因为"退货"是这个查询里最显眼的词。

总则告诉了系统"七天无理由"的通用规则，但它没有回答"定制商品是否例外"，也没有回答"质量问题是否特殊处理"。系统拿到的证据是不完整的，如果就此生成答案，它只能给出一个笼统甚至错误的回答。

> 这说明系统需要一个机制：在检索之后判断证据是否足够，如果不够，就带着"还缺什么"这个信息再检索一次。这个机制就是 Self-RAG。

---

## 二、Self-RAG 的思路

**Self-RAG（Self-Reflective RAG，自反思检索）** 的核心是一个循环：检索、评分、改写、再检索。

系统先检索一批证据，然后让模型对证据做一次评分，判断它是否相关、是否足够。如果足够，循环结束；如果不够，模型还要指出"缺了哪个方面"，系统据此改写查询，发起下一跳检索。

这里的关键在于"指出缺了什么"这一步。

普通的迭代检索只是把同一个查询再搜一遍，结果不会有变化；Self-RAG 的不同之处在于，它让模型明确说出缺失的维度，例如"缺少定制商品的例外条件"，然后带着这个维度去改写查询。

> 改写后的查询更聚焦，因此下一跳更容易命中之前漏掉的切片。

---

## 三、本项目的实现

`app/retrieval/self_rag.py` 中的 `SelfRAGLoop.retrieve` 实现了这个循环。

它用一个字典 `accumulated` 累积每一跳命中的切片，循环最多执行 `max_retrieval_hops` 次，本项目的默认值是 **3**。

每一跳里，它依次做四件事。

- 先调用改写器，把"上一跳还缺什么"传进去；
- 再用改写后的查询去检索与精排；
- 然后把新命中的切片并入累积结果；
- 最后调用评分器 `_grade`，判断证据是否足够。如果足够，循环提前结束。

`app/retrieval/self_rag.py` —— `SelfRAGLoop.retrieve`

```python
    async def retrieve(
        self,
        query: str,
        *,
        top_k: int,
    ) -> list[RetrievedChunk]:
        accumulated: dict[str, RetrievedChunk] = {}
        current_query = query
        missing = ""
        for _hop in range(self._settings.max_retrieval_hops):
            rewritten = await self._rewriter.rewrite(current_query, missing_aspect=missing)
            hop_query = rewritten[0]
            candidates = await self._retriever.retrieve(hop_query, top_k=top_k)
            reranked = await self._reranker.rerank(
                hop_query, candidates, top_n=self._settings.rerank_top_n
            )
            for chunk in reranked:
                accumulated[chunk.chunk_id] = chunk
            grade = await self._grade(query, list(accumulated.values()))
            if grade.sufficient:
                break
            missing = grade.missing_aspect or "more specific policy conditions"
            current_query = query
        return list(accumulated.values())[: self._settings.rerank_top_n * 2]
```

`retrieve` 以 `accumulated` 字典累积切片，循环上限是 `max_retrieval_hops`。每一跳它先把 `missing` 交给改写器，用改写后的首条查询检索并精排，再调用 `_grade`；若 `grade.sufficient` 为真则 `break`，否则用 `grade.missing_aspect` 更新缺失维度进入下一跳。

评分器的输出是一个结构化的 `GradeResult`，它包含三个字段。

- `relevant` 表示证据是否相关；
- `sufficient` 表示证据是否足够；
- `missing_aspect` 表示还缺哪个方面。

`app/retrieval/self_rag.py` —— `GradeResult`

```python
class GradeResult(BaseModel):
    relevant: bool
    sufficient: bool
    missing_aspect: str = ""
    rationale: str = ""
```

`GradeResult` 用 pydantic 定义评分结果，`relevant` 与 `sufficient` 是布尔判定，`missing_aspect` 默认空串用于携带"还缺什么"，`rationale` 默认空串用于记录理由。

项目把自反思实现成结构化 JSON，而不是某种特殊 token，原因是 JSON 可以被 schema 校验，也便于测试。

`app/retrieval/self_rag.py` —— `SelfRAGLoop._grade`

```python
    async def _grade(self, query: str, chunks: list[RetrievedChunk]) -> GradeResult:
        evidence = "\n\n".join(f"[{c.chunk_id}] {c.content}" for c in chunks[:6]) or "(empty)"
        try:
            response = await self._llm.generate(
                [
                    {"role": "system", "content": GRADE_SYSTEM},
                    {"role": "user", "content": GRADE_USER.format(query=query, evidence=evidence)},
                ],
                temperature=0.0,
                max_tokens=256,
                response_format={"type": "json_object"},
            )
            return parse_model(response.content, GradeResult)
        except (LLMProviderError, LLMOutputError):
            return GradeResult(relevant=bool(chunks), sufficient=bool(chunks), rationale="fallback")
```

`_grade` 取前 6 条切片拼成证据文本，用 `json_object` 格式让模型评分并解析为 `GradeResult`。当调用失败或输出无法解析时，它退回 `GradeResult(relevant=bool(chunks), sufficient=bool(chunks), rationale="fallback")`，即只要累积证据非空就判为足够。

> 当评分调用失败时，系统退回一个保守判断：只要累积证据非空，就认为足够，从而避免循环空转。

---

## 四、它带来的效果

Self-RAG 的价值最终要落到指标上。本项目的实测覆盖了 **65 条**政策问句，对比了三种生成条件。

| 生成条件 | 忠实度 | 幻觉率 |
| --- | --- | --- |
| 无检索 | 80% | **20%** |
| 普通 RAG | 96.9% | **3.1%** |
| RAG 加自纠错 | **100%** | **0%** |

这三个数字要连起来读。

无检索时，模型没有依据，只能凭自身知识作答，幻觉率高达 **20%**；一旦提供证据，幻觉率立刻降到 **3.1%**，说明检索本身是压制幻觉的主力；再叠加自纠错，幻觉率进一步降到 **0%**，说明自纠错是最后的把关。

> 这里有一条必须主动说明的口径：裁判与生成器是同一个模型 `deepseek-chat`，同模型裁判偏乐观，因此这组数字应当与关键词命中率并列报出，而不是单独强调。

---

## 五、反例与练习

假设系统去掉自纠错，只保留一次检索与普通生成。

在那些需要多约束的问题上，系统拿到的证据只有总则，模型只能基于总则作答，它可能给出"可以退货"这样的笼统结论，而忽略了定制商品本就不适用七天无理由这个关键例外。用户据此行动，可能产生误解。

> 这个反例说明，自纠错的价值不在于提升关键词命中，而在于让答案真正被证据支撑。

事实上，本项目的自纠错把幻觉率从 **3.1%** 压到 **0%**，但它**没有**再提高关键词命中率，因为它修的是"证据支撑"，不是"补全标准答案的词"。

本部分的练习有两项。

- **设计缺失维度。** 读者应取"定制商品过了七天还有质量问题能不能退"，写出第一跳之后模型应当指出的缺失维度。
- **解释指标。** 读者应说明为什么自纠错能降低幻觉率，却不能提高关键词命中率。

本篇对应的指标是第 11 部分"评测体系"中的生成忠实度、幻觉率与关键词命中。忠实度从 **80%** 到 **96.9%** 再到 **100%**，幻觉率从 **20%** 到 **3.1%** 再到 **0%**，这组数字是自纠错价值的最直接证据。读者在阅读第 11 部分时，可以对照完整消融表理解每一步的贡献。

---

**本篇涉及的源码：** `app/retrieval/self_rag.py`
