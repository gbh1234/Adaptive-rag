# 15 · 解析、切块、向量化与检索

> 一句话：启动全量 ingest 把政策变成带稳定 ID 的 chunk；问答时 Adaptive 决定是否检索，Hybrid 融 rank，Cross-Encoder 精排。

## 本章目录

1. [总览](#总览)
2. [文档解析与预处理](#文档解析与预处理)
3. [文档分块策略](#文档分块策略)
4. [向量化](#向量化)
5. [向量数据库](#向量数据库)
6. [检索策略](#检索策略)
7. [重排序](#重排序)
8. [评测口径](#评测口径)

对应：`app/retrieval/`、`app/providers/embeddings.py`、`app/providers/reranker.py`、`knowledge/`。

对应的 Agent/RAG 面试问题已按 [zero2Agent 面试通关目录](https://github.com/ranxi2001/zero2Agent/tree/main/learn-agent-interview) 的维度整理到 [项目面试地图](16-interview-bagu-map.md)；本章聚焦实际解析与检索链路。

路由、Self-RAG、Agent 细节见 [04](04-adaptive-rag.md)。数字只引用 [`eval/MEASURED.md`](../eval/MEASURED.md)。

```text
knowledge/*
  → parse_path（Unstructured；缺依赖 / testing 则 Markdown 标题切分）
  → normalize + 非 .md 才 mask_pii
  → 精确 SHA1 去重（近重复只打日志）
  → embed → BM25 索引 + 向量 upsert

query
  → Adaptive（可不检索）
  → 改写 → BM25 ∥ 向量 → RRF
  → Cross-Encoder rerank
  → 生成 / 忠实度
```

启动：`build_container` → `ingest_knowledge`。改 `knowledge/` 后重启 API。无 CMS、无增量删除。

---

## 文档解析与预处理

### 要点

生产路径用开源 Unstructured `partition`，按文件类型分流。支持 `.md` `.pdf` `.docx` `.pptx` `.html` 与常见图片。类目仍按**文件名前缀**映射到 `DocumentCategory`，解析器不负责分类。

Unstructured 在 extra `.[docs]` 里，**不进主依赖**。`APP_ENV=testing` 或未安装 extra：`.md` 走 `chunk_markdown`，其它格式跳过。那不是 OCR，不要写进简历。

切块之后、embedding 之前清洗：

| 步骤 | 行为 |
|---|---|
| 编码 | Markdown `utf-8-sig`（去 BOM） |
| 不可见字符 | 零宽、软连字符、除 `\n\t` 外的控制符 |
| 全角 | NFKC（`７天` → `7天`）；**不**把「七天」改成「7天」 |
| 空白 | 行内空白压成单空格；连续空行最多两个 |
| 硬换行 | 仅正文：汉字被单换行切开则拼回；**表格不拼** |
| PII | 复用 `mask_pii`；**仅非 .md**。政策文里的「身份证」是规则，不是用户号码 |
| 去重 | 相同正文 SHA1 留第一条，不改 `chunk_id`；跨文档 SimHash 近重复只记日志 |

日志脱敏是另一层（`ContextFilter`），不能当成知识库已脱敏。

### 代码摘要

```python
# app/retrieval/unstructured_parser.py
# Title → section；NarrativeText/ListItem 聚块；Table 整块；空图跳过
# Header/Footer/PageBreak 丢弃。PDF/图片 strategy=auto，OCR chi_sim+eng。

# app/retrieval/cleaning.py
def normalize_text(text, *, join_hard_breaks=True): ...
def dedupe_chunks(chunks):  # 精确丢弃；近重复 logger.info
```

系统包：poppler、tesseract（`chi_sim`）、Office 还需 libreoffice。不接 Unstructured Cloud。

### 为什么

政策语料本是人工 Markdown，标题切就够用。接 Unstructured 是为了运营丢来的 PDF/扫描件，而不是替换已经干净的 `.md`。清洗补 OCR 全角和硬换行；近重复不丢块，是因为总则和品类例外本来就该同时可召回。

---

## 文档分块策略

### 要点

两层切，不是语义自适应切分：

1. **按结构分段**：Unstructured 用 `Title` 当 `section`；Markdown 降级用 `#{1,3}`。
2. **段内滑窗**：`MAX_CHUNK_CHARS=500`，`OVERLAP_CHARS=60`。表格单独成块，禁止滑窗切碎。

`chunk_id` 禁止 uuid4：`{document_id}_{两位序号}`。`document_id` = `{stem}_{路径 SHA1 前 8 位}`。citation、Qdrant upsert、评测金标都靠它。评测按 stem 匹配（`return_policy`），不按 chunk 序号。

规模（撰写时）：`knowledge/` **39 篇 Markdown**。换成 Unstructured 后边界可能变，必须重跑 `--task retrieval`。

每个 chunk 带：`title`、`section`、`category`、`policy_version`、`metadata.parser` / `element_type` / `page_number`。

### 代码摘要

```python
# app/retrieval/chunking.py
MAX_CHUNK_CHARS, OVERLAP_CHARS = 500, 60

def stable_chunk_id(document_id: str, chunk_index: int) -> str:
    return f"{document_id}_{chunk_index:02d}"

def document_id_from_path(path: Path) -> str:
    stem = path.stem.lower().replace(" ", "_")
    digest = hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:8]
    return f"{stem}_{digest}"
```

Qdrant point id：`chunk_id` 的 MD5 派生成 UUID（`stable_point_id`）。重 ingest 覆盖同一点。

### 为什么

政策条款按标题写，「7 天无理由」和「定制商品」不该挤在一块。500/60 避免一篇塞进一个 chunk。uuid4 每次 ingest 全变，引用和评测都会断。

---

## 向量化

### 要点

对 **chunk 正文** 做 embedding，L2 归一化。查询侧用同一套模型。优先级：

1. 配了 `EMBEDDING_API_KEY` + `BASE_URL` → 远程 OpenAI 兼容接口
2. 否则本地双塔 **`BAAI/bge-small-zh-v1.5`**（512 维）
3. 加载失败或 `APP_ENV=testing` → **hash 向量**（CI 占位，几乎无语义）

Hash 向量 Hit@1 约 3%，**不要把 hash Hybrid 说成语义检索**。也不是 bge-m3。

BM25 是另一路：jieba 分词；没装 jieba 时汉字 bigram + 英文数字。政策里的「7 天」「ORD」「SKU」主要靠词面。

### 代码摘要

```python
# app/providers/embeddings.py
def build_embedding_provider(settings, *, model=None):
    if settings.embedding_configured:
        return OpenAICompatibleEmbeddingProvider(settings)
    local = BgeM3EmbeddingProvider(settings, model=model)  # 默认小模型，类名历史遗留
    if local.available:
        return local
    return HashEmbeddingProvider(dim=settings.embedding_dim)
```

`KnowledgeIngestor.load`：去重后 `embed([chunk.content for chunk in chunks])`，再 `build_records`。

### 为什么

客服政策短、中文条款多。small 在 65 条上仅向量 P@1 已到 83.1%。测试禁止下载权重，所以必须有 hash 降级，但降级路径不能写进简历。

---

## 向量数据库

### 要点

`QDRANT_URL` 非空则用 Qdrant，集合默认 `cs_knowledge`，距离 **COSINE**，维度必须与 embedding 一致（本地 small 是 512）。

Qdrant 连不上或启动失败 → **内存库** `InMemoryVectorStore`，进程内 brute-force 余弦。BM25 仍独立工作。

写入是 upsert：同一 `chunk_id` 覆盖。没有删除 API，全量启动 ingest。

Payload 带 `chunk_id` / `document_id` / `title` / `content` / `section` / `chunk_index` / `policy_version`，检索结果还原成 `RetrievedChunk`。

### 代码摘要

```python
# app/retrieval/ingest.py
if qdrant_url:
    store = QdrantVectorStore(qdrant_url, qdrant_collection, embedding_dim)
    try:
        await asyncio.to_thread(store.ensure_collection)
        await asyncio.to_thread(store.upsert, records)
        return bm25, store, chunks
    except Exception:
        logger.warning("qdrant_ingest_failed_using_memory")
# 内存库兜底
```

没有 Elasticsearch。当前 39 篇规模，内存 BM25 + 可选 Qdrant 够用。

### 为什么

Qdrant 可独立扩、point id 稳定。本地开发 / CI 不强制 Docker。向量挂了不能让客服完全哑火，所以 BM25 与内存库是一等公民，不是「演示开关」。

---

## 检索策略

### 要点

不是每个问题都检索。Adaptive 先定策略：

| complexity | strategy | 检索 |
|---|---|---|
| simple | `direct` | 无 |
| single_hop | `single` | 改写 → Hybrid → rerank，`top_k=3` |
| multi_hop | `multi` | Self-RAG 最多 3 跳，`top_k=8` |
| tool_required | `agent` | 工具；政策靠 `search_knowledge` |
| out_of_scope | `refuse` | 无 |

LLM 路由失败走规则（意图、订单号、多跳线索）。有订单号时 **Agent 优先于 Multi**：先查系统，不先搜政策。

**Hybrid**：BM25 与向量 **各自 try/except**。两路都空才 `RetrievalError`。融合是 RRF：`1/(k+rank)`，`k=60` 是 Cormack 等默认值，**不是本仓库调参结论**。BM25 分数和余弦不能直接加。同一 `chunk_id` 只留一条。

Single 路径默认 query rewrite（最多 3 条，失败用原句）。Multi 的改写在 Self-RAG 每跳里，用 `missing_aspect`。

缓存：政策 query TTL 60s；含 `ORD` 或「订单」**不缓存**。

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
```

```python
# app/agents/nodes/retrieval.py
if strategy == RetrievalStrategy.MULTI:
    chunks = await self_rag.retrieve(query, top_k=top_k)
else:
    rewritten = await rewriter.rewrite(query)
    candidates = await retriever.retrieve(rewritten[0], top_k=top_k)
    chunks = await reranker.rerank(rewritten[0], candidates, top_n=settings.rerank_top_n)
```

### 为什么

问候打向量浪费延迟和幻觉空间。「7 天」这类条款 BM25 更稳；近义问法靠稠密路。RRF 只看名次，换 embedding 不用重调加权重。本 65 条上 RRF 与仅 small 数字相同，**不要写「RRF 一定优于单路」**。

---

## 重排序

### 要点

召回之后用 **本地 Cross-Encoder** `BAAI/bge-reranker-base`：query 和 document **拼在一起**打分，不是把 embedding 模型再打一遍。默认 `rerank_top_n=5`。

未装 `.[rerank]`、权重加载失败、或 testing 未 `CROSS_ENCODER_FORCE` → 词面 overlap。**那不是 Cross-Encoder**。

加载成功后，`python -m eval.runner --task retrieval` 应出现 `hybrid+cross-encoder`。

### 代码摘要

```python
# app/providers/reranker.py
pairs = [(query, document) for document in documents]
scores = await asyncio.to_thread(self._predict, model, pairs)

# app/retrieval/reranker.py
# 按 provider 返回的 (原下标, score) 重排 RetrievedChunk，source="rerank"
```

### 为什么

RRF 只能说「两路都排得靠前」，不能判断「这段是否真回答了这个问题」。Cross-Encoder 吃完整 query+chunk，适合近义政策。65 条上 Hybrid+CE：**P@1 89.2% / R@3 97.7% / MRR 0.94**，相对纯 BM25 +12.3 / +7.7 个百分点；相对 RRF 的增益来自 CE，不是来自再融一次分。

---

## 评测口径

65 条 / 39 篇 / 已加载 small + Cross-Encoder / 报告 `all_20260822T121308Z.json`（未随仓库分发）：

| 系统 | Precision@1 | Recall@3 | MRR |
|---|---|---|---|
| BM25 | 76.9% | 90% | 0.84 |
| 仅 bge-small | 83.1% | 94.6% | 0.89 |
| BM25 + small + RRF | 83.1% | 94.6% | 0.89 |
| Hybrid + Cross-Encoder | **89.2%** | **97.7%** | **0.94** |

改 Prompt、切分、解析器或知识库后必须重跑 `--task retrieval`，再改 `MEASURED.md`。完整消融见 [10](10-evaluation.md)、[14](14-evaluation-report.md)。

---

上一章 [14](14-evaluation-report.md) · [返回目录](README.md)
