# 04 · Adaptive-RAG 与检索

> 一句话：先路由复杂度，再决定不检索 / 一跳 hybrid / Self-RAG 多跳；BM25 与向量用 RRF 融 **rank** 不融分数。

## 本章目录

1. [论文映射与路由](#论文映射与路由)
2. [检索节点](#检索节点)
3. [Hybrid：一路失败不能拖死另一路](#hybrid一路失败不能拖死另一路)
4. [RRF](#rrf融-rank-不融分数)
5. [Self-RAG 多跳](#self-rag-多跳)
6. [切分与稳定 ID](#切分与稳定-id)
7. [Rerank 与降级](#rerank-与降级)
8. [缓存](#缓存)
9. [评测口径](#评测口径)

对应：`app/retrieval/`、`app/agents/nodes/retrieval.py`、`knowledge/`。

论文：[Adaptive-RAG (Jeong et al., ACL 2024)](https://aclanthology.org/2024.acl-long.123/)。电商额外加 **Agent**、**Refuse**。

## 论文映射与路由

| complexity | strategy | 行为 | `top_k` |
|---|---|---|---|
| simple | `direct` | 问候，不检索 | — |
| single_hop | `single` | 改写 → hybrid → rerank | `RETRIEVAL_TOP_K_SIMPLE`（3） |
| multi_hop | `multi` | Self-RAG：检索 → 打分 → 改写 → 再检索 | `RETRIEVAL_TOP_K_COMPLEX`（8） |
| tool_required | `agent` | Planner + 工具 | 工具内 4 |
| out_of_scope | `refuse` | 边界拒答 | — |

### 要点

LLM 分类失败必须还能路由。规则看意图 + 订单号 + 「同时/过了/但是」这类多跳线索。

### 代码摘要

```python
# app/retrieval/adaptive.py
def rule_based_complexity(query: str, intent: IntentResult) -> ComplexityResult:
    if intent.label == IntentLabel.OUT_OF_SCOPE:
        return ComplexityResult(strategy=RetrievalStrategy.REFUSE, ...)
    if intent.label in {IntentLabel.GREETING, IntentLabel.CHITCHAT}:
        return ComplexityResult(strategy=RetrievalStrategy.DIRECT, ...)
    if intent.label in {ORDER_INQUIRY, LOGISTICS, REFUND, ...} or _ORDER_ID.search(text):
        return ComplexityResult(strategy=RetrievalStrategy.AGENT, ...)
    # 多跳线索 → MULTI；否则 SINGLE
```

`AdaptiveRouter.route()`：先 LLM JSON，捕获 `LLMProviderError` / `LLMOutputError` 后调用上面的规则。

### 为什么

纯 LLM 路由在 Fake/超时下不可测。规则兜底让 `tests/unit/test_adaptive_router.py` 不打网。Agent 优先于 Multi：有订单号时先查系统，而不是先搜政策。

## 检索节点

### 要点

`SINGLE` 与 `MULTI` 共用节点 `retrieve_docs`，用 `state.strategy` 分支，避免两套几乎一样的边。

### 代码摘要

```python
# app/agents/nodes/retrieval.py
async def retrieval_node(state, *, retriever, reranker, rewriter, self_rag, settings):
    top_k = (
        settings.retrieval_top_k_complex
        if strategy == RetrievalStrategy.MULTI
        else settings.retrieval_top_k_simple
    )
    if strategy == RetrievalStrategy.MULTI:
        chunks = await self_rag.retrieve(query, top_k=top_k)
    else:
        rewritten = await rewriter.rewrite(query)
        candidates = await retriever.retrieve(rewritten[0], top_k=top_k)
        chunks = await reranker.rerank(rewritten[0], candidates, top_n=settings.rerank_top_n)
    return {"retrieved_chunks": chunks, "rewritten_queries": rewritten, ...}
```

### 为什么

`top_k` 随复杂度变：简单政策 3 条够用，多约束问题需要更大候选池再 rerank。改写只在 single 路径默认跑；multi 的改写在 Self-RAG 每一跳里做。

## Hybrid：一路失败不能拖死另一路

### 要点

BM25 与向量 **各自 try/except**。两路都空才 `RetrievalError`。未配 embedding 时 hash 向量几乎无语义，但 BM25 仍能独立工作。

### 代码摘要

```python
# app/retrieval/hybrid.py
try:
    lexical = self._bm25.search(query, top_k=top_k)
except Exception as exc:
    lexical_error = exc
try:
    dense = await self._vector.search(query, top_k=top_k)
except Exception as exc:
    dense_error = exc
if not lexical and not dense:
    raise RetrievalError("both lexical and dense retrievers failed")
fused = reciprocal_rank_fusion([lexical, dense], k=self._rrf_k)
return fused[:top_k]
```

### 为什么

Qdrant 抖动不应让客服完全哑火。生产稠密路是本地 **bge-small-zh-v1.5**（双塔召回）；加载失败才 hash。hash 向量 Hit@1 ≈ 3%，硬融会拉低 BM25，**不要把 hash Hybrid 说成语义检索**。精排是同一家族的另一套权重 **bge-reranker-base**（Cross-Encoder），不是把 embedding 模型再打一遍分。

## RRF：融 rank 不融分数

### 要点

BM25 分数与余弦不在同一量纲。RRF：`1 / (k + rank)`，`k=60` 是 Cormack 等默认值，**不是本项目调参结论**。

### 代码摘要

```python
# app/retrieval/fusion.py
def reciprocal_rank_fusion(ranked_lists, *, k=DEFAULT_RRF_K):
    scores: dict[str, float] = {}
    canonical: dict[str, RetrievedChunk] = {}
    for ranked in ranked_lists:
        for rank_position, chunk in enumerate(ranked, start=1):
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (k + rank_position)
            if chunk.chunk_id not in canonical:
                canonical[chunk.chunk_id] = chunk.model_copy(deep=True)
    # 按融合分排序，source="rrf"
```

单测：`tests/unit/test_rrf.py`。

### 为什么

若 `score = 0.5 * bm25 + 0.5 * cosine`，量纲一变（换 embedding）权重就失效。RRF 只看名次，两路地位对等。`chunk_id` 去重：同一段被两路命中只留一条，分数相加。

## Self-RAG 多跳

### 要点

不是特殊 token，是结构化 JSON：`relevant` / `sufficient` / `missing_aspect`。最多 `MAX_RETRIEVAL_HOPS`（默认 3）。够用就 break。

### 代码摘要

```python
# app/retrieval/self_rag.py
class GradeResult(BaseModel):
    relevant: bool
    sufficient: bool
    missing_aspect: str = ""

async def retrieve(self, query, *, top_k):
    accumulated = {}
    for _hop in range(self._settings.max_retrieval_hops):
        rewritten = await self._rewriter.rewrite(current_query, missing_aspect=missing)
        candidates = await self._retriever.retrieve(hop_query, top_k=top_k)
        reranked = await self._reranker.rerank(hop_query, candidates, top_n=...)
        for chunk in reranked:
            accumulated[chunk.chunk_id] = chunk
        grade = await self._grade(query, list(accumulated.values()))
        if grade.sufficient:
            break
        missing = grade.missing_aspect or "more specific policy conditions"
    return list(accumulated.values())[: ...]
```

### 为什么

「定制 + 过了 7 天 + 质量问题」一跳常常只命中退货总则。第二跳用 `missing_aspect` 去搜质量例外。跳数有上限，防止 Agent 在检索上花光预算。

## 切分与稳定 ID

### 要点

生产 ingest 走 Unstructured：PDF / DOCX / PPTX / HTML / 图片 / Markdown 统一 `partition`，再映射成 `RetrievedChunk`。切块之后、embedding 之前做清洗：去不可见字符、NFKC 全角半角、正文硬换行拼接；精确内容哈希去重；近重复只打日志。非 Markdown 来源入库前复用 `mask_pii`。政策 `.md` 不脱敏。`chunk_id` 禁止 uuid4。

`APP_ENV=testing` 或未安装 `.[docs]` 时 **降级** 到 Markdown 标题切分。那不是 Unstructured，不要写进简历。

### 代码摘要

```python
# app/retrieval/cleaning.py
# 切块后：BOM/零宽 → NFKC → 空白；正文可拼 CJK 硬换行；表格不拼。
# 精确 SHA1 去重留第一条；SimHash 近重复只记日志。
# 非 .md 才 mask_pii（电话/身份证/银行卡/订单号）。

def stable_chunk_id(document_id: str, chunk_index: int) -> str:
    return f"{document_id}_{chunk_index:02d}"

def document_id_from_path(path: Path) -> str:
    stem = path.stem.lower().replace(" ", "_")
    digest = hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:8]
    return f"{stem}_{digest}"
```

规模（撰写时）：`knowledge/` **39 篇 Markdown**。类目仍由文件名前缀映射到 `DocumentCategory`。换成 Unstructured 后 chunk 边界可能变，必须重跑 `python -m eval.runner --task retrieval`，不要沿用旧 Hit@1。

### 为什么

uuid4 每次 ingest 全变，引用对不上、Qdrant 无法覆盖旧点。Unstructured 用版面元素代替手写 `##`，才能吃 PDF/扫描件/表格。清洗补的是 OCR/全角/扫描件 PII，不是把「七天」改成「7天」。降级路径保留确定性，让 pytest 不下载 OCR 模型。

## Rerank 与降级

### 要点

生产路径是 **本地 Cross-Encoder**（`CrossEncoderRerankProvider`，默认 `BAAI/bge-reranker-base`）。未安装 `sentence-transformers` 或权重加载失败时才词面 overlap，**那不是 Cross-Encoder，不要写进简历**。

加载成功后：`python -m eval.runner --task retrieval` 应出现 `hybrid+cross-encoder`。

```python
# app/providers/reranker.py
pairs = [(query, document) for document in documents]
scores = await asyncio.to_thread(self._predict, model, pairs)
```

### 为什么

Cross-Encoder 把 query 和 document 拼在一起打分，比双塔/RRF 更适合精排。词面降级只为 CI / 无权重开发不断。pytest 的 `APP_ENV=testing` 不下载模型。

## 缓存

政策 query：TTL 默认 60s（Redis 或内存）。  
query 含订单号或「订单」：**不缓存**（状态会变）。实现：`app/retrieval/cache.py`。

## 评测口径

65 条 / 已加载 `bge-small-zh-v1.5` + Cross-Encoder / 报告 `all_20260822T121308Z.json`（未随仓库分发）：

| 系统 | Precision@1 | Recall@3 | MRR |
|---|---|---|---|
| BM25 | 76.9% | 90% | 0.84 |
| 仅 bge-small | 83.1% | 94.6% | 0.89 |
| BM25 + small + RRF | 83.1% | 94.6% | 0.89 |
| Hybrid + Cross-Encoder | **89.2%** | **97.7%** | **0.94** |

完整表与「能写 / 不能写」见 [10](10-evaluation.md)。从 ingest 到精排的流水线见 [15](15-ingest-and-retrieval.md)。

---

上一章 [03](03-architecture.md) · 下一章 [05 · 智能体](05-agents-and-tools.md)
