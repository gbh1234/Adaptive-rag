# 稠密召回与向量库

本文是第四部分的第二篇正文，它讲清语义召回的流程与本项目的向量库设计。

全文分为五节，前两节讲稠密召回的流程，中间两节讲向量库与容错，最后一节给出反例与练习。

---

## 一、稠密召回解决什么

关键词召回要求查询与文档在字面上重合，这带来了一个难以绕开的短板。

用户问"买回来的东西不想要了"，政策文档写的是"七天无理由退货"，两句话没有一个字相同，关键词召回给出零命中。

稠密召回要解决的正是这个问题。它先把查询与文档都映射成向量，再比较向量的接近程度。在这个新的空间里，"不想要了"与"七天无理由"方向接近，因此即使字面不同，系统也能把它们关联起来。

这种能力称为**语义召回**。

> 语义召回让系统能够容忍口语化表达、同义改写与近义句式，是关键词召回的重要补充。

---

## 二、稠密召回的流程

稠密召回的流程可以分为三步。

| 步骤 | 操作 |
| --- | --- |
| 查询编码 | 用嵌入模型把查询映射成向量，模型与入库时一致 |
| 相似度比较 | 查询向量与库中每个切片向量做比较 |
| 排序取前 | 按相似度从高到低排序，取前 `top_k` 条 |

本项目的比较方式在上一部分已经讲过，是归一化之后的点积，等价于余弦相似度。

这三步里，第一步的模型一致性最关键。如果查询用了一个模型、文档用了另一个模型，那么两侧向量落在两个不同的空间里，比较就完全失去意义。

> 本项目在查询侧与文档侧使用同一套嵌入提供者，正是为了守住这条底线。

`VectorRetriever.search` 把这三步串起来：编码查询、交给向量库、返回结果。

`app/retrieval/vector.py` —— `VectorRetriever.search`

```python
    async def search(self, query: str, *, top_k: int) -> list[RetrievedChunk]:
        vectors = await self.embedder.embed([query])
        if not vectors:
            return []
        # Qdrant client is sync; do not block the event loop.
        return await asyncio.to_thread(self.store.search, vectors[0], top_k=top_k)
```

`VectorRetriever.search` 先用同一个 `embedder` 把查询编码成向量，再把向量交给向量库检索。由于 Qdrant 客户端是同步的，它用 `asyncio.to_thread` 把检索放到线程里执行，避免阻塞事件循环。

---

## 三、向量库如何组织

### 3.1 内存库与 Qdrant

`app/retrieval/vector.py` 提供了两种向量库实现。

| 实现 | 存储与检索方式 | 特点 |
| --- | --- | --- |
| `InMemoryVectorStore` | 向量放在进程内存，检索时暴力遍历 | 本地开发与测试不依赖 Docker |
| `QdrantVectorStore` | 向量存到远端 Qdrant，由 Qdrant 建索引与检索 | 可独立部署、可水平扩展、point id 稳定 |

系统在 `QDRANT_URL` 非空时使用 Qdrant，否则退回内存库。

本项目同时保留这两种实现，是一个刻意的设计。系统在 **39 篇文档**这个规模上，两种实现都能胜任，因此选择的依据不是性能，而是部署环境的便利性。

`InMemoryVectorStore.search` 展示了内存库的暴力检索。

`app/retrieval/vector.py` —— `InMemoryVectorStore.search`

```python
    def search(self, query_vector: list[float], *, top_k: int) -> list[RetrievedChunk]:
        scored: list[tuple[float, VectorRecord]] = [
            (cosine(query_vector, record.embedding), record) for record in self._records
        ]
        scored.sort(key=lambda item: item[0], reverse=True)
        results: list[RetrievedChunk] = []
        for rank, (score, record) in enumerate(scored[:top_k], start=1):
            chunk = record.chunk.model_copy(deep=True)
            chunk.score = float(score)
            chunk.rank = rank
            chunk.source = "vector"
            results.append(chunk)
        return results
```

它遍历所有记录，对每条记录调用 `cosine` 得到分数，再按分数降序排序取前 `top_k` 条。返回前它给每条结果填回 `score`、`rank` 与 `source`，与 BM25 路保持同一套字段，供上层融合使用。

