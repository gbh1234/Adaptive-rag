# 10 · 评测与回归

> 一句话：改 Prompt 或切分后必须跑全集；简历数字只能来自 `eval/runner` 与 [`MEASURED.md`](../eval/MEASURED.md)。完整口径、消融与路径表见 [14 · 测评报告](14-evaluation-report.md)。

## 本章目录

1. [命令与数据集](#命令与数据集)
2. [指标怎么算](#指标怎么算)
3. [已测量](#已测量须与代码一起引用)
4. [可以写 / 不能写](#简历可以写--不能写)
5. [口径陷阱](#口径陷阱面试主动说)
6. [CI](#ci-建议)

对应：`eval/runner.py`、`eval/metrics.py`、`eval/dataset/`。

## 命令与数据集

```bash
python -m eval.runner --task all --llm
python -m eval.runner --task retrieval          # CI；装了 .[rerank] 且能加载权重时含 Cross-Encoder
python -m eval.runner --task intent --llm
python -m eval.runner --task generation --llm
python -m eval.runner --task e2e --llm
```

报告：`eval/reports/*.json`（git 忽略）。

| 文件 | 用途 | 条数 |
|---|---|---|
| `eval/dataset/intent_100.jsonl` | 14 类意图 | 100 |
| `eval/dataset/rag_eval.jsonl` | 政策检索 + 关键词 | 65 |
| `eval/dataset/e2e_eval.jsonl` | 注入/订单/政策 | 16 |

## 指标怎么算

文档级：chunk 的 `document_id` 去掉 `_{index}` 得到 stem，与 `relevant_doc_ids` 比。

### 代码摘要

```python
# eval/metrics.py
def precision_at_k(relevant: set[str], retrieved: list[str], k: int) -> float:
    top = retrieved[:k]
    return sum(item in relevant for item in top) / len(top)

def recall_at_k(relevant: set[str], retrieved: list[str], k: int) -> float:
    return sum(item in relevant for item in retrieved[:k]) / len(relevant)

def mrr(relevant: set[str], retrieved: list[str]) -> float:
    for rank, item in enumerate(retrieved, start=1):
        if item in relevant:
            return 1.0 / rank
    return 0.0
```

意图：`accuracy = 命中数 / 100`。生产评测跑 `intent_v3` + overlay。  
生成：幻觉 = 忠实度裁判 `supported=false`。相对下降 = `(naive - checked) / naive`。裁判与生成器同模型，**偏乐观**；关键词命中更独立。

检索评测在未加载 Cross-Encoder 时**不会**把词面 overlap 标成 Cross-Encoder。

## 已测量（须与代码一起引用）

**意图**（DeepSeek `deepseek-chat`，100 条）

| 版本 | 准确率 |
|---|---|
| 关键词规则 | 51% |
| `intent_v1`（无覆盖，历史） | 85% |
| `intent_v2`（无覆盖，历史） | 86% |
| 仅歧义覆盖层 | **100%** |
| `intent_v3` + 覆盖（生产） | **100%** |

**检索**（65 条，39 篇；**已加载 `bge-small-zh-v1.5` + Cross-Encoder**）

| 系统 | Precision@1 | Recall@3 | MRR |
|---|---|---|---|
| BM25 | 76.9% | 90.0% | 0.84 |
| 仅 `bge-small-zh-v1.5` | 83.1% | 94.6% | 0.89 |
| BM25 + small + RRF | 83.1% | 94.6% | 0.89 |
| Hybrid + Cross-Encoder | **89.2%** | **97.7%** | **0.94** |

P@1 / R@3 落在简历常用的 58%–85% / 63%–91%（CE 已超出上沿，面试报实测即可）。CE 相对 BM25：+12.3 / +7.7 个百分点。同日 hash 对照仅向量 Hit@1 3.1%。

**生成 / 幻觉**（65 条，同模型裁判）

| | Faithfulness | 幻觉率 | 关键词命中 |
|---|---|---|---|
| 无检索 | 80.0% | 20.0% | 36.9% |
| RAG | 96.9% | 3.1% | 95.4% |
| RAG + LLM 自纠错 | **100%** | **0%**（&lt;4%） | 95.4% |

无检索 Faithfulness 80% 落在 54%–88%；幻觉相对下降 100%（≥62%）。

**E2E**（16 条，2026-08-22 12:13Z）：拒答 / 工具路径 100%；关键词 **9/11（81.8%）**；P50 **4.9s** / P95 **5.8s**。

## 简历可以写 / 不能写

**可以：** 规则 51% → intent_v3+覆盖 100%；仅 small P@1 83.1%、R@3 94.6%；Hybrid+CE P@1 89.2%、R@3 97.7%；BM25 76.9% / 90% / 0.84；无检索幻觉 20% → RAG+自纠错 0%。

**不能：** 把本轮 E2E 关键词写成 100%；把稠密路写成 bge-m3；把 RRF 说成本集上优于仅 small。

## 口径陷阱（面试主动说）

1. 生产意图 = LLM JSON + 覆盖层；覆盖针对稳定中文歧义，不是按 query id 写死。
2. Faithfulness 同模型裁判偏乐观。
3. 稠密路是 `bge-small-zh-v1.5`，不是 bge-m3；本集上 RRF 没有超过仅 small。
4. pytest 不打真实 LLM。

## CI 建议

- PR：`pytest -q` + `python -m eval.runner --task retrieval`
- Prompt 变更：`--task intent --llm`，看 `mismatches`
- 知识库变更：先改 `rag_eval.jsonl` 金标
- 配上 Cross-Encoder：报告里必须出现 `hybrid+cross-encoder`

---

完整测评报告：[14](14-evaluation-report.md)。

上一章 [09](09-security.md) · 下一章 [11 · 部署](11-deployment.md)
