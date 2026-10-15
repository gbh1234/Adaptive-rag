# 稀疏召回 BM25

> **本文目标：** 讲清关键词召回的原理与本项目的实现。前两节讲 BM25 的直觉与机制，第三节讲本仓库的代码实现，第四节讲中文分词，最后一节给出反例与练习。

---

## 一、为什么还需要关键词召回

向量检索出现之后，一个自然的想法是：既然向量能表达语义，那是不是只用向量就够了？

真实的客服场景否定了这个想法。

用户问"ORD10001 到哪了"，这里的 `ORD10001` 是一个订单号。它是一个精确的字符串，本身没有"语义"可言。当系统把它送进嵌入模型时，模型会把它压成一个向量；而这个向量与知识库里任何一段文本都不接近，因为订单号不是知识库里的内容。

此时，向量检索给出的结果几乎是随机的，而关键词检索却能一眼认出这个字符串是否出现过。

政策名称也有类似的性质。"七天无理由""包邮""偏远地区"这些词是条款的专有名词，用户很可能原样引用。在这类精确词汇上，关键词召回比语义召回更稳。

两路召回的分工可以对照来看。

| 维度 | BM25（稀疏） | 向量（稠密） |
| --- | --- | --- |
| 匹配依据 | 词面是否命中 | 语义是否相近 |
| 擅长 | 订单号、政策专名、型号 | 口语表达、同义改写 |
| 短板 | 同义改写难命中 | 精确串被"语义化" |
| 本仓库实现 | `rank_bm25` 的 `BM25Okapi` | `bge-small-zh-v1.5` |

> 系统因此保留了一路关键词召回，它与向量召回各司其职。

---

## 二、BM25 的直觉

关键词召回的核心，是给每个切片打一个相关性分数。

最朴素的想法是数词频：查询里的词在某段文本里出现得越多，这段文本就越相关。但单纯的词频有两个毛病。

- **长文本占便宜。** 一段长文本天然包含更多词，它的词频总和必然偏高。
- **常见词占便宜。** 像"的""是""可以"这类词几乎每段都有，它们对相关性没有贡献，却会抬高分数。

**BM25（Best Matching 25）** 正是为修正这两个毛病而设计的，它用两个机制来平衡。

- **词频饱和。** 一个词出现多次之后，它带来的分数增益会递减，不会无限增长。
- **逆文档频率（IDF）。** 一个词如果在越多文档里出现，它的权重就越低；反过来，像订单号这种只在极少数文档里出现的词，它的权重就很高。

> 两个机制合在一起，让 BM25 既能奖励真正匹配的稀有词，又不会让长文本与常见词占便宜。

---

## 三、本项目的实现

`app/retrieval/bm25.py` 中的 `BM25Retriever` 封装了 `rank_bm25` 库的 `BM25Okapi`。它的构建过程很直接。

1. 系统把语料中每个切片的内容分词，用分词结果建立索引。
2. 查询时，系统对查询分词，调用 `get_scores` 得到每个切片的分数。
3. 系统按分数从高到低排序，取前 `top_k` 条。

下面是 `app/retrieval/bm25.py` 中 `BM25Retriever` 的核心代码。

```python
class BM25Retriever:
    """Lexical retriever. Complements dense search on exact policy numbers / SKUs."""

    def build(self, corpus: list[RetrievedChunk]) -> None:
        self._chunks = list(corpus)
        tokenized = [tokenize(chunk.content) for chunk in self._chunks]
        # BM25Okapi requires a non-empty corpus; keep None if ingest has not run.
        self._bm25 = BM25Okapi(tokenized) if tokenized else None

    def search(self, query: str, *, top_k: int) -> list[RetrievedChunk]:
        if self._bm25 is None or not self._chunks:
            return []
        scores = self._bm25.get_scores(tokenize(query))
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
        results: list[RetrievedChunk] = []
        for rank, index in enumerate(ranked, start=1):
            # BM25 IDF can be negative on tiny corpora; still return the ranked docs.
            chunk = self._chunks[index].model_copy(deep=True)
            chunk.score = float(scores[index])
            chunk.rank = rank
            chunk.source = "bm25"
            results.append(chunk)
        return results
```

`build` 负责建立倒排索引，它在语料为空时把 `self._bm25` 置为 `None`，避免 `BM25Okapi` 在空语料上抛错。`search` 先对查询分词，再取分数并按降序排列，最后为每条结果填回 `score`、`rank` 与 `source` 三个字段，供上层融合时区分来源。

这段实现里有一处细节值得留意。代码注释指出，在**小语料**上 BM25 的 IDF 可能为负，此时系统仍然返回排序后的切片，而不做截断。

这是为了在知识库规模很小时也保持可用。读者不应当把"分数为负"误读成"结果不可用"。

---

## 四、中文分词

### 4.1 分词的必要

BM25 建立在词的基础上，它需要先把文本切成词。英文用空格分词，中文没有空格，必须借助分词工具。

本项目在 `app/retrieval/tokenizer.py` 中优先使用 `jieba` 分词。政策里的"7 天""ORD""SKU"这类词主要靠词面匹配，**分词质量直接决定召回质量**。

### 4.2 降级方案

`jieba` 是一个可选依赖，它可能没有安装。为了在这种情况下系统仍然可用，`tokenize` 提供了一个降级方案。

当 `jieba` 不可用时，它对汉字使用**二元切分**，也就是把连续的汉字按每两个字一段切开，同时对英文与数字按单词切分。

这个方案不如真正的分词精确，但它保证了 BM25 始终有一个可用的倒排索引，不会因为缺少分词库而完全失效。

---

## 五、反例与练习

**反例。** 假设系统只保留向量召回，去掉 BM25。用户问"ORD10001 到哪了"，系统把这句话送进嵌入模型，得到一个与订单号几乎无关的向量，检索结果与知识库里任何一段政策都不接近，系统于是召回了若干看似相关、实则无关的政策条款。

用户的问题本应通过订单工具查询，但检索层已经先给出了错误的依据。这个反例说明：**关键词召回在精确词汇上不可替代。**

**练习一：观察 IDF 的作用。** 读者取一个只在少数文档出现的词，与一个在多数文档出现的词，比较它们对同一段文本分数的贡献。

**练习二：判断分词效果。** 读者对"满减券能不能叠加"这句话，分别用 `jieba` 与二元切分处理，比较两种结果的差异。

> **指标回指。** 本篇对应第 11 部分"评测体系"中的检索 Precision@1 与 Recall@3。仅使用 BM25 时，这两项分别为 **76.9%** 与 **90.0%**，它是本项目消融实验的基线。读者在阅读第 5 部分"融合精排"时，可以回到本篇，确认这条基线是如何被超越的。

---

**本篇涉及的源码：** `app/retrieval/bm25.py`、`app/retrieval/tokenizer.py`
