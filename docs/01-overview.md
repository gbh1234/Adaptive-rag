# 01 · 产品与问题定义

> 一句话：按问题复杂度选择 Direct / Single / Multi / Agent / Refuse，而不是对所有 query 做一次 `top_k` 向量检索。

## 本章目录

1. [要解决什么](#要解决什么)
2. [用户可见行为](#用户可见行为)
3. [成功标准](#成功标准工程不是-demo)
4. [非目标](#非目标)

对应代码：`app/agents/graph.py`、`app/core/enums.py`。

## 要解决什么

| 现状 | 失败模式 | 本仓库 |
|---|---|---|
| FAQ 关键词客服 | 长尾政策命中差 | BM25 + 向量 + RRF；`top_k` 随复杂度变 |
| 常规单跳 RAG | 多约束（定制 + 过期 + 质量）推不动 | Adaptive 路由到 Self-RAG 多跳 |
| 无护栏生成 | 幻觉、越权退款、注入 | 忠实度、HITL、注入检测 |
| 长会话 Agent | Token 膨胀 | 128k 预算，50% / 70% / 85% 三级压缩 |

### 要点

策略是枚举，不是字符串魔法。Graph 的条件边按 `RetrievalStrategy` 走。

### 代码摘要

```python
# app/core/enums.py
class RetrievalStrategy(str, Enum):
    DIRECT = "direct"    # 问候等，不检索
    SINGLE = "single"    # 一跳 hybrid
    MULTI = "multi"      # Self-RAG 多跳
    AGENT = "agent"      # Planner + 工具
    REFUSE = "refuse"    # 越权 / 边界
```

### 为什么

把「要不要检索、检索几跳、要不要调工具」收成一个枚举，才能：单独测路由、在 SSE 里暴露 `strategy`、在 Prometheus 上按策略打点。如果写在一个大 `if query:` 里，面试时讲不清失败路径。

## 用户可见行为

1. 问政策 → 检索知识库，尽量带 `citations`。
2. 问 `ORD10001` → `strategy=agent`，只读工具查单。
3. 申请退款/取消 → 返回 `pending_action`，确认后才写库。
4. 注入或越权 → `refused=true`，不走工具。

种子订单见 [02 · 快速开始](02-getting-started.md)。

## 成功标准（工程，不是 Demo）

- 业务失败和系统失败分开：`error_code` + HTTP；「证据不足」是 200 文案，不是 503。
- 外部调用有超时；429/5xx 可重试，401/403 不重试。
- RRF、路由、压缩、权限可单测（`tests/unit/`）。
- 简历数字必须来自 `python -m eval.runner`，见 [10](10-evaluation.md)。

## 非目标

不要对外写成已上线：

- 承运商 / 支付网关实接（订单是仓储种子数据）

详见 [12 · 限制](12-limitations.md)。

---

[文档首页](README.md) · 下一章 [02 · 快速开始](02-getting-started.md)
