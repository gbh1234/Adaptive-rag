# RRF 融合

> 本文是第五部分的第一篇正文，它讲清两路候选如何合并。

全文分为五节。前两节讲为什么不能直接加分数，中间两节讲 RRF 的公式与实现，最后一节给出反例与练习。

---

## 一、两路候选为什么需要合并

系统从第 4 部分拿到两批候选：一批来自 BM25，一批来自向量检索。这两批候选各自排好序，但它们不能简单拼接，因为系统最终只需要一个列表。

系统必须回答一个问题：如果一段切片同时被两路召回，而另一段只被一路召回，谁应当排在前面。

最直观的想法是把两路的分数加权相加，例如给 BM25 与向量各一半权重。这个想法看起来合理，实际却行不通。

> 加权求和行不通的根本原因在于，两路的分数不在同一个量纲上。

---

## 二、为什么不能直接加分数

BM25 的分数没有上界。它由词频与逆文档频率计算而来，理论上可以取到任意大的值；在本项目的小语料上，它甚至可能为负。

而向量相似度是有界的，它在 **-1 到 1** 之间。

把两个量纲不同的分数直接相加，等于把一个没有刻度的量和一个有刻度的量混在一起，加出来的结果没有明确含义。

更麻烦的是，量纲会随配置漂移。如果系统换一个嵌入模型，向量相似度的分布就会改变，原来调好的权重随之失效。

> 这意味着"加权求和"方案在换模型时必须重新调参，而调参依赖人工经验，既不稳健也不可复现。系统因此需要一个不依赖分数刻度、只依赖排序位置的融合方式。

两种思路可以对照来看。

| 维度 | 加权求和 | RRF |
| --- | --- | --- |
| 依据 | 分数 | 名次 |
| 量纲要求 | 两路须同量纲 | 无要求 |
| 换模型 | 需重新调参 | 不受影响 |
| 可复现性 | 依赖人工经验 | 稳健可复现 |

---

## 三、RRF 的做法

### 3.1 公式

**RRF（Reciprocal Rank Fusion，倒数排名融合）** 的核心思想是：忽略分数，只看名次。

它的公式是 `score(d) = sum_i 1 / (k + rank_i(d))`，其中 `rank_i(d)` 是切片 `d` 在第 `i` 路结果中的名次，`k` 是一个常数。

这个公式有两个特点。

- **对名次敏感、对分数不敏感。** 无论 BM25 的分数是 30 还是 300，只要它排第一，贡献就相同。
- **对靠前的名次更敏感。** 排第一的贡献是 `1/(k+1)`，排第十的贡献是 `1/(k+10)`，前者明显大于后者。

> 系统因此既避免了量纲问题，又保留了"排名越靠前越重要"的直觉。

### 3.2 常数 k 的作用与来历

公式里的常数 `k` 用来抑制名次差异。`k` 越大，不同名次之间的贡献差距越小；`k` 越小，靠前名次的优势越突出。

本项目取 `k = 60`，这个取值来自 RRF 原始论文作者 Cormack 等人的默认设定。

这里有一条必须讲清的边界：`k = 60` 是一个沿用的默认值，**不是**本项目调参得到的结论。

> 读者在面试中不应当把它说成"我们调出来的最优参数"。

---

## 四、本项目的实现

`app/retrieval/fusion.py` 中的 `reciprocal_rank_fusion` 接收若干已排序的候选列表，对每个列表按名次累加 `1 / (k + rank)`，得到每个切片的融合分，再按融合分从高到低排序。

`app/retrieval/fusion.py` —— `reciprocal_rank_fusion`

```python
"""Reciprocal Rank Fusion.

RRF(d) = sum_i 1 / (k + rank_i(d))

k=60 is the original Cormack, Clarke, Buettcher default. We use rank rather
than raw scores because BM25 and cosine are not on the same scale.
Duplicate chunk_ids are merged; first-seen metadata wins, scores are fused.
"""

# ...

def reciprocal_rank_fusion(
    ranked_lists: list[list[RetrievedChunk]],
    *,
    k: int = DEFAULT_RRF_K,
) -> list[RetrievedChunk]:
    if k <= 0:
        raise ValueError("RRF k must be positive")
    scores: dict[str, float] = {}
    canonical: dict[str, RetrievedChunk] = {}
    for ranked in ranked_lists:
        for rank_position, chunk in enumerate(ranked, start=1):
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (k + rank_position)
            if chunk.chunk_id not in canonical:
                canonical[chunk.chunk_id] = chunk.model_copy(deep=True)
    fused = []
    for chunk_id, score in sorted(scores.items(), key=lambda item: item[1], reverse=True):
        chunk = canonical[chunk_id]
        chunk.score = score
        chunk.source = "rrf"
        fused.append(chunk)
    for index, chunk in enumerate(fused, start=1):
        chunk.rank = index
    return fused
```

`reciprocal_rank_fusion` 先对每一路按名次累加 `1.0 / (k + rank_position)`，同一个 `chunk_id` 的分数因此叠加。它用 `canonical` 只保留每个切片第一次出现的副本，随后按融合分降序写出结果，并把 `source` 标为 `rrf`、按序重写 `rank`。

代码里有一处细节值得留意：它用一个 `canonical` 字典保存每个 `chunk_id` 第一次出现时的切片对象。当同一个切片被两路同时召回时，系统只保留一条，但融合分累加。

> 两路都命中的切片会获得更高的融合分，这是 RRF 奖励"多路共识"的体现。

融合之后，系统在 `app/retrieval/hybrid.py` 中截取前 `top_k` 条返回。`HybridRetriever` 在调用融合之前，已经完成了"两路独立失败"的容错，这一点在上一部分讲过。

---

## 五、反例与练习

这里有一个必须主动澄清的反例。很多人会想当然地认为"RRF 一定优于单路召回"，但本项目的实测给出了相反的结论。

在 **65 条**政策问句的评测集上，BM25 加向量再加 RRF 的成绩，与仅使用向量召回的成绩完全相同。

| 方案 | Precision@1 | Recall@3 |
| --- | --- | --- |
| 仅向量召回 | **83.1%** | **94.6%** |
| BM25 + 向量 + RRF | **83.1%** | **94.6%** |

真正带来提升的是随后的 Cross-Encoder 精排。

> RRF 的价值在于提供一个稳健、可复现的合并方式，而不是保证涨点。读者在简历与面试中，不应当把 RRF 写成"融合一定涨点"。

本部分的练习有两项。

- **手算融合。** 读者应取两路各三条候选，按 `k = 60` 计算融合分，排出合并后的顺序。
- **解释设计。** 读者应说明为什么 RRF 只看名次而不看分数，这样做规避了什么问题。

本篇对应的指标是第 11 部分"评测体系"中的检索 Precision@1 与 MRR。融合本身在本评测集上不带来额外增益，它的作用是为精排准备一个统一的候选列表。读者在阅读下一篇时，可以对照理解增益究竟来自哪一步。

---

**本篇涉及的源码：** `app/retrieval/fusion.py`、`app/retrieval/hybrid.py`
