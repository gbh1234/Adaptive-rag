# Adaptive-RAG、切分索引、改写、Hybrid 与多跳

> 对应简历句：**检索阶段：FAQ、退货策略、配送说明等文档进行预处理、切分、向量化索引。基于 Adaptive-RAG 实现科学感知的逻辑路由，动态调度检索策略，并通过问题改写和混合检索，解决多跳问题。**
>
> 用法：每个问题先给 **30 秒开口**，再给对照仓库的详细答案。数字只引用 [`eval/MEASURED.md`](../../eval/MEASURED.md)（2026-08-22）。行为只写代码里真实存在的；没做的会标明。
>
> **用词：** 「科学感知」对应论文里的 **query complexity-aware**（按问题复杂度选策略），不是「感知科学领域」。答辩时主动改口。
>
> 正文先读 [Chapter 2 · 检索证据](chapter2.md)。配套：[04 Adaptive-RAG](../04-adaptive-rag.md) · [15 解析切块](../15-ingest-and-retrieval.md) · [10 评测](../10-evaluation.md) · [14 测评报告](../14-evaluation-report.md)。

## 本章目录

1. [预处理、切分、向量化索引](#1-预处理切分向量化索引)
2. [Adaptive-RAG 与复杂度路由](#2-adaptive-rag-与复杂度路由)
3. [问题改写](#3-问题改写)
4. [混合检索 Hybrid](#4-混合检索-hybrid)
5. [多跳 Self-RAG](#5-多跳-self-rag)
6. [数字与评测](#6-数字与评测)
7. [跨模块综合](#7-跨模块综合)
8. [面试官在验证什么](#8-面试官在验证什么)

---

## 1. 预处理、切分、向量化索引

### 1.1 离线 ingest 和在线检索各做什么？改了知识库要不要重启？有没有增量更新？

**开口：** 启动时全量 ingest：解析 → 清洗 → 切块 → embed → 建 BM25 + 向量索引。问答时 Adaptive 决定是否检索，再改写 / Hybrid / 精排。改 `knowledge/` 要重启 API。没有 CMS，没有增量删除。

**详细答案：**

离线（进程启动，`build_container` → `ingest_knowledge`）：

```text
knowledge/*
  → parse_path（Unstructured；缺依赖 / testing 则 Markdown 标题切分）
  → normalize；非 .md 才 mask_pii
  → 精确 SHA1 去重（近重复只打日志）
  → embed → BM25 索引 + 向量 upsert
```

在线（一次请求里，且 `strategy` 为 SINGLE / MULTI 时才进 `retrieve_docs`）：

```text
query → Adaptive（可不检索）→ 改写 → BM25 ∥ 向量 → RRF → Cross-Encoder → 生成 / 忠实度
```

`docs/12-limitations.md`：启动全量 ingest，无删除 API。面试不要说「热更新知识库」。

---

### 1.2 FAQ / 退货 / 配送是怎么进库的？类目按文件名还是模型分类？

**开口：** 文件扔进 `knowledge/`，类目按**文件名前缀**映射到 `DocumentCategory`，解析器不负责分类。

**详细答案：**

`category_for_stem`（`app/retrieval/ingest.py`）最长前缀优先，例如 `return_` → 退货政策，`shipping` / `logistics` → 配送，未知 stem 回落 `FAQ`。撰写时约 **39 篇 Markdown**。类目用于过滤和展示，检索主路径仍是全文 BM25 + 向量，不是先选类目再搜。

---

### 1.3 解析用了什么？PDF 和 `.md` 是不是同一条路径？testing 降级成什么？

**开口：** 生产用 Unstructured `partition`，按类型分流。testing 或没装 `.[docs]` 时，`.md` 走标题切分，其它格式跳过。那不是 OCR，不要写进简历。

**详细答案：**

生产：`.md` `.pdf` `.docx` `.pptx` `.html` 与常见图片。Title → section；NarrativeText/ListItem 聚块；Table 整块；Header/Footer/PageBreak 丢弃。PDF/图片 `strategy=auto`，OCR `chi_sim+eng`。需要 poppler、tesseract、Office 还要 libreoffice。不接 Unstructured Cloud。

政策语料本是人工 Markdown，标题切就够用。接 Unstructured 是为了运营丢来的 PDF/扫描件，不是替换已经干净的 `.md`。

---

### 1.4 预处理洗了什么？「七天」会不会变成「7天」？政策里的「身份证」会不会被 mask？

**开口：** 去 BOM/零宽/控制符，NFKC 把 `７天` 变成 `7天`，**不**把汉字「七天」改成「7天」。PII 只 mask **非 .md**。政策文里的「身份证」是规则，要留给检索。

**详细答案：**

| 步骤 | 行为 |
|---|---|
| 编码 | Markdown `utf-8-sig` |
| 不可见字符 | 零宽、软连字符、除 `\n\t` 外的控制符 |
| 全角 | NFKC；中文数字不动 |
| 空白 | 行内压成单空格；连续空行最多两个 |
| 硬换行 | 仅正文：汉字被单换行切开则拼回；**表格不拼** |
| PII | 复用 `mask_pii`；**仅非 .md** |
| 去重 | 相同正文 SHA1 留第一条，不改 `chunk_id`；跨文档 SimHash 近重复只记日志 |

日志脱敏（`ContextFilter`）是另一层，不能当成知识库已脱敏。代码：`app/retrieval/cleaning.py`。

---

### 1.5 切分策略？chunk 多大、overlap？表格怎么切？

**开口：** 两层切，不是语义自适应：先按标题分段，段内滑窗 **500 字 / overlap 60**。表格单独成块，禁止滑窗切碎。

**详细答案：**

1. 结构：Unstructured 用 `Title`；Markdown 降级用 `#{1,3}`。
2. 段内：`MAX_CHUNK_CHARS=500`，`OVERLAP_CHARS=60`（`app/retrieval/chunking.py`）。

政策按标题写，「7 天无理由」和「定制商品」不该挤在一块。500/60 避免一篇塞进一个 chunk。切太大：无关条款进上下文，幻觉和稀释；切太碎：一条规则裂成两截，单跳召不齐，这正是后面 Self-RAG 要补的。

**没有** embedding 聚类语义切分。不要说成 Parent-Child 或 late chunking。

---

### 1.6 `chunk_id` / `document_id` 怎么生成？为什么要稳定 ID？

**开口：** `document_id = {stem}_{路径 SHA1 前 8 位}`，`chunk_id = {document_id}_{两位序号}`。禁止 uuid4。引用、Qdrant upsert、评测金标都靠它。

**详细答案：**

```python
# app/retrieval/chunking.py
def stable_chunk_id(document_id: str, chunk_index: int) -> str:
    return f"{document_id}_{chunk_index:02d}"

def document_id_from_path(path: Path) -> str:
    stem = path.stem.lower().replace(" ", "_")
    digest = hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:8]
    return f"{stem}_{digest}"
```

Qdrant point id：`chunk_id` 的 MD5 派生成 UUID，重 ingest **覆盖同一点**。uuid4 每次全变，citation 对不上、评测也对不上。

评测金标是文档 **stem**（如 `return_policy`），不是 chunk 序号：`document_id.rsplit("_", 1)[0]` 去掉 digest 再比。同一篇政策的多个切片只计一次。

改一句文案：该 chunk 向量变，id 序号一般不变（仍按切分顺序）。改切分边界或增删标题，后面序号会漂移，必须重跑 `--task retrieval`。

---

### 1.7 精确去重和近重复分别怎么处理？为什么近重复不丢？

**开口：** 正文 SHA1 相同只留第一条。SimHash 近重复只打日志。总则和品类例外本来就该同时可召回。

**详细答案：**

精确去重不改 `chunk_id`（留给第一条）。若把近重复当重复丢掉，可能只留下总则「7 天可退」，丢掉「定制不可退」，单跳看起来召回很好，答案却是错的。面试用这个例子说明「去重不是越狠越好」。

---

### 1.8 向量化用哪个模型、几维？加载失败走什么？hash 还能叫语义检索吗？

**开口：** 生产本地 **`BAAI/bge-small-zh-v1.5`，512 维**，L2 归一化。失败或 testing 走 hash 占位。Hash 仅向量 Hit@1 约 **3.1%**，不能写成语义检索，也不是 bge-m3。

**详细答案：**

优先级（`app/providers/embeddings.py`）：

1. 配了 `EMBEDDING_API_KEY` + `BASE_URL` → 远程 OpenAI 兼容
2. 否则本地双塔 `bge-small-zh-v1.5`
3. 加载失败或 `APP_ENV=testing` → `HashEmbeddingProvider`

类名里可能残留 `BgeM3EmbeddingProvider`，**默认权重是 small**。简历写 m3 会被对质。

只对 **chunk 正文** embed，query 侧同一套模型。BM25 是另一路：jieba；没装则汉字 bigram + 英文数字。「7 天」「ORD」「SKU」主要靠词面。

---

### 1.9 向量库？BM25 何时重建？和向量是不是同一批 chunk？

**开口：** 有 `QDRANT_URL` 用 Qdrant（集合默认 `cs_knowledge`，COSINE，维度必须 512）；否则内存库。BM25 与向量 **同一批 ingest 后的 chunks**，启动时一起建。

**详细答案：**

`KnowledgeIngestor.load` 去重后 embed，再 `BM25Retriever(chunks)` + `upsert`。不是「向量一份、BM25 另一份过期语料」。Qdrant 5s 超时；sync 包 `asyncio.to_thread`。

---

### 1.10 Embedding 要不要 instruction prefix？中英要不要分模型？

**开口：** 本仓库 **没有** BGE instruction prefix，也没有中英双塔。small 在 65 条中文政策上仅向量 P@1 已到 83.1%。被问「为什么不加 prefix」：客服短句、语料单一，先保证能加载、能评测。

**详细答案：** 没做的不要补编。若加 prefix，query 侧和文档侧必须成对，否则相似度系统性偏。换模型必须重 ingest。

---

### 1.11 追问：切太大 / 切太碎会怎样？「7 天」和「定制不可退」被切到两块？

**开口：** 太大稀释、乱引用；太碎单跳漏条件。这正是 overlap、标题切、以及多跳用 `missing_aspect` 再搜的原因。

**详细答案：**

退货总则一块、定制例外一块，是政策文档的正常结构。单跳 Hybrid 可能只命中总则。Self-RAG 裁判 `sufficient=false`，`missing_aspect` 类似「定制商品是否适用七天」，第二跳再搜。单跳路径没有这个循环，所以路由器要把「定制 + 过了 7 天」这类标成 MULTI。

---

## 2. Adaptive-RAG 与复杂度路由

### 2.1 原论文解决什么？和 Naive RAG、Self-RAG 差在哪？

**开口：** Adaptive-RAG（Jeong et al., ACL 2024）按 **问题复杂度** 选检索深度：简单不检索或一跳，复杂才多跳。Naive 每问都一跳；Self-RAG 偏「检索后反思是否再跳」。我们把论文三档映射成五路，并加了电商的 Agent / Refuse。

**详细答案：**

| | Naive RAG | Self-RAG | Adaptive-RAG（本仓库） |
|---|---|---|---|
| 是否检索 | 永远检索 | 模型决定 retrieve / 再 hop | **先路由再决定** |
| 多跳 | 无 | 检索→打分→再跳 | 仅 `strategy=MULTI` 才进 Self-RAG 循环 |
| 工具 / 拒答 | 无 | 无 | 电商加的 AGENT / REFUSE |

不要说「我们实现了整篇论文的全部实验」。实现的是 **复杂度路由思想** + 自研 Hybrid / HITL。

---

### 2.2 「科学感知」指什么？复杂度有哪几档？

**开口：** 就是 **感知问题复杂度**。五档 complexity 映射五路 strategy。

**详细答案：**

| complexity | strategy | 行为 | top_k |
|---|---|---|---|
| simple | `direct` | 问候，不检索 | — |
| single_hop | `single` | 改写 → hybrid → rerank | 3 |
| multi_hop | `multi` | Self-RAG | 8 |
| tool_required | `agent` | Planner + 工具 | 工具内 4 |
| out_of_scope | `refuse` | 拒答 | — |

Prompt：`app/prompts/complexity.py`。枚举：`app/core/enums.py`。

---

### 2.3 Agent、Refuse 是论文有的还是电商加的？

**开口：** **电商加的。** 论文面向问答检索；客服还有查订单和越权注入，不能硬塞进 single/multi。

**详细答案：** `adaptive.py` 文件头注释写明了映射，并写 tool needs → AGENT。面试主动说「论文 + 两路业务扩展」，比假装论文里就有 Agent 更稳。

---

### 2.4 谁做路由？意图错了策略会不会跟着错？

**开口：** **复杂度节点** `route_complexity`，不是意图节点。意图是特征（prompt 里会带上）。意图错了，规则路由器可能把退款打成 AGENT（还算安全），也可能把政策打成退换货再进 Agent。

**详细答案：**

`AdaptiveRouter.route(query, intent)`：先 LLM JSON；挂了用 `rule_based_complexity`。规则：**越权 REFUSE；问候 DIRECT；订单/退款/物流等或订单号 → AGENT（优先于 Multi）**；句子里有「同时/过了/如果」且足够长 → MULTI；默认 SINGLE。

意图只是输入之一。LLM 路由器看到 `intent=faq_policy` 仍可因多条件选 MULTI。规则路径对事务意图直接 AGENT，所以「退款政策怎么算」若被标成 `refund`，规则会进 Agent 而不是检索——这是可承认的错分代价，覆盖层 / 意图 v3 在减这类错。

---

### 2.5 LLM 路由挂了怎么办？规则看哪些信号？

**开口：** `LLMProviderError` / `LLMOutputError` 落到规则。看意图、订单号、工具 cue、多跳 cue。单测 `tests/unit/test_adaptive_router.py` 不打网。

**详细答案：**

多跳 cue：`同时、并且、还是、如果、但是已经、过了、既、又` 以及英文 `and then`。规则还要求 `len(text) > 18`，避免短句误触发。工具 cue：订单、物流、退款进度、取消订单等。有订单号则 AGENT，**先查系统，不要先搜政策**。

---

### 2.6 为什么有订单号优先 Agent？为什么问候不检索？

**开口：** 订单状态在 DB 里，政策库里没有「ORD10001 到哪了」。问候检索浪费延迟、钱，还把无关 chunk 塞进生成。

**详细答案：** 这是 Adaptive 相对玩具 RAG 的第一刀。面试第一句若被问「所有问题都做一次向量检索吗」，答案必须是 **否**。

---

### 2.7 `SINGLE` 和 `MULTI` 为什么共用 `retrieve_docs`？top_k 为什么不同？

**开口：** 避免两套几乎一样的边。节点内部看 `state.strategy` 分支。单跳 top_k=3、精排 top_n=5；多跳召回 8、最多 3 hop， hop 间按 chunk_id 去重累积。

**详细答案：** 图更清晰，SSE 仍是一个 `retrieve_docs` 节点。代价：看日志时要靠 `strategy` 区分是一跳还是 Self-RAG。设置：`retrieval_top_k_simple=3`，`retrieval_top_k_complex=8`，`rerank_top_n=5`，`max_retrieval_hops=3`。

---

### 2.8 追问：这是「动态调度」还是「先分类再走死边」？第一跳差会不会改策略？

**开口：** **先分类再走死边。** 进了 SINGLE 不会中途改成 MULTI。MULTI **内部** 可以再 hop，那是 Self-RAG，不是改 `strategy`。

**详细答案：** 图上 `route_complexity` 之后条件边写死。没有「召回太差回流路由器」。动态指 **不同请求不同策略**，不是 **同一次请求自适应改道**。被追问就承认：这是实现复杂度，换策略要再跑 LLM 路由，延迟更高。

---

## 3. 问题改写

### 3.1 改写发生在哪？改写几句？用哪句去搜？

**开口：** 检索节点里、Hybrid **之前**。LLM 出 1–3 条，**只用第一条** `rewritten[0]`。失败回原句。

**详细答案：**

`QueryRewriter.rewrite`（`app/retrieval/query_rewrite.py`）：`temperature=0`，JSON `{"queries":[...]}`，最多留 3 条。`retrieval_node` 单跳：`retriever.retrieve(rewritten[0])`。Self-RAG 每一跳也是 `rewritten[0]`。

**没有** 多路改写再融合（没有把 3 条都拿去 Hybrid 再 RRF）。Prompt 让模型保留时效、品类、是否定制、是否质量问题（`app/prompts/query_rewrite.py`）。

---

### 3.2 改写解决什么？失败怎么办？会不会改歪？

**开口：** 口语和缺省（「还能退吗」→ 带上 7 天/品类约束）。LLM 挂了用原句。过宽改写会召回总则、漏品类例外，所以 prompt 强调保留约束；多跳再用 `missing_aspect` 补。

**详细答案：** 改写发生在路由 **之后**，不会把问候改成政策再去搜——问候根本不进检索节点。Agent 路径默认也不走这个 rewriter（见 7.5）。

---

### 3.3 多跳时每一跳都改写吗？`missing_aspect` 怎么变成下一跳 query？

**开口：** 是。裁判不足则 `missing` 传入 rewriter；`current_query` 回到 **原始问题**，不是在上一跳改写句上叠改。

**详细答案：** `SelfRAGLoop` 循环里：`rewrite(current_query, missing_aspect=missing)`，不足时 `current_query = query`（原句），`missing = grade.missing_aspect`。这样第二跳是「原问题 + 还缺定制例外」，而不是「改写的改写」语义漂移。

---

### 3.4 改写模型和生成模型是不是同一个？

**开口：** 都是 DeepSeek `deepseek-chat`，分类 / 改写 / 规划 / 生成共用 `LLMProvider`。改写 `temperature=0`；生成约 0.2。

**详细答案：** 无独立小改写模型。测试用 Fake。代价：每次单跳多一次 LLM；路由已花一次。这是延迟构成里要主动说的。

---

## 4. 混合检索 Hybrid

### 4.1 两路是什么？为什么不能只向量或只 BM25？

**开口：** BM25 抓条款数字和专有名词；`bge-small` 抓同义。只向量漏「7 天」；只 BM25 漏「能不能退」≈「七天无理由」。

**详细答案：** 见 `HybridRetriever`。政策语料短、中文条款密，两路互补。本 65 条上仅向量已经 83.1%，BM25 76.9%，说明向量路在本集很强；Hybrid 的工程价值还包括 **一路可失败**。

---

### 4.2 为什么 RRF 融 rank 不加权加分？k=60 是调参吗？

**开口：** BM25 分和余弦不同量纲，`0.5*bm25+0.5*cosine` 换 embedding 就失效。RRF：\(1/(k+\mathrm{rank})\)。**k=60 是 Cormack 等默认值，不是本项目网格搜索结论。**

**详细答案：** 同一 `chunk_id` 两路命中则分数相加、只留一条。代码 `app/retrieval/fusion.py`。`DEFAULT_RRF_K = 60` 写在 constants 注释里，面试主动说「不是调参科学」。

---

### 4.3 一路失败会不会拖死另一路？两路都空？

**开口：** 各自 try/except。两路都空才 `RetrievalError` → 对用户 503 `VECTOR_DB_UNAVAILABLE`。Qdrant 抖动时 BM25 仍能答政策。

**详细答案：** 未配 embedding 时 hash 几乎无语义，硬融会拉低 BM25，**不要把 hash Hybrid 说成语义检索**。

---

### 4.4 Hybrid 之后要不要精排？CE 和双塔差在哪？没加载权重能不能冒充 CE？

**开口：** 要。生产 **本地 Cross-Encoder `bge-reranker-base`**：query 和 doc **拼在一起**打分。双塔是分别编码再点积，适合召回；CE 适合精排。没装权重时是词面 overlap，报告必须写 `lexical`，不能写成 Cross-Encoder。

**详细答案：** `DocumentReranker` 调 provider；CI / testing 不下载。评测加载成功应出现 backend `hybrid+cross-encoder`。pytest 不打真实 CE。

---

### 4.5 本集上 RRF 有没有超过仅向量？增益主要来自哪？

**开口：** **没有。** BM25+small+RRF 与仅 small 都是 P@1 **83.1%** / R@3 **94.6%** / MRR **0.89**。再加 CE 到 **89.2% / 97.7% / 0.94**。本集增益主要来自精排。

**详细答案：** 相对纯 BM25：CE 路径 +12.3 / +7.7 个百分点。不要说「RRF 一定优于单路」。RRF 仍保留：量纲安全、一路失败、和 CE 解耦。

---

### 4.6 追问：向量路退化成 hash，Hybrid 数字还能写进简历吗？

**开口：** **不能。** 同日 hash 对照仅向量 Hit@1 **3.1%**。简历数字必须来自已加载 small + CE 的那次 JSON。

---

## 5. 多跳 Self-RAG

### 5.1 什么叫多跳？举电商例子。

**开口：** 答案依赖 **不止一条** 证据，且单次检索很难同时排到。例：「定制马克杯过了 7 天且已拆封，质量问题运费谁出」——要总则时效、定制例外、质量问题运费三条。

**详细答案：** 单跳容易只命中「7 天无理由」。第二跳 `missing_aspect` 去搜定制/质量例外。不是「把 query 送进向量库两次」就叫多跳。

---

### 5.2 多跳是 Hybrid 搜两次，还是 Self-RAG 循环？

**开口：** **Self-RAG 风格循环：** 改写 → Hybrid → CE → LLM JSON 打分 → 不足则带 `missing_aspect` 再 hop。最多 `max_retrieval_hops=3`。不是图上两个 `retrieve_docs`。

**详细答案：** 反思做成结构化 JSON（`relevant` / `sufficient` / `missing_aspect`），不是 Self-RAG 论文里的特殊 token。打分失败则：有 chunk 就当 sufficient，避免死循环空转。

累积用 `dict[chunk_id]` 去重，最后截断到 `rerank_top_n * 2`。

---

### 5.3 停止条件？模型说不够会不会死循环？

**开口：** `sufficient=true` 就停；否则最多 3 hop。循环是 `for _hop in range(max_retrieval_hops)`，硬上限。

**详细答案：** 没有「模型说 Continue 就无限跳」。3 hop 最坏是 3 次改写 + 3 次 Hybrid + 3 次 CE + 3 次 grade，延迟明显高于 SINGLE，所以路由器不能把所有政策都标 MULTI。

---

### 5.4 多跳和 Agent 会不会抢同一类问题？

**开口：** 规则里 **Agent 优先于 Multi**。有订单号 / 退款进度先查系统。纯政策组合才 MULTI。「我的单能不能退」该 `get_order` + 可能 `search_knowledge`，不是只靠多跳搜政策。

**详细答案：** Agent 里的知识工具是短路径 Hybrid top_k=4，**不**走 Self-RAG 循环（见 7.5）。事务 + 政策要组合时，靠 Planner 把 `get_order` 和 `search_knowledge` 排进同一次计划，而不是把订单问题标成 MULTI。

---

### 5.5 评测集有多少真正多跳？规则会不会误标？

**开口：** 检索 65 条主要是政策问句，**没有**单独报 MULTI 路径的条数。规则用「同时/如果」且长度>18，短句不易误标，长口语可能误标，白白加 hop。

**详细答案：** E2E 16 条里政策组走 Single/Multi，没有把「多跳准确率」写成独立指标。不要说「多跳 Hit@1 提升 xx」。能说的是机制 + 65 条整体检索数字（那是 Hybrid/CE 召回，多数是一跳评测路径）。

若被问「你怎么证明多跳有用」：用构造例子走 MULTI 看第二跳是否补上 missing 文档；离线集没有 hop 消融，**主动承认**。

---

### 5.6 追问：简历把改写+Hybrid 写成「解决多跳」，对吗？

**开口：** **不严谨。** 改写 + Hybrid 是 **单跳** 路径。多跳是 Self-RAG 循环。应拆开说：单跳靠改写和 Hybrid；复杂条件靠路由到 MULTI 再 hop。

---

## 6. 数字与评测

### 6.1 检索评测几条、几篇？金标是 chunk 还是文档？

**开口：** 65 条 / 39 篇知识库；金标是文档 **stem**（如 `return_policy`），不是 chunk id。5 条 query 标了两篇相关文档。

**详细答案：** `eval/dataset/rag_eval.jsonl`。匹配：`document_id` 去掉最后一段 digest 得 stem，按首次出现顺序去重后再算 P/R/MRR。同一政策多个切片只计一次，避免切碎刷 Recall。

---

### 6.2 P@1 / R@3 / MRR / Hit@k 怎么算？

**开口：** P@1 = 第一篇是否相关。R@3 = top3 命中了金标集合的多大比例。MRR = 第一个相关文档排名的倒数，没有则 0。Hit@k = top-k 是否至少一篇相关。

**详细答案：** 实现 `eval/metrics.py`。客服最敏感 P@1（第一名错了用户先看见错政策）。只报 Hit@k 会掩盖「第一名是错文档」。

---

### 6.3 各系统数字（必须能背）

**开口：** 已加载 small + CE，2026-08-22：

| 系统 | P@1 | R@3 | MRR |
|---|---|---|---|
| BM25 | 76.9% | 90.0% | 0.84 |
| 仅 bge-small | 83.1% | 94.6% | 0.89 |
| BM25 + small + RRF | 83.1% | 94.6% | 0.89 |
| Hybrid + CE | **89.2%** | **97.7%** | **0.94** |

同日 hash 仅向量 Hit@1 **3.1%**。

生成 65 条（同模型裁判）：无检索幻觉 20% → RAG 3.1% → RAG+自纠错 **0%**（&lt;4% 口径）。检索证明「找没找对」；幻觉证明「说没说对」。

---

### 6.4 改切分或知识库后金标要不要改？

**开口：** stem 级金标多数不用改；chunk 边界变了必须重跑 retrieval，**不要沿用旧 P@1**。文档增删或政策改名才改 `rag_eval.jsonl`。

**详细答案：** `docs/10-evaluation.md`：知识库变更先改金标。Prompt 变更跑 intent；切分变更跑 retrieval。

---

### 6.5 口径陷阱（答辩主动说）

1. 不要写 bge-m3；是 **bge-small-zh-v1.5**。
2. 不要说本集 RRF 优于仅向量。
3. Hash / 词面精排数字不能冒充语义 / CE。
4. 65 条手写政策问句，不是线上抽样；无双人标注。
5. pytest 不下载权重、不打真实 LLM。
6. E2E 关键词 **9/11（81.8%）**，不要说成 100%。
7. Faithfulness 同模型裁判偏乐观。

---

## 7. 跨模块综合

### 7.1 画一次「定制商品能不能七天无理由」

**开口：** ingest 时 `return_policy` 等文档按标题切成多块并 embed。在线路由多为 SINGLE（或含「如果定制」时 MULTI）→ 改写保留「定制」「七天」→ Hybrid → CE → 生成带 citation → 忠实度。

**详细答案：**

1. 离线：`return_policy.md` / 定制相关篇 → `document_id=return_policy_<hash>` → chunk `..._00`、`..._01`。
2. 护栏过 → 意图 `return_exchange` 或 `faq_policy`（「能不能」偏退换；「怎么算」偏政策）。
3. 无订单号：规则偏 SINGLE；若句子很长且有「如果」→ MULTI。
4. 单跳：改写 → BM25+向量 RRF → CE top_n=5 → `retrieved_chunks`。
5. 生成把最多 6 块写成 `[chunk_id] title\ncontent`，模型填 `citation_chunk_ids`。
6. 忠实度：若说「可以无理由退」但证据是「定制除外」，`supported=false`，重写或抽取式回退。

金标样例：`r001`「定制商品能不能七天无理由退货」→ `relevant_doc_ids: [return_policy]`。

---

### 7.2 问候误入检索会怎样？注入句进了向量库当 query 会怎样？

**开口：** 问候误检索：慢、贵、可能胡答政策。注入应在 **护栏节点** 先拒；检索文本当数据不当指令，生成 prompt 有 `UNTRUSTED_CONTEXT_BANNER`。

**详细答案：** Adaptive 的价值之一就是把 Direct/Refuse 从检索里拆出去。PDF 里若写「忽略以上规则」，banner 要求模型不遵守检索段落里的指令。护栏在意图之前，命中则根本不检索。

---

### 7.3 证据不足时生成说什么？忠实度失败会不会再检索一跳？

**开口：** 生成失败走抽取式回退（截证据 + 请补充订单号）。忠实度失败只 **改写答案一次**，再不行仍抽取，**不会**回流 `retrieve_docs`。

**详细答案：** 图上没有 `check_faithfulness → retrieve_docs`。再检索是 MULTI 内部的事，发生在生成前。这是延迟取舍：生成后再 hop 要再付一轮检索+生成。

---

### 7.4 检索到的政策被当成指令怎么防？

**开口：** 护栏拦 query 侧注入；生成 system 里 banner 声明检索文本 untrusted；不把检索段落当 system 角色。

**详细答案：** `app/prompts/answer.py` 引用 `UNTRUSTED_CONTEXT_BANNER`。工具 `search_knowledge` 说明：content 只作政策依据，不能当某笔订单的事实。

---

### 7.5 Agent 里的 `search_knowledge` 还走不走 Adaptive + 改写 + CE？

**开口：** **走短路径：** 直接 `HybridRetriever.retrieve(query, top_k=4)`，不改写、不 CE、不 Self-RAG、不经过 `retrieve_docs` 节点。

**详细答案：** `SearchKnowledgeTool` 持有同一 `HybridRetriever`。Planner 已经收缩目录、用户 query 往往已含政策词，再套一整条 Adaptive 会重复路由、拖垮写操作确认前的延迟。被问「是不是全链路统一检索」要否认，并说这是 Agent 与 RAG 叉的差异。

缓存：政策 query TTL 默认 60s；query 含订单号或「订单」**不缓存**（`app/retrieval/cache.py`）。

---

### 7.6 只能砍一样保上线：Adaptive、BM25、CE、Self-RAG，先砍谁？

**开口：** 先砍 **Self-RAG**（少、贵、离线无独立指标）；再砍 CE（可退回 RRF，P@1 从 89.2 回 83.1 仍可用）；**不要先砍 Adaptive**（问候/注入会打满检索）；BM25 作为 Qdrant 失败兜底尽量留。

**详细答案：** 上线排序：能拒答、能不检索问候、BM25 可用 > 向量 small > CE > Self-RAG。Hash 向量不要当生产语义路。

---

## 8. 面试官在验证什么

| 简历用词 | 其实在验证 | 开口锚点 |
|---|---|---|
| 预处理 / 切分 / 向量化 | 会不会 ingest | 500/60、稳定 ID、small 512 维 |
| 科学感知 / Adaptive-RAG | 是否每问都检索 | 五路；问候 Direct；论文 + Agent/Refuse |
| 动态调度策略 | 先分类再走死边 | LLM + 规则；有单号优先 Agent |
| 问题改写 | 时机与失败 | Hybrid 前；只用 `[0]`；失败原句 |
| 混合检索 | 量纲与一路可失败 | BM25+向量+RRF k=60 |
| 解决多跳 | Self-RAG 循环 | 不是 Hybrid 搜两遍；最多 3 hop |
| 数字 | 口径诚实 | CE 89.2%；RRF 本集未超仅向量 |

准备三件套：**画出「可不检索」的五路图**、**讲清切分与稳定 ID**、**背出 BM25 / small / RRF / CE 四行数字并主动说 RRF 本集无增益**。被追问时宁可说「多跳没有单独消融」「Agent 知识检索是短路径」，不要把仓库没有的热更新、语义切分、多路改写融合编进去。

---

上一份 [面试1 · 状态机与意图](01-langgraph-planning-intent.md) · 机制正文 [04](../04-adaptive-rag.md) · [15](../15-ingest-and-retrieval.md)