### 3.2 距离度量的一致性

Qdrant 集合的创建参数里，距离度量被明确配置为 **COSINE**。

这一步必须与内存库保持一致：内存库做的是归一化点积，等价于余弦；如果 Qdrant 改用欧氏距离，那么同一份向量在两个库里的排序就会不同，系统行为将随部署环境而漂移。

> 读者应当记住这条原则：向量库的距离度量，必须与向量生成时的归一化方式配套。

`cosine` 是内存库使用的相似度函数，它把归一化后的点积当作余弦相似度。

`app/retrieval/vector.py` —— `cosine`

```python
def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False))
```

`cosine` 只做逐元素相乘再求和，没有除以向量长度，因为它假定输入已经归一化。内存库把归一化点积当作余弦相似度使用，Qdrant 侧则通过集合参数声明同样的度量。

Qdrant 集合在建库时就声明了 COSINE 距离。

`app/retrieval/vector.py` —— `QdrantVectorStore.ensure_collection`

```python
    def ensure_collection(self) -> None:
        from qdrant_client.models import Distance, VectorParams

        client = self._ensure_client()
        names = [item.name for item in client.get_collections().collections]
        if self._collection not in names:
            client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(size=self._dim, distance=Distance.COSINE),
            )
```

`ensure_collection` 在建集合时把 `distance` 设为 `Distance.COSINE`，并在集合已存在时跳过创建。这一行参数就是 3.2 节强调的一致性来源：只要 Qdrant 与内存库都用余弦度量，同一份向量在两个库里的排序才会一致。

---

## 四、两路召回如何容错

### 4.1 独立失败

`app/retrieval/hybrid.py` 中的 `HybridRetriever` 体现了一条重要的工程原则：**两路召回各自独立失败**。

它把 BM25 与向量检索分别包在 `try/except` 里，任何一路抛错都只记录该路的错误，不影响另一路。只有当两路**都**为空时，系统才抛出 `RetrievalError`。

这条设计的现实意义在于：Qdrant 可能抖动，嵌入服务可能超时，但客服系统不能因此完全哑火。当向量路不可用时，BM25 仍然能够独立工作，系统至少还能给出关键词层面的召回结果；反过来，当 BM25 因语料异常而失败时，向量路也能顶上。

> 把两路召回都当作一等公民，而不是把其中一路当作"演示开关"，是本项目的一个基本立场。

### 4.2 与缓存的关系

政策类查询会经过一层缓存，默认存活时间为 **60 秒**。

这里有一条例外：含有订单号或"订单"字样的查询**不缓存**，因为订单状态会变化，缓存会让用户看到过期结果。

缓存的实现在 `app/retrieval/cache.py`，读者在阅读第 12 部分"工程化与上线"时可以一并理解它的部署依赖。

---

## 五、反例与练习

假设系统只保留向量召回，且嵌入模型退回哈希实现。

哈希向量几乎没有语义，它把文本按字符哈希随机撒到空间里，两段意思相近的文本不会因此靠得更近。实测中，哈希向量的 Hit@1 只有约 **3%**，这个数字几乎等于随机命中。

如果有人把这个降级路径产生的 Hybrid 结果说成"语义检索"，那就是对系统的严重误读。

> 这个反例说明，稠密召回的价值完全建立在真实嵌入模型之上，降级路径不能作为能力证明。

本部分的练习有两项。

- **对比召回。** 读者应取"买回来的东西不想要了"这一句，分别观察关键词召回与语义召回的结果，解释二者差异。
- **检查一致性。** 读者应说明如果查询侧与文档侧用了不同的嵌入模型，检索会出现什么现象。

> **指标回指。** 本篇对应的指标同样是第 11 部分"评测体系"中的检索 Precision@1 与 Recall@3。仅使用 `bge-small-zh-v1.5` 时，这两项分别为 **83.1%** 与 **94.6%**，已经超过 BM25 的基线。读者在阅读第 5 部分"融合精排"时，可以回到本篇确认这两路候选是如何被合并的。

---

**本篇涉及的源码：** `app/retrieval/vector.py`、`app/retrieval/hybrid.py`、`app/retrieval/cache.py`
