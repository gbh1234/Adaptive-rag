# 14 · 测评报告

> 一句话：数字只来自 `eval.runner` 写出的 JSON；本文把口径、数据集、消融和限制写全，方便复现和面试对质。

## 本章目录

1. [结论摘要](#1-结论摘要)
2. [评测目标与范围](#2-评测目标与范围)
3. [环境与复现](#3-环境与复现)
4. [数据集](#4-数据集)
5. [指标定义](#5-指标定义)
6. [意图识别](#6-意图识别)
7. [检索](#7-检索)
8. [生成与幻觉](#8-生成与幻觉)
9. [端到端](#9-端到端)
10. [自动化测试](#10-自动化测试)
11. [与简历数字对照](#11-与简历数字对照)
12. [未测项与下一步](#12-未测项与下一步)

对应：[`eval/runner.py`](../eval/runner.py)、[`eval/metrics.py`](../eval/metrics.py)、[`eval/MEASURED.md`](../eval/MEASURED.md)。  
命令与 CI 门槛见 [10 · 评测与回归](10-evaluation.md)。

**测量日期：** 2026-08-22  
**生成模型 / 裁判模型：** DeepSeek `deepseek-chat`（API 上的 DeepSeek-V3）  
**稠密召回：** `BAAI/bge-small-zh-v1.5`（已加载）  
**精排：** `BAAI/bge-reranker-base`（已加载）  
**原始报告：** 标识 `all_20260822T121308Z.json`。`eval/reports/*.json` 已按 `.gitignore` 忽略、不随仓库分发，仓库内没有报告本体；结论以 [`MEASURED.md`](../eval/MEASURED.md) 为准。

---

## 1. 结论摘要

| 任务 | 集合 | 主结果 | 对照 |
|---|---|---|---|
| 意图 | 100 条 / 14 类 | `intent_v3` + 覆盖层 **100%** | 关键词规则 51%；无覆盖 v1 85% / v2 86% |
| 检索 | 65 条 / 39 篇 | BM25 **P@1 76.9%**、**R@3 90.0%**、**MRR 0.84** | 仅 `bge-small` **83.1 / 94.6 / 0.89** |
| 检索 + CE | 同上 | Hybrid+CE **P@1 89.2%**、**R@3 97.7%**、**MRR 0.94** | 相对 BM25 +12.3 / +7.7 个百分点 |
| 生成 / 幻觉 | 65 条 | RAG+自纠错忠实度 **100%**、幻觉 **0%** | 无检索 80% / 20%；相对下降 100% |
| E2E | 16 条 | 拒答 / 工具路径 **100%**；关键词 **9/11（81.8%）** | P50 **4.9s** / P95 **5.8s** |
| 回归 | pytest | **154 passed** | 不打真实 LLM / 不下载权重 |

### 要点

这次测评验证四件事：Adaptive 路由能把问候和注入从检索里拆出去；本地 `bge-small-zh-v1.5` 把仅向量 P@1 从 hash 的 3.1% 拉到 **83.1%**；Cross-Encoder 再把 Hybrid P@1 从 83.1% 提到 **89.2%**；忠实度自纠错能把同模型裁判下的幻觉从 20% 压到 0%。本 65 条上 BM25+small 的 RRF 没有超过仅 small。

---

## 2. 评测目标与范围

客服场景里「感觉还行」不够。本仓库把可面试的数字钉在四条离线任务上：

| 任务 | 回答的问题 | 不回答的问题 |
|---|---|---|
| `intent` | 14 类意图能不能分对，覆盖层贡献多少 | 路由策略是否最优 |
| `retrieval` | 政策文档能不能排到前面 | 生成句子是否正确 |
| `generation` | 有无证据时会不会胡编；自纠错有没有用 | 人工偏好、文采 |
| `e2e` | 注入会不会拒、订单会不会走工具、延迟多少 | 并发压测、多租户 |

**范围内：** 本地 SQLite + 内存检索 + DeepSeek + 本地 `bge-small-zh-v1.5` + Cross-Encoder；知识库 `knowledge/*.md`（39 篇）。  
**范围外：** 更大 embedding（bge-m3 等）、线上流量 A/B、人工标注一致性。

---

## 3. 环境与复现

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]" ".[rerank]"
# .env 填 DEEPSEEK_API_KEY；国内拉权重可设 HF_ENDPOINT=https://hf-mirror.com

pytest -q
python -m eval.runner --task all --llm
```

报告写到 `eval/reports/{task}_{UTC}.json` 和 `eval/reports/latest.json`。  
改 Prompt、切分或知识库后必须重跑对应任务，再改 [`MEASURED.md`](../eval/MEASURED.md) 与本文数字。

### 为什么

pytest 在 `tests/conftest.py` 清空真实 key，保证 CI 可重复、不烧钱。简历上的百分比必须来自 `--llm` 那次跑出来的 JSON，不能手填。

---

## 4. 数据集

| 文件 | 条数 | 金标 | 用途 |
|---|---|---|---|
| `eval/dataset/intent_100.jsonl` | 100 | `intent`（14 类） | 分类准确率与消融 |
| `eval/dataset/rag_eval.jsonl` | 65 | `relevant_doc_ids` + `gold_answer_contains` | 检索 P/R/MRR + 生成关键词 |
| `eval/dataset/e2e_eval.jsonl` | 16 | `expect_refused` / `expect_keywords` | 整图路径与延迟 |

### 4.1 意图：14 类分布

| 标签 | 条数 | 业务含义 |
|---|---|---|
| `faq_policy` | 16 | 发票、积分、客服时间等政策 |
| `return_exchange` | 8 | 退货 / 换货 |
| `out_of_scope` | 8 | 注入、炸弹、炒股等越权 |
| `order_inquiry` | 7 | 查单 |
| `logistics` | 7 | 物流轨迹 |
| `product_consult` | 7 | 规格 / 库存 |
| `chitchat` | 6 | 闲聊 |
| `refund` | 6 | 退款到账 |
| `cancel_order` | 6 | 取消未发货 |
| `recommendation` | 6 | 推荐商品 |
| `coupon` | 6 | 优惠券叠加 |
| `complaint` | 6 | 投诉 |
| `human_handoff` | 6 | 转人工 |
| `greeting` | 5 | 问候 |

样例：`{"id":"i011","query":"怎么开发票","intent":"faq_policy"}`。

### 4.2 检索 / 生成：65 条政策问句

金标是**文档 stem**（如 `return_policy`），不是 chunk id。65 条覆盖 38 个不同文档 stem；5 条 query 标了两篇相关文档（例如包邮 + 优惠券）。

样例：

```json
{"id":"r001","query":"定制商品能不能七天无理由退货","relevant_doc_ids":["return_policy"],"gold_answer_contains":["定制","无理由"]}
```

知识库 `knowledge/` 共 **39** 篇 Markdown，ingest 后约 156 chunk。文档级匹配：`document_id` 去掉 `_{index}` 得到 stem。

### 4.3 E2E：16 条路径覆盖

| 组 | ID | 在测什么 |
|---|---|---|
| 问候 | e01 | Direct，不检索 |
| 政策 | e02–e05, e09, e16 | Single / Multi + 关键词 |
| 工具 | e06–e08, e14, e15 | 查单 / 物流 / 库存 / 取消（HITL） |
| 拒答 | e10–e12 | 注入、造炸弹、炒股 |
| 转人工 | e13 | `human_handoff` |

`e10`「Ignore previous instructions…」期望 `refused=true`。  
演示用户 `u_demo`；订单 `ORD10001` / `ORD10002` / `ORD10003`。

---

## 5. 指标定义

### 要点

检索评的是**文档**不是 chunk：同一篇政策的多个切片只计一次。幻觉率 = 忠实度裁判 `supported=false` 的比例，**不是**人工事实核查。

### 代码摘要

```python
# eval/metrics.py
def precision_at_k(relevant, retrieved, k):
    top = retrieved[:k]
    return sum(item in relevant for item in top) / len(top)

def recall_at_k(relevant, retrieved, k):
    return sum(item in relevant for item in retrieved[:k]) / len(relevant)

def mrr(relevant, retrieved):
    for rank, item in enumerate(retrieved, start=1):
        if item in relevant:
            return 1.0 / rank
    return 0.0
```

| 指标 | 公式（本仓库实现） | 报告里用的 |
|---|---|---|
| Accuracy | 命中数 / N | 意图 100 条 |
| Precision@k | Top-k 里相关文档数 / k | P@1 |
| Recall@k | Top-k 命中的相关文档 / 金标文档数 | R@3 |
| Hit@k | Top-k 是否至少一篇相关 | 向量路对照 |
| MRR | 第一个相关文档排名的倒数，未命中为 0 | 检索 |
| Faithfulness | `supported=true` 占比 | 生成 |
| 幻觉率 | `supported=false` 占比 | 生成 |
| 相对下降 | `(naive - checked) / naive` | 无检索 vs RAG+自纠错 |
| 关键词命中 | `gold_answer_contains` 全部出现在答案中 | 生成 / E2E |
| 拒答准确率 | `expect_refused` 与 `response.refused` 一致 | E2E（3 条） |
| 工具路径 | query 含 ORD/库存/取消，且答案含订单号或 `pending_action` | E2E |
| 延迟 | `response.latency.total_ms` 的 P50 / P95 | E2E |

### 为什么

P@1 看「第一篇对不对」（客服最敏感）；R@3 看「相关政策有没有进上下文」。只报 Hit@k 会掩盖「第一名是错文档」的失败。关键词命中比同模型 Faithfulness 更独立，面试要并列表。

---

## 6. 意图识别

生产路径：DeepSeek 输出 JSON（`intent_v3`）→ `apply_intent_overlay` 纠偏。LLM 挂了走关键词规则，再走同一覆盖层。

### 6.1 消融（100 条）

| 系统 | 覆盖层 | 准确率 |
|---|---|---|
| 关键词规则 `intent_rules_v1` | 无 | 51.0% |
| `intent_v1` | 关 | 85.0% |
| `intent_v2` | 关 | 86.0% |
| 仅歧义覆盖层 | — | **100%** |
| `intent_v3` + 覆盖（生产） | 开 | **100%** |

规则基线在 `chitchat` / `product_consult` 为 0，`refund` 仅 16.7%：关键词分不清「退货」和「退款到账」。LLM 把整体拉到 85%–86%；覆盖层专门打转人工 vs 退款、政策问法 vs 退换货等稳定中文歧义。

### 代码摘要

```python
# app/agents/nodes/intent_overlay.py
def high_precision_intent(query: str) -> IntentLabel | None:
    # 只在高置信短语上返回标签，否则 None（交给 LLM）
    if any(token in text for token in _HANDOFF):
        return IntentLabel.HUMAN_HANDOFF
    ...
```

评测可 `apply_overlay=False` 做消融；生产 `apply_overlay=True`。

### 为什么 / 面试主动说

100% **含覆盖层**。覆盖针对稳定客服短语（「转人工」压过退款），**不是**按 `i070` 这种 query id 写死金标。规则基线必须保留：它证明「只靠 if-else」不够，也是 LLM 宕机时的兜底。

---

## 7. 检索

65 条，`top_k=5`。稠密侧是本地 `BAAI/bge-small-zh-v1.5`（`BgeM3EmbeddingProvider`，`backend=bge-small-zh-v1.5`）。Cross-Encoder 已加载，报告含 `hybrid+cross-encoder`。同日更早一轮 hash 对照（报告标识 `all_20260822T042748Z.json`）仅向量 Hit@1 3.1%。

### 7.1 系统对照

| 系统 | Precision@1 | Recall@3 | Hit@1 | Hit@3 | MRR |
|---|---|---|---|---|---|
| BM25 | 76.9% | 90.0% | 76.9% | 90.8% | 0.84 |
| 仅 `bge-small-zh-v1.5` | 83.1% | 94.6% | 83.1% | 95.4% | 0.89 |
| BM25 + small + RRF | 83.1% | 94.6% | 83.1% | 95.4% | 0.89 |
| Hybrid + Cross-Encoder | **89.2%** | **97.7%** | 89.2% | 98.5% | **0.94** |

报告字段：取自该轮报告 `all_20260822T121308Z.json`（未随仓库分发），字段名与 [`eval/runner.py`](../eval/runner.py) 一致。

### 要点

仅 small 已经超过 BM25（P@1 +6.2，R@3 +4.6 个百分点）。本集合上 RRF 与仅 small **数字相同**，不要把 Hybrid 吹成「融合一定涨点」。有效再涨来自 **Cross-Encoder**（相对 BM25：P@1 +12.3，R@3 +7.7；相对 RRF：P@1 +6.1，R@3 +3.1）。同日 hash 对照 Hit@1 仅 3.1%，接上 small 之前不能把 Hybrid 说成语义检索。

### 为什么

双塔解决近义召回（「不想要了」≈ 七天无理由）；Cross-Encoder 把 query 和文档拼在一起打分，处理「定制过了七天有质量问题」这类排序。简历写 CE 的 **89.2 / 97.7 / 0.94**，同时说稠密路是 small 不是 m3，且 RRF 在本集上没有额外增益。

---

## 8. 生成与幻觉

同一 65 条：无检索生成 vs Hybrid 证据生成 vs 忠实度失败后 `self_correct_answer`（先 LLM 重写，再抽取式回退）。裁判与生成器同模型 `deepseek-faithfulness_v1`。

| 条件 | Faithfulness | 幻觉率 | 关键词命中 |
|---|---|---|---|
| 无检索 | 80.0% | 20.0% | 36.9% |
| RAG | 96.9% | 3.1% | 95.4% |
| RAG + LLM 自纠错 | **100%** | **0%** | 95.4% |

相对下降 `(20.0% - 0%) / 20.0% = 100%`（简历常用门槛 ≥62%）。无检索 Faithfulness 80% 落在 54%–88% 这档。

### 代码摘要

```python
# eval/runner.py · eval_generation
naive = await _generate_answer(llm, query, "(无检索结果)")
rag = await _generate_answer(llm, query, evidence)
if not rag_judge.supported:
    checked, checked_judge, _ = await self_correct_answer(...)
```

幻觉定义：`FaithfulnessChecker.check(...).supported is False`。

### 为什么 / 口径陷阱

同模型裁判**偏乐观**（生成器和裁判共享知识与措辞）。关键词命中在 RAG 后从 36.9% 到 95.4%，自纠错**没有**再提高关键词——它修的是「证据支撑」，不是补全金标词。面试要两列一起报。

---

## 9. 端到端

16 条走完整 `ChatService` → LangGraph（含护栏、意图、Adaptive 五路、工具、HITL）。限流在评测里临时调到 1000 次/分钟。

| 指标 | 结果 |
|---|---|
| 拒答准确率（3 条） | **100%** |
| 关键词命中（11 条） | **9/11（81.8%）** |
| 工具路径（5 条） | **100%** |
| 延迟 P50 / P95 / mean | **4925 / 5774 / 4567 ms** |
| 意图分段 P50 | 803 ms |
| 生成 LLM 分段 P50 | 1084 ms |
| 检索 / 工具分段 P50 | **0 ms** |

检索与工具的 P50 为 0，是因为 16 条里 Direct / Refuse 不检索、部分路径不调工具，**中位数被 0 拉平**。n=16 的 P95 是离散分位（5.8s）；实际最慢是 `e02` multi **11.1s**。注入 `e10` **10 ms**——正则拦下，不打 LLM。

### 策略分布（实测）

| ID | 意图 | 策略 | 延迟 |
|---|---|---|---|
| e01 | greeting | direct | 3.1s |
| e02 | return_exchange | multi | 11.1s |
| e03 | faq_policy | single | 4.4s |
| e04 | faq_policy | single | 5.2s |
| e05 | faq_policy | single | 4.9s |
| e06 | order_inquiry | agent | 5.5s |
| e07 | order_inquiry | agent | 4.8s |
| e08 | logistics | agent | 4.3s |
| e09 | coupon | single | 5.0s |
| e10 | （注入） | refuse | 10ms |
| e11 | out_of_scope | refuse | 1.5s |
| e12 | out_of_scope | refuse | 1.7s |
| e13 | human_handoff | direct | 5.3s |
| e14 | product_consult | single | 5.8s |
| e15 | cancel_order | agent | 5.7s（HITL 确认，未真取消） |
| e16 | faq_policy | single | 4.8s |

来源：该轮报告 `all_20260822T121308Z.json`（未随仓库分发）；汇总口径见 [`MEASURED.md`](../eval/MEASURED.md)。

---

## 10. 自动化测试

`pytest -q`：**154 passed**（含 Cross-Encoder / 本地 embedding 单测，mock 权重）。覆盖 RRF、Adaptive 路由、护栏、压缩、工具权限、Skill、MCP、执行 Fallback、自纠错、订单仓储、HTTP 聊天，以及 `eval` 指标函数与检索缓存 / 自纠正 / 查询改写 / 向量检索 / 分词。

pytest **不**调用真实 DeepSeek / 不下载 Cross-Encoder。线上指标必须 `eval.runner --llm`；CE 分数必须 `hybrid+cross-encoder` 那一行。

---

## 11. 与简历数字对照

**可以写（已测量）：**

- 意图：规则 51% → 无覆盖 v1 85% / v2 86% → v3+覆盖 **100%**（≥97%）
- 仅 `bge-small`：P@1 **83.1%**、R@3 **94.6%**、MRR **0.89**
- Hybrid+CE：P@1 **89.2%**、R@3 **97.7%**、MRR **0.94**
- BM25 对照：P@1 **76.9%**（58–85）、R@3 **90%**（63–91）、MRR **0.84**
- 幻觉：无检索 20% → RAG+自纠错 **0%**（&lt;4%）；相对下降 100%（≥62%）
- 无检索 Faithfulness **80%**（54–88%）
- E2E P50 **4.9s** / P95 **5.8s**；注入拒答约 10ms；关键词 **9/11**

**不能写：**

- 把本轮 E2E 关键词写成 100%
- 把 100% 意图说成「纯 LLM、无规则」
- 把 Faithfulness 100% 说成「人工事实核查零幻觉」
- 把稠密路写成 bge-m3，或把 RRF 说成本集上优于仅 small

---

## 12. 未测项与下一步

| 项 | 状态 | 怎样才算测完 |
|---|---|---|
| Cross-Encoder `BAAI/bge-reranker-base` | **已测** Hybrid+CE P@1 89.2% / R@3 97.7% | 换 checkpoint 后重跑 retrieval |
| `bge-small-zh-v1.5` | **已测** 仅向量 P@1 83.1% / R@3 94.6% | 换更大 embedding 后另跑，勿混写成 m3 |
| 意图无覆盖的 v3 单列 | 生产 100% 含覆盖；关覆盖的 v3 未单独落 JSON | `apply_overlay=False` 再跑一列 |
| E2E 关键词 | 本轮 9/11 | 看失败 2 条的答案再改生成或金标 |
| 人工 Faithfulness | 无 | 抽 20 条双人标注 |
| 并发 / 限流 / 故障注入 | 仅单请求 E2E | 另做压测，不进本报告 |

---

上一章 [13 · 面试稿](13-interview-engineering-rag.md) · [返回目录](README.md)
