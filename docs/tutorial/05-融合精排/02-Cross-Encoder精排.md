# Cross-Encoder 精排

> 本文是第五部分的第二篇正文，它讲清候选如何重新排序。

全文分为五节。前两节讲精排的必要性与原理，中间两节讲本项目的实现与降级，最后一节给出反例与练习。

---

## 一、召回分数为什么不够用

召回阶段的分数只能说明"看起来相关"，它无法判断"这段是否真的回答了当前这个问题"。

以一个具体的例子说明。用户问"定制商品过了七天还有质量问题能不能退"，政策库里有两段切片：第一段是退货总则，讲的是七天无理由的通用规则；第二段是品类例外，讲的是定制商品的特殊处理。

这两段都与"退货"高度相关，召回阶段给出的分数可能非常接近，甚至总则排在例外之前。然而对这个问题而言，真正的答案在例外那一段，总则只提供了背景。

召回阶段之所以难以区分这种细微差别，是因为它必须快。为了在毫秒级返回结果，它只能对查询和文档分别编码，然后比较两个向量的距离。

> 这种分开编码的方式无法让查询与文档"逐词对照"，因此它看不到"定制"这个限定词对答案的决定性影响。

---

## 二、精排的原理

### 2.1 双塔与交叉编码器

召回阶段使用的模型称为**双塔模型（Bi-Encoder）**。它把查询编码成一个向量，把文档编码成另一个向量，两侧互不干涉。

这种结构可以提前把文档向量算好并缓存，查询时只需算一次查询向量再做比较。它换来了速度，牺牲了精度。

精排阶段使用的模型称为**交叉编码器（Cross-Encoder）**。它把查询与文档拼在一起，作为一个整体送进模型，让模型在编码时就能看到二者的交互。

这样一来，模型能够判断"定制"这个限定词是否真的对应了文档中的例外条款，排序精度因此显著提高。代价是它无法预计算：每一条候选都要与查询拼接后重新过一遍模型，因此它比召回慢得多。

| 维度 | 双塔模型（Bi-Encoder） | 交叉编码器（Cross-Encoder） |
| --- | --- | --- |
| 编码方式 | 查询与文档分开编码 | 查询与文档联合编码 |
| 是否预计算 | 可预计算 | 不可预计算 |
| 速度 | 快 | 慢 |
| 精度 | 较低 | 较高 |

### 2.2 两阶段架构

正因为交叉编码器慢，系统不能对全部切片做精排，只能对召回后的少量候选做精排。

这就形成了检索系统的经典两阶段架构：第一阶段用快而粗的召回把候选缩到几十条，第二阶段用慢而准的精排把候选排到前几条。

本项目在 `app/retrieval/reranker.py` 中默认只对召回结果的前 `rerank_top_n = 5` 条做精排，正是这一架构的落地。

---

## 三、本项目的实现

精排的提供者在 `app/providers/reranker.py`。生产路径使用本地加载的交叉编码器，默认检查点是 `BAAI/bge-reranker-base`。

`CrossEncoderRerankProvider.rerank` 把查询与每条文档拼成 `(query, document)` 对，批量送入模型打分，再按分数重排。

`app/providers/reranker.py` —— `CrossEncoderRerankProvider.rerank`

```python
    async def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        top_n: int,
    ) -> list[tuple[int, float]]:
        model = self._ensure_model()
        if model is None:
            return await self._fallback.rerank(query, documents, top_n=top_n)
        pairs = [(query, document) for document in documents]
        scores = await asyncio.to_thread(self._predict, model, pairs)
        ranked = sorted(enumerate(scores), key=lambda item: item[1], reverse=True)
        return [(index, score) for index, score in ranked[:top_n]]

    @staticmethod
    def _predict(model: Any, pairs: list[tuple[str, str]]) -> list[float]:
        raw = model.predict(pairs, show_progress_bar=False)
        return [float(score) for score in raw]
```

`rerank` 先确保模型可用：若 `_ensure_model` 返回 `None`，它直接转发给 `LexicalRerankProvider`。可用时，它把查询与文档拼成 `(query, document)` 对，通过 `asyncio.to_thread` 在线程中批量打分，再按分数降序取前 `top_n` 条，返回 `(原下标, 分数)`。

