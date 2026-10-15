# 检索优化口径、记忆压缩、Skill/MCP 与护栏

> 正文先读 [Chapter 3 · 工具、记忆与可靠性](chapter3.md)；本文件保留逐题追问和详细数字口径。

> 对应简历句：
>
> 1. **检索优化：** 基于 Self-RAG 构建多轮检索策略，并利用 RRF 对多源异构检索结果融合去重，随后调用 Cohere 重排序。Precision 76%→89%，Recall 63%→91%，Faithfulness 54%→88%，幻觉率下降 62%。
> 2. **上下文压缩与记忆：** 128k Token 预算（滑动窗口 + 动态摘要）；三层压缩：50%–70% 收紧工具结果，>85% auto-compact。
> 3. **Skill + MCP：** 按需加载退货 / 订单跟踪 / 商品推荐；本地与远程 MCP 统一为 Function Calling。
> 4. **兜底与护栏：** 分解层与执行层双向 Fallback；查询边界、幻觉检测与自纠错；幻觉率控制在 4% 以下。
>
> **答辩第一句（数字与 Cohere）：** 精排生产路径是本地 Cross-Encoder `bge-reranker-base`，**不是 Cohere**。76→89 对齐 BM25 P@1 76.9% → Hybrid+CE 89.2%。Recall 简历写 63%→91% 是常用区间，**本轮实测 R@3 是 90.0%→97.7%**。Faithfulness 简历 54%→88% 是区间口径，**实测无检索 80% → RAG+自纠错 100%**；幻觉相对下降实测 100%，简历写 ≥62%；&lt;4% 是保守上限，实测 0%（同模型裁判偏乐观）。

## 本章目录

