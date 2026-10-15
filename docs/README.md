# 技术文档

生产向手册。结构参考 [Diátaxis](https://diataxis.fr/)：先能跑，再讲概念，再查参考，最后看上线。

**原则：只写仓库里真实存在的行为。** 评测数字以 [10 · 评测](10-evaluation.md) 和 [`eval/MEASURED.md`](../eval/MEASURED.md) 为准。

## 文档约定

每一章的**重点机制**固定三块，避免「只讲概念不给代码」：

| 块 | 作用 |
|---|---|
| **要点** | 先给结论，面试可直接复述 |
| **代码摘要** | 仓库里的真实片段（带文件路径），不是伪代码 |
| **为什么** | 取舍：为什么这样、不那样会怎样 |

完整实现以源文件为准；摘要只截关键分支，避免把整文件贴进文档。

## 怎么读

| 你想… | 去 | 关键代码 |
|---|---|---|
| 5 分钟跑通 | [02](02-getting-started.md) | `app/asgi.py`、`app/services/seed.py` |
| 分层与 Graph | [03](03-architecture.md) | `app/agents/graph.py`、`app/core/request_scope.py` |
| Adaptive-RAG / RRF / Self-RAG | [04](04-adaptive-rag.md) | `app/retrieval/` |
| 解析 / 切块 / 向量库 / Hybrid / 精排 | [15](15-ingest-and-retrieval.md) | `app/retrieval/`、`app/providers/embeddings.py` |
| 意图 / Skill / 工具 / HITL / MCP | [05](05-agents-and-tools.md) | `app/agents/nodes/`、`app/tools/`、`app/mcp/` |
| HTTP / SSE | [06](06-api-reference.md) | `app/api/routes/chat.py`、`app/schemas/chat.py` |
| 环境变量 | [07](07-configuration.md) | `app/config/settings.py` |
| 超时重试 / 指标 | [08](08-reliability.md) | `app/core/retry.py`、`app/observability/` |
| 注入 / 越权 / 密钥 | [09](09-security.md) | `app/guardrails/`、`app/tools/permissions.py` |
| 简历数字 | [10](10-evaluation.md) | `eval/runner.py` |
| 完整测评报告 | [14](14-evaluation-report.md) | `eval/MEASURED.md`、`eval/dataset/` |
| Docker | [11](11-deployment.md) | `docker-compose.yml` |
| 写掘金/面试长文 | [13](13-interview-engineering-rag.md) | 对照仓库的「玩具 vs 工程化」 |
| 项目面试书 | [目录](interview/README.md) | 三章连续讲述请求、证据与行动 |
| 面试维度索引 | [16](16-interview-bagu-map.md) | zero2Agent 17 维度 ↔ 三章与实现边界 |

## 章节

1. [产品与问题定义](01-overview.md)
2. [快速开始](02-getting-started.md)
3. [系统架构](03-architecture.md)
4. [Adaptive-RAG 与检索](04-adaptive-rag.md)
5. [智能体、工具与 HITL](05-agents-and-tools.md)
6. [API 参考](06-api-reference.md)
7. [配置参考](07-configuration.md)
8. [可靠性与可观测性](08-reliability.md)
9. [安全与护栏](09-security.md)
10. [评测与回归](10-evaluation.md)
11. [部署与运维](11-deployment.md)
12. [限制与路线图](12-limitations.md)
13. [面试稿：Demo 还是能上线](13-interview-engineering-rag.md)（含完整框架图）
14. [测评报告](14-evaluation-report.md)（数据集、消融、口径陷阱）
15. [解析、切块、向量化与检索](15-ingest-and-retrieval.md)
16. [zero2Agent 面试维度索引](16-interview-bagu-map.md)

项目面试书：[Chapter 1 · 执行图](interview/chapter1.md) → [Chapter 2 · 检索证据](interview/chapter2.md) → [Chapter 3 · 工具与可靠性](interview/chapter3.md)。逐题追问资料从 [面试书目录](interview/README.md) 进入。

## 仓库地图

```text
app/
  api/            HTTP：路由、校验、SSE
  services/       ChatService、DI 容器、种子数据
  agents/         LangGraph 状态机与节点
  retrieval/      解析、清洗、切分、BM25、向量、RRF、Adaptive、Self-RAG
  tools/          15 业务工具 + Registry + 权限
  mcp/            本地/远程 MCP，统一成 Tool
  skills/         退货/跟踪/推荐 JSON，按需加载
  repositories/   订单、会话、幂等
  providers/      DeepSeek / Embedding / Cross-Encoder
  guardrails/     注入、边界、忠实度
  memory/         128k 预算与三级压缩
  prompts/        版本化模板
  observability/  JSON 日志、Prometheus、contextvars
knowledge/        政策文档（Markdown；生产还可 PDF/Office/HTML/图片）
eval/             离线集 + runner
tests/            unit / integration / e2e
docs/             本手册
```

请求路径（记住这一条就能画架构图）：

```text
HTTP → ChatService → LangGraph → Retriever 或 Tool → Provider / DB
```


## 系统化工程教程

面向「从零讲清一个可运行的 Adaptive-RAG 电商客服工作流」的成体系教程，共 **12 个部分、43 篇正文**（另有附录一章）：

- [教学教程总目录](tutorial/README.md)

配套材料：

- [Adaptive-RAG 工程化教学路线](00-engineering-tutorial.md)（单篇速览）
- [项目架构图与运行流程](17-architecture-flow.md)
- [教学文档写作蓝图](18-teaching-doc-blueprint.md)（维护者写作规范）
- [项目结构诊断](19-project-diagnosis.md)（维护者自用：历史问题与处理结果，不对读者承诺功能）