这里有一条硬性事实，读者必须记准：本项目的精排模型是 `BAAI/bge-reranker-base`，**不是 Cohere**。Cohere 是一个商业重排服务，本项目从未调用过它。

> 把精排模型写成 Cohere，是最容易被代码对质发现的一处错误，因为它与 `cross_encoder_model` 的默认配置直接冲突。

`DocumentReranker.rerank` 负责把提供者返回的 `(原下标, 分数)` 还原成切片列表：它按新分数重新排序，更新每个切片的名次，并把来源标记为 `rerank`。这一层封装把"打分"与"重排"分开，便于单独测试。

`app/retrieval/reranker.py` —— `DocumentReranker.rerank`

```python
    async def rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        *,
        top_n: int,
    ) -> list[RetrievedChunk]:
        if not chunks:
            return []
        documents = [chunk.content for chunk in chunks]
        ranked = await self._provider.rerank(query, documents, top_n=min(top_n, len(chunks)))
        results: list[RetrievedChunk] = []
        for new_rank, (original_index, score) in enumerate(ranked, start=1):
            chunk = chunks[original_index].model_copy(deep=True)
            chunk.score = score
            chunk.rank = new_rank
            chunk.source = "rerank"
            results.append(chunk)
        return results
```

`DocumentReranker.rerank` 先从每条切片取出正文交给提供者，再把返回的 `(original_index, score)` 映射回原切片：它用 `model_copy(deep=True)` 复制一份，写入新的 `score` 与 `rank`，并把 `source` 标为 `rerank`。

---

## 四、降级路径

精排依赖 `sentence-transformers` 与模型权重，这两者可能不可用。

当依赖缺失或权重加载失败时，`CrossEncoderRerankProvider` 退回 `LexicalRerankProvider`，也就是按查询与文档的字符重叠度打分。

`app/providers/reranker.py` —— `LexicalRerankProvider.rerank`

```python
    async def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        top_n: int,
    ) -> list[tuple[int, float]]:
        query_tokens = set(query.lower())
        scored: list[tuple[int, float]] = []
        for index, document in enumerate(documents):
            doc_tokens = set(document.lower())
            if not query_tokens:
                score = 0.0
            else:
                score = len(query_tokens & doc_tokens) / len(query_tokens)
            scored.append((index, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_n]
```

`LexicalRerankProvider.rerank` 把查询与文档都拆成字符集合，用两者的交集大小除以查询字符数作为分数，再按分数降序返回前 `top_n` 条。它是无权重环境下的替代实现，并不做查询与文档的联合编码。

> 这条降级路径只用于测试环境与无权重开发，**它不是交叉编码器**，不能写进简历，也不能作为精排能力的证明。

测试环境默认走降级路径，这是为了让单元测试不下载模型权重。当生产环境加载成功时，评测报告里会出现 `hybrid+cross-encoder` 这一行，读者可以用它确认精排确实生效。

---

## 五、反例与练习

假设系统去掉精排，只保留融合。上一部分已经说明，在本项目的 **65 条**评测集上，BM25 加向量再加 RRF 的成绩与仅向量召回相同，都是 Precision@1 **83.1%**。

加入 Cross-Encoder 之后，各项指标随之提升。

| 指标 | 加精排后 | 相对 BM25 基线 |
| --- | --- | --- |
| Precision@1 | **89.2%** | +12.3 个百分点 |
| Recall@3 | **97.7%** | +7.7 个百分点 |
| MRR | **0.94** | — |

相对融合后的结果，Precision@1 提升了约 **6.1 个百分点**。

> 这组对比清楚地说明，增益来自精排，而不是来自融合。

本部分的练习有两项。

- **解释差异。** 读者应说明交叉编码器与双塔模型在编码方式上的区别，以及这一区别为什么带来了精度提升。
- **核对模型名。** 读者应在简历中检查精排模型的写法，确认它是 `bge-reranker-base` 而不是 Cohere。

本篇对应的指标是第 11 部分"评测体系"中的检索 Precision@1、Recall@3 与 MRR。Hybrid 加精排的 **89.2% / 97.7% / 0.94** 是本项目检索链路的最优成绩，也是简历中最值得写的一组数字。读者在阅读第 11 部分时，可以对照完整消融表理解每一步的贡献。

---

**本篇涉及的源码：** `app/retrieval/reranker.py`、`app/providers/reranker.py`