1. [Self-RAG、RRF、精排与简历数字](#1-self-ragrrf精排与简历数字)
2. [上下文压缩与记忆管理](#2-上下文压缩与记忆管理)
3. [Skill + MCP](#3-skill--mcp)
4. [双向 Fallback、护栏与幻觉](#4-双向-fallback护栏与幻觉)
5. [面试官在验证什么](#5-面试官在验证什么)

---

## 1. Self-RAG、RRF、精排与简历数字

### 1.1 Self-RAG 多轮检索具体怎么跑？和 Adaptive 路由什么关系？

**开口：** 只有 `strategy=MULTI` 才进循环。每跳：改写（带 missing_aspect）→ Hybrid → Cross-Encoder → LLM JSON 打分。`sufficient` 则停，否则最多 3 hop。不是每问都多轮。

**详细答案：**

实现 `SelfRAGLoop`（`app/retrieval/self_rag.py`）。反思是结构化 JSON（`relevant` / `sufficient` / `missing_aspect`），不是论文里的特殊 token。chunk 按 `chunk_id` 累积去重。打分失败则有结果就当足够，避免空转。

Adaptive 先决定要不要 MULTI。单跳路径只有「改写 + Hybrid + 精排」一次。简历「基于 Self-RAG 构建多轮检索」不要说成全流量多轮。

---

### 1.2 RRF 融合的「多源异构」是哪几源？去重怎么做？

**开口：** 两源：BM25（稀疏）和向量（稠密）。异构指量纲不同，所以融 rank 不融分数。同一 `chunk_id` 分数相加、只留一条。

**详细答案：**

公式 \(\mathrm{RRF}(d)=\sum_i 1/(k+\mathrm{rank}_i(d))\)，`k=60` 是 Cormack 默认值，不是本项目调参。没有第三路（知识图谱、网页）不要编。一路失败另一路仍可融合。

本 65 条上 BM25+small+RRF 与仅 small 数字相同（P@1 83.1%），不要说 RRF 一定优于单路。

---

### 1.3 简历写 Cohere 重排序，仓库是什么？被问到怎么说？

**开口：** **改口。** 生产是本地 `BAAI/bge-reranker-base`（Cross-Encoder，query 和文档拼在一起打分）。未加载权重时是词面 overlap，不能叫 Cohere，也不能叫 Cross-Encoder。

**详细答案：**

仓库无 Cohere API、无 `COHERE_API_KEY`。简历若已投出，面试主动说：「当时按业界常用精排品牌写了 Cohere，落地为了离线可复现改成本地 CE，数字来自 `bge-reranker-base`。」不要坚持调用了 Cohere。

双塔（small）负责召回，CE 负责精排，不是把 embedding 模型再打一遍分。

---

### 1.4 Precision 76%→89%、Recall 63%→91% 怎么对口径？

**开口：** Precision 按 **P@1**：BM25 **76.9%** → Hybrid+CE **89.2%**。Recall 简历 63%→91% 是文档里写的「简历常用区间」；**本轮实测 R@3 是 BM25 90.0% → CE 97.7%**。被问「为什么简历和测评不一致」：区间是保守写法，答辩报 MEASURED 实测。

**详细答案：**

| 口径 | Precision | Recall |
|---|---|---|
| 简历 | 76%→89% | 63%→91% |
| 实测（65 条，文档 stem） | P@1 76.9%→89.2% | R@3 90.0%→97.7% |

金标是文档 stem 不是 chunk。P@1 看第一篇对不对；R@3 看相关政策有没有进前三。不要把 Hit@k 说成 Precision。

---

### 1.5 Faithfulness 54%→88%、幻觉下降 62%、控制在 4% 以下？

**开口：** 54%–88% 是无检索 Faithfulness 的常见区间；本轮无检索 **80%** / 幻觉 **20%**，RAG **96.9%** / **3.1%**，RAG+自纠错 **100%** / **0%**。相对下降 \((20-0)/20=100\%\)，简历写 ≥62%。&lt;4% 是保守上限（覆盖 3.1% 的 RAG 档）。

**详细答案：**

裁判与生成器同模型，**偏乐观**。关键词命中更独立：无检索 36.9% → RAG 95.4%。自纠错不提高关键词（仍 95.4%），只压幻觉话术。

流程：生成后 `FaithfulnessChecker` JSON（`supported` / `hallucinated_spans`）。失败则 LLM 按证据重写一次，再 check；仍不行抽取式回退。拒答或 HITL pending 跳过。**不会**因幻觉再 hop 检索。

---

### 1.6 这些数字是端到端还是检索子集？有没有对照实验？

**开口：** 检索 65 条政策；生成/幻觉同一 65 条；意图另 100 条；E2E 另 16 条。76→89 是检索消融（BM25 vs Hybrid+CE），不是 E2E。E2E 关键词 9/11，不要说成 89%。

**详细答案：** 对照：BM25 / 仅向量 / RRF / +CE；生成：无检索 / RAG / RAG+自纠错。Hash 向量 Hit@1 3.1% 证明「没加载 small 时不能报语义数字」。

---

## 2. 上下文压缩与记忆管理

### 2.1 128k 预算怎么算？是官方 tokenizer 吗？

**开口：** **不是。** DeepSeek tokenizer 未公开，启发式 **约 1.5 汉字/token**（`len(text)/1.5`）。`TOKEN_BUDGET=128000`。面试主动说是启发式，会和真实账单有偏差。

**详细答案：** `app/memory/budget.py` 的 `estimate_tokens`。只计 messages + summary，检索 chunk 另算进生成 prompt，压缩模块主要管会话历史和工具结果体积。

---

### 2.2 三层阈值和行为分别是什么？

**开口：**

| 利用率 | 级别 | 行为 |
|---|---|---|
| &lt;50% | none | 不动 |
| 50%–70% | soft | 工具结果截到 400 字 |
| 70%–85% | hard | 工具 160 字 + 最近 4 轮滑动窗口 |
| &gt;85% | auto-compact | 窗口 + LLM 动态摘要，摘要失败则最近 4 条截断拼接 |

**详细答案：**

设置：`compress_soft_ratio=0.50`，`hard=0.70`，`auto_compact=0.85`。`KEEP_RECENT_TURNS=4`，窗口按「4 轮 ≈ 8 条消息」（user+assistant）。hard/auto 若已有 summary，前面加一条 `对话摘要：...`。

`memory_node` 在图末尾：先把本轮 user/assistant 追加进 messages，再 `apply_compression`；仅 AUTO 时调 `ConversationSummarizer`，再压一次。单测 `tests/unit/test_compression.py`。

为什么不用 LangGraph `Annotated[add]` 无限 append：长会话会把预算打爆且难以断言。显式节点让「何时摘要」可测。

---

### 2.3 滑动窗口和动态摘要谁先谁后？摘要失败怎么办？

**开口：** hard 就开始窗口。auto 在窗口之后让 LLM 摘要（最多看最近 16 条，输出截断 800 字）。LLM 挂了：最近 4 条各取 40 字拼起来，不中断请求。

**详细答案：** 摘要是为了下一轮还能看见「用户上次要退 ORD10001」，不是为了当前答案（当前答案已生成）。压缩发生在忠实度 **之后**，不影响本轮回复，影响下轮 prompt。

---

### 2.4 为什么 50% 先砍工具结果，而不是先砍对话？

**开口：** 工具 JSON 最肥、对多轮指代价值低；最近对话有「这件/那个单」的指代。先截工具是性价比最高的。

**详细答案：** 写工具的 output 仍可能被截成 preview。幂等结果在 DB，不依赖 state 里完整 JSON。不要把压缩说成「丢了退款凭证」——凭证在幂等表。

---

### 2.5 压缩会不会把订单号压丢，下一轮幻觉？

**开口：** 窗口保留最近 4 轮；auto 摘要 prompt 要求保留订单号等实体（以 `app/prompts/summary.py` 为准）。仍可能丢更早的单号，用户需再提供。没有单独的「实体白名单抽取」模块，不要编。

---

## 3. Skill + MCP

### 3.1 Skill 按需加载是什么？三个技能分别绑定哪些工具？

**开口：** 三个 JSON：退货处理、订单跟踪、商品推荐。先匹配 trigger 短语，再按意图映射。命中后 Planner **只展示该 Skill 的工具** + 永远可调的 `search_knowledge`、`escalate_to_human`。

**详细答案：**

`app/skills/definitions/`。例 `return_handling`：triggers「退货/换货/7天无理由」；tools：`get_order`、`get_order_items`、`search_knowledge`、`create_return_request`。

`INTENT_TO_SKILL`：退货/退款 → return_handling；物流/查单/取消 → order_tracking；推荐/咨询 → product_recommend。

不是「LLM 失败才读 JSON」。Skill 在规划 **前** 收缩目录；失败才 `skill_to_plan` 把 JSON 落成步骤。15 个工具全塞进 prompt 容易在退货场景乱调 `cancel_order`。

可插拔：加一个 JSON + 注册对应 Tool 即可，不必改图。没有运行时从网关热加载 Skill 文件，重启才读目录。

---

### 3.2 MCP 和本地工具如何统一成 Function Calling？

**开口：** `MCPToolProxy` 继承同一套 `Tool`：`openai_schema()` 都是 `type=function`，`run` 先校验再 `execute`。Planner/Executor **不区分** transport。

**详细答案：**

本地 catalog：`mcp_store_hours`（营业时间、夜间是否审退款）、`mcp_warehouse_cutoff`（截单）。`MCP_ENABLED` 时 `merge_mcp_tools`。远程走 HTTP POST JSON；失败变 `ToolExecutionError`，读工具仍可 `READ_FALLBACKS` 到 `search_knowledge`。

MCP 不是第二个 Agent 框架，只是 Tool 适配器。演示的是接入模型，不是已对接全部外部系统。

---

### 3.3 远程 MCP 挂了、鉴权失败、和本地工具风险等级是否一致？

**开口：** 对执行器一致，都是 `ToolResult`。MCP 默认风险 `external`。权限拒绝不走读 Fallback。远程多一层超时，映射成工具错误，不把图打挂。

**详细答案：** 营业时间类可降级搜知识库，不要降级成「编造 24 小时营业」。夜间 `night_refund_review=false` 时不要承诺立即退款——这是工具描述里写死的。

---

### 3.4 Skill 命中错了（推荐流程去处理退货）怎么办？

**开口：** trigger 先于意图。用户说「退货」不会进推荐 Skill。若意图错但同属售后，退货/退款共用 `return_handling`，伤害被目录重叠缩小。写操作仍要 HITL。

---

## 4. 双向 Fallback、护栏与幻觉

### 4.1 「任务分解和工具执行层双向 Fallback」指哪两层？

**开口：**

- **分解层：** Planner LLM JSON 失败或 sanitize 后无步骤 → Skill 模板落成步骤（抽 `ORD\d+`）→ 再不行只调 `search_knowledge`。
- **执行层：** 读工具失败按 `READ_FALLBACKS` 换下一个（如 `get_order` → `search_knowledge`）。**写工具和权限拒绝不走这张表。**

**详细答案：** 两层都不是「模型再 Thought 一轮」。分解层保证 Agent 叉不空转；执行层保证读失败仍能给政策。写操作 Fallback 会绕过 HITL，所以禁止。

---

### 4.2 查询边界护栏拦什么？和意图 `out_of_scope` 谁先？

**开口：** 护栏节点在意图 **之前**。明显注入（ignore previous / 忽略以上指令 / 索要 system prompt）直接 `refused`，条件边去拒答，不检索。更泛的越权（炒股、炸弹）靠意图 + 路由器 REFUSE。

**详细答案：** `detect_prompt_injection`。检索段落不当指令：生成 prompt 有 `UNTRUSTED_CONTEXT_BANNER`。业务拒答可以 HTTP 200 + `refused=true`；系统故障才 5xx。

---

### 4.3 幻觉检测与自纠错重试：重试的是生成还是检索？

**开口：** **只改写答案一次**，不重检索、不重规划。再不行抽取证据句子。metrics `HALLUCINATION_FLAGS`。

**详细答案：** 流式已推 token 时，纠错只改最终 `answer` 事件，没有撤回协议。前端以 `answer` 为准。

---

### 4.4 「幻觉率 4% 以下」和「下降 62%」会不会打架？

**开口：** 不打架。&lt;4% 是绝对水平（RAG 档 3.1%，自纠错档 0%）。62% 是相对下降的**简历下限**；实测相对下降 100%。答辩报实测，并说同模型裁判偏乐观。

---

### 4.5 护栏误杀正常售后怎么办？漏检注入怎么办？

**开口：** 误杀：正则过严会把「忽略运费，只看时效」当注入——当前模式偏英文 jailbreak 和「忽略以上指令」，中文售后较少误伤。漏检：意图优先级把注入标 `out_of_scope`，banner 降低检索投毒。没有语义分类器当护栏，不要说成 LLM 安全模型。

---

## 5. 面试官在验证什么

| 简历用词 | 其实在验证 | 开口锚点 |
|---|---|---|
| Self-RAG 多轮 | 是否全流量多跳 | 仅 MULTI，最多 3 hop |
| RRF 多源异构 | 是否懂量纲 | BM25+向量，融 rank，k=60 |
| Cohere 重排序 | 是否诚实 | **改口成本地 CE** |
| 76→89 / 63→91 | 指标定义 | P@1 实测 76.9→89.2；R@3 报 90→97.7 |
| 54→88 / 下降 62% / &lt;4% | 消融与保守写法 | 80→100%；相对下降 100%；&lt;4% 是上限 |
| 128k 三层压缩 | 是否真有预算 | 启发式 tokenizer；50/70/85 |
| Skill 按需加载 | 是否防乱调工具 | 规划前收缩目录 |
| MCP Function Calling | 是否同一 Tool | Proxy 继承 Tool |
| 双向 Fallback | 写操会不会被换走 | 读可换，写/权限不可 |
| 护栏 + 自纠错 | 注入与幻觉分层 | 护栏在意图前；纠错不重检索 |
