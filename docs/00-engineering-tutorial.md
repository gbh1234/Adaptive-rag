# Adaptive-RAG 工程化教学路线

这套教程以本仓库为唯一代码事实来源，目标是让读者能够从零理解一个可运行的多智能体 RAG 客服系统。每章固定回答四个问题：**知识是什么、代码在哪里、为什么这样选、上线时如何思考**。

## 章节导航

1. [项目介绍](#1-项目介绍)
2. [问题建模与系统边界](#2-问题建模与系统边界)
3. [项目分层与依赖方向](#3-项目分层与依赖方向)
4. [配置、启动与生命周期](#4-配置启动与生命周期)
5. [文档处理与知识库](#5-文档处理与知识库)
6. [混合检索与自适应路由](#6-混合检索与自适应路由)
7. [Agent Graph 与状态设计](#7-agent-graph-与状态设计)
8. [工具、权限与人工确认](#8-工具权限与人工确认)
9. [模型供应商与降级策略](#9-模型供应商与降级策略)
10. [可靠性、安全与可观测性](#10-可靠性安全与可观测性)
11. [测试、评测与发布](#11-测试评测与发布)
12. [重构后的工程实践](#12-重构后的工程实践)

## 1. 项目介绍

> 本章目标：读者完成本章后，能够在 30 秒、2 分钟和 5 分钟三个时长内准确介绍项目；能够画出系统主链路；能够解释项目为什么需要 Adaptive-RAG、Hybrid Retrieval、Agent 和工程化护栏。

### 本章学习路径

```text
业务背景 → 用户问题 → 项目目标 → 系统边界 → 总体架构
    → 一次请求的完整链路 → 技术亮点 → 指标口径 → 项目介绍
```

### 前置知识

- 能阅读 Python 函数、类和异步代码。
- 了解 HTTP API、JSON、数据库和基本的 Docker 使用方法。
- 知道 LLM、Embedding、向量数据库和 RAG 的基本概念即可；具体原理会在后续章节展开。

### 1.1 项目背景

传统客服机器人通常只有“问题 → 向量检索 → 大模型回答”一条路径。这个方案在简单 FAQ 上有效，但面对真实电商客服场景会遇到四类问题：

1. 所有问题都走检索，简单问题延迟高，复杂问题又缺少多步推理。
2. 订单号、政策名等精确词适合关键词检索，口语化问题却更适合语义检索，单一召回方式不稳定。
3. 查询订单和修改订单的风险不同，模型不能直接决定是否执行退款、取消或地址修改。
4. 模型可能产生幻觉、误读不可信文档，线上还会遇到限流、超时、缓存失效和外部服务不可用。

因此，本项目实现一个面向电商客服的 Adaptive-RAG 多智能体系统：先识别意图和问题复杂度，再选择 Direct、Single、Multi 或 Agent 路径；需要知识时使用 BM25、向量检索、RRF 融合和可选精排；需要动作时通过工具注册表、权限校验、幂等和人工确认保护业务系统。

### 1.2 项目简介（项目简历版）

**项目名称：** Adaptive-RAG 多智能体电商客服系统

**项目定位：** 一个可运行、可测试、可评测、可部署的工程化 RAG 项目，用于演示如何把检索增强生成从 Demo 做成具备安全边界和可靠性设计的应用。

**核心技术：** Python 3.11、FastAPI、Pydantic、SQLAlchemy、Alembic、LangGraph、BM25、向量检索、Qdrant、Redis、Prometheus、Docker。

**主要能力：**

- 根据意图和复杂度自适应选择回答、检索或 Agent 工具路径。
- 使用 BM25 与向量检索组成 Hybrid Retrieval，并通过 RRF 融合结果。
- 支持查询订单、物流、售后和知识库等工具，并区分只读与写操作风险。
- 对高风险操作返回待确认动作，通过确认 token 才能执行。
- 使用护栏检测 Prompt Injection、越界问题和答案事实性。
- 提供 Fake Provider、单元测试、集成测试、E2E 测试和离线评测集。
- 支持本地内存后端，也支持 PostgreSQL、Redis、Qdrant 和真实 LLM 的生产部署。

**项目结果：** 项目重点不是堆叠模型调用，而是建立从输入、决策、检索、生成、工具执行到观测和评测的完整闭环。所有关键模块都能独立测试，外部依赖不可用时有明确的降级路径。

### 1.3 系统架构总览

```text
客户端
  ↓ HTTP / SSE
FastAPI API 层
  ↓ Schema 校验、请求上下文、错误处理
ChatService
  ↓
LangGraph Agent
  ├─ Guardrail：安全边界
  ├─ Intent：意图识别
  ├─ Router：复杂度与策略路由
  ├─ Retrieval：BM25 + Vector + RRF + Reranker
  ├─ Planner / Executor：工具规划、权限、幂等、确认
  ├─ Generate：答案生成
  ├─ Faithfulness：事实性检查与自纠错
  └─ Memory：上下文压缩与摘要
       ↓
Provider / PostgreSQL / Redis / Qdrant / Knowledge
```

### 1.4 3–5 分钟项目介绍稿

> 我介绍一下 Adaptive-RAG 多智能体电商客服项目。
>
> 这个项目要解决的是传统客服 RAG 只有一条固定链路的问题。简单 FAQ、订单查询、复杂售后和需要修改业务数据的请求，它们对检索、推理、权限和延迟的要求完全不同。如果所有请求都做一次向量检索，系统会出现延迟高、召回不准、工具越权和答案幻觉等问题。
>
> 我的设计是先把请求经过安全护栏，然后识别用户意图和问题复杂度，根据结果选择四种路径：Direct 直接回答，Single 做一次检索，Multi 做多路检索，Agent 则进入计划和工具执行流程。这样简单问题可以低延迟返回，复杂问题才消耗更多检索和模型资源。
>
> 在检索层，我没有只使用向量检索，而是同时维护 BM25 和向量索引。BM25 对订单号、政策名和专有词更准确，向量检索对口语化表达和同义改写更有优势。两路结果通过 Reciprocal Rank Fusion，也就是 RRF，统一成一个候选列表，再根据配置选择 Cross-Encoder 精排。Qdrant 用于生产向量存储，测试和本地开发可以退化到内存实现。
>
> 在 Agent 层，LangGraph 用显式状态和条件边表达流程。状态中会保存意图、路由策略、检索片段、引用、工具计划、工具结果和延迟信息。节点保持单一职责，护栏、意图、检索、执行、生成、事实性检查和记忆压缩都可以分别测试。
>
> 工具执行是这个项目和普通问答 Demo 的主要区别。查询订单属于只读操作，退款、取消订单或修改地址属于高风险写操作。模型只能提出 action proposal，真正执行前还要经过服务端的参数校验、权限检查、幂等指纹和用户确认。确认 token 不匹配时，系统不会执行写操作。
>
> 在工程化方面，项目使用 FastAPI 提供 HTTP 和 SSE 接口，Pydantic 定义输入输出契约，SQLAlchemy 和 Alembic 管理业务数据，Redis 用于缓存和限流，Prometheus 记录请求、检索和工具指标。DeepSeek 是真实模型适配，Fake Provider 用于测试，保证 pytest 不调用真实 LLM，也不依赖本地模型下载。
>
> 最后，项目不仅测试代码，还提供离线评测集，分别评估意图识别、召回率、引用和端到端行为。我的工程目标是让每次路由都有原因、每次失败都能降级、每次工具调用都可审计、每次评测都能复现。这也是这个项目从一个 RAG Demo 走向可维护系统的核心。

### 1.5 这一章的工程化思维

项目介绍不能只罗列技术名词。一个完整的介绍应按“业务背景 → 核心问题 → 解决方案 → 关键技术 → 工程保障 → 结果”展开。面试或汇报时，先说明为什么需要 Adaptive-RAG，再说明系统如何做路由、检索和工具隔离，最后用测试、评测、降级和可观测性证明它不是只能跑通的 Demo。

### 1.6 业务场景与用户问题

本项目模拟一个综合电商客服，而不是只回答固定 FAQ。用户问题可以分成四类：

| 场景 | 示例 | 主要依赖 | 风险 |
| --- | --- | --- | --- |
| 常识/政策问答 | “优惠券能不能和会员折扣叠加？” | 知识库检索 | 需要引用和事实性检查 |
| 订单查询 | “ORD10001 现在到哪了？” | 订单数据库、物流工具 | 只读，但要校验订单归属 |
| 复杂售后 | “定制商品超过七天但有质量问题怎么办？” | 多路检索、规则判断 | 需要组合多条政策 |
| 业务写操作 | “帮我取消还没发货的订单” | 订单工具、权限、幂等 | 必须人工确认 |

这四类问题的共同点是都来自自然语言，但它们的处理成本和错误代价完全不同。系统设计的第一原则是把“回答问题”和“执行动作”分开，把“低风险只读”和“高风险写入”分开。

### 1.7 项目目标与非目标

**项目目标：**

1. 用同一套 API 同时支持 FAQ、订单、物流、售后和工具执行。
2. 让简单请求保持低延迟，让复杂请求获得更多检索和推理预算。
3. 让答案有来源、有引用，无法确认时明确说明不确定性。
4. 让写操作具备权限、确认、幂等和审计边界。
5. 让开发环境不依赖真实 LLM、在线向量库或下载大型模型。
6. 让检索、路由和端到端质量都有可重复的测试和评测口径。

**项目非目标：**

- 不替代真实支付、仓储或物流系统；仓库中的 repository 和 tool 是可运行的演示实现。
- 不追求所有问题都由 Agent 自主完成；高风险问题应转人工或等待确认。
- 不把 Prompt 当作权限系统；权限永远由后端代码决定。
- 不承诺仅靠模型解决知识库脏数据、业务规则冲突和身份认证问题。

明确非目标可以避免项目介绍时夸大能力，也能帮助后续确定测试边界。

### 1.8 端到端案例：从问题到答案

以“定制马克杯过了 7 天但是有质量问题能退吗”为例，完整处理过程如下：

1. API 层用 `ChatRequest` 校验消息、用户和会话字段。
2. Guardrail 检查问题是否越界、是否包含 Prompt Injection。
3. Intent 节点判断为售后/退货类问题。
4. Adaptive Router 根据“定制商品、超过期限、质量问题”判断为复杂问题。
5. Query Rewriter 生成适合知识库检索的查询词。
6. BM25 找到“定制商品退货”和“质量问题退货”的精确规则。
7. 向量检索找到语义相近的售后政策，RRF 合并两路候选。
8. Reranker 对候选片段重新排序，并保留来源和 chunk id。
9. Generate 节点只能基于检索上下文生成答案，同时输出 citation。
10. Faithfulness 节点检查答案中的期限、条件和结论是否被上下文支持。
11. Memory 节点压缩会话历史，最终返回答案、引用、路由策略和耗时信息。

这个案例说明 Adaptive-RAG 的重点不是“多调用一次模型”，而是将复杂问题拆成可观测、可测试和可回退的步骤。

再看“帮我取消 ORD10003”这一类写操作：系统首先查询订单状态，确认订单尚未发货；然后返回 `pending_action` 和 `confirm_action_id`，而不是立即修改数据库。用户再次确认后，后端校验 token、用户和订单状态，生成幂等指纹，最后才执行取消动作。即使模型被提示注入，也无法绕过服务端的权限和确认逻辑。

### 1.9 技术亮点与可量化指标

介绍项目时，技术亮点要和问题一一对应：

| 问题 | 设计 | 可观察指标 |
| --- | --- | --- |
| 简单问题延迟高 | 复杂度路由 | 各策略请求量、P50/P95 延迟 |
| 专有词召回差 | BM25 + 向量 + RRF | Recall@K、MRR、Precision@1 |
| 长上下文成本高 | 预算和压缩 | 输入 token、压缩比例、LLM 成本 |
| 答案无依据 | citation + faithfulness | 引用覆盖率、事实性失败率 |
| 工具误执行 | 风险等级 + HITL | 待确认率、拒绝率、幂等冲突数 |
| 外部依赖不稳定 | timeout、retry、fallback | provider 错误率、降级次数 |

仓库中的 `eval/MEASURED.md` 和 `docs/14-evaluation-report.md` 用于记录实测结果。汇报时应说明数据集大小、模型版本、知识库版本和运行命令，不能只报一个脱离实验条件的百分比。

### 1.10 目录与能力映射

```text
app/
├── api/            HTTP 路由、依赖注入、健康检查
├── agents/         LangGraph 状态、节点和流程图
├── config/         Pydantic Settings 与环境配置
├── core/           错误码、异常、重试、ID、安全和流式上下文
├── guardrails/     越界、注入和事实性防护
├── infra/          Redis、限流等基础设施适配
├── memory/         token 预算、压缩和会话摘要
├── observability/  日志、trace context 和 Prometheus 指标
├── providers/      LLM、Embedding、Reranker 和 Fake provider
├── repositories/   SQLAlchemy 模型、数据库和订单仓储
├── retrieval/      解析、清洗、切块、索引、召回和精排
├── schemas/        API、Agent、检索和订单数据契约
├── services/       ChatService、容器和演示数据
└── tools/          工具协议、注册表、权限和业务工具
```

目录不是为了“看起来专业”，而是为了把变化隔离：换模型主要影响 `providers`，换向量库主要影响 `retrieval/vector.py`，调整 API 字段主要影响 `schemas` 和路由，业务流程变化主要影响 `agents` 和 `services`。

### 1.11 面试版、汇报版和简历版的差异

**简历版（30 秒）：**

> 负责设计并实现一个基于 FastAPI 和 LangGraph 的 Adaptive-RAG 电商客服系统。系统根据意图和复杂度动态选择 Direct、Hybrid Retrieval 或 Agent 工具路径，使用 BM25、向量检索、RRF 和可选 Cross-Encoder 提升召回质量，并通过工具风险分级、权限校验、幂等和人工确认保护订单写操作。项目同时提供 Fake Provider、分层测试和离线评测，支持本地内存后端和 PostgreSQL/Redis/Qdrant 生产后端。

**技术汇报版（2 分钟）：**

先讲业务问题：客服请求的复杂度和风险不同；再讲架构：护栏、意图、复杂度路由、混合检索、工具执行、事实性检查和记忆压缩；最后讲工程保障：协议化 provider、可选基础设施、测试隔离、评测集、指标和 Docker 部署。

**项目答辩版（5 分钟）：**

按“背景 → 痛点 → 方案 → 关键链路 → 技术取舍 → 安全边界 → 评测结果 → 后续演进”展开。面试官追问时，可以继续进入第二章讲分层，进入第五章讲召回，进入第八章讲工具权限，进入第十一章讲测试和评测。

### 1.12 本项目的核心工程判断

这个项目最重要的判断有五个：

1. **不是所有请求都需要 RAG。** 路由本身就是性能和成本优化。
2. **不是所有 RAG 都应该只用向量。** 业务系统中的 ID、编号和专有词需要词法召回。
3. **不是所有模型输出都可以执行。** 模型负责提出计划，后端负责验证和执行。
4. **不是所有失败都应该重试。** 可恢复的网络错误才重试，参数错误和权限错误应立即返回。
5. **不是所有指标都来自线上日志。** 召回和事实性需要固定评测集，延迟和错误需要生产指标。

### 1.13 本章小结

Adaptive-RAG 是一个以电商客服为场景的工程化 RAG 系统。它的学习重点有三层：第一层是 RAG 的数据、索引、检索和生成基础；第二层是根据问题复杂度进行路由，并通过 Agent 完成多步任务；第三层是把模型能力放进真实工程边界，通过 schema、权限、幂等、超时、降级、日志、指标和评测保证系统可用。

后续章节不会重新罗列技术名词，而是沿着本章的主链路逐层拆解：先讲分层和依赖，再讲启动与数据准备，然后进入检索、Agent、工具、安全和评测。每章都会同时给出概念、仓库代码、运行方式、选型对比和可验证的工程结果。

### 1.14 动手练习

1. 不看代码，只根据本章架构图说明一次 FAQ 请求和一次取消订单请求的差异。
2. 找到 `app/agents/graph.py`，标出 guardrail、retrieval、tool execution 和 faithfulness 节点。
3. 找到 `app/retrieval/hybrid.py`，回答为什么项目同时保留 BM25 和向量检索。
4. 找到 `app/tools/permissions.py`，说明模型为什么不能直接决定写操作。
5. 用自己的话完成一版 90 秒项目介绍，并至少说出一个指标、一个降级策略和一个安全边界。

练习的目的不是记住文件名，而是训练“问题—设计—代码—指标”的映射能力。能够完成这张映射，才算真正理解项目结构。

## 2. 问题建模与系统边界

### 知识

RAG 不是“把问题向量化后查数据库”。完整系统至少包含输入校验、意图识别、复杂度判断、检索、上下文压缩、答案生成、事实性检查和动作执行。系统边界要先定义：知识问答可以自动完成，订单查询需要数据库，退款等写操作需要权限和用户确认。

### 对应代码

- API 入口：`app/api/routes/chat.py`
- 请求和响应：`app/schemas/chat.py`
- 业务编排：`app/services/chat_service.py`
- 流程图：`app/agents/graph.py`
- 工具权限：`app/tools/permissions.py`

### 选型思考

FastAPI 适合提供异步 HTTP 和 SSE；Pydantic schema 把外部输入转换为稳定的内部契约；LangGraph 适合表达带条件分支、循环和状态的 Agent 流程。若系统只有单次检索和生成，直接服务函数会更简单，不应为了“多智能体”引入图框架。

### 工程化思维

先写清楚不可做的事情和失败时的行为，再写 Prompt。任何会改变订单状态的动作都必须有幂等键、权限判断和确认态；任何模型输出都必须经过 schema 解析，不能直接信任自由文本。

## 3. 项目分层与依赖方向

### 知识

分层的价值是限制变化传播。`api` 负责协议，`services` 负责用例，`agents` 负责决策流程，`retrieval` 负责召回，`providers` 负责外部模型，`repositories` 负责持久化，`schemas` 负责数据契约。

### 对应代码

- 领域常量和错误：`app/core/`
- 数据契约：`app/schemas/`
- 外部能力：`app/providers/`、`app/infra/`
- 持久化：`app/repositories/`
- 组合根：`app/services/container.py`

### 选型思考

这里使用显式 Python 包而不是微服务。当前系统的主要复杂度在流程和模型适配，拆成微服务会增加网络、部署和调试成本。只有当索引构建、在线推理和工具执行拥有不同伸缩周期时，才考虑拆分进程。

### 工程化思维

依赖方向应大体从外向内：路由调用服务，服务调用接口，基础设施实现接口。避免在 schema 中导入数据库模型，避免在 provider 中反向调用 API 路由。公共 `__init__.py` 只导出稳定接口，减少循环导入。

## 4. 配置、启动与生命周期

### 知识

配置不是散落在代码里的常量，而是运行环境的契约。开发、测试、生产需要不同的数据库、LLM 和检索后端。应用生命周期还要区分启动准备、请求处理和关闭清理。

### 对应代码

- 配置模型：`app/config/settings.py`
- FastAPI 生命周期：`app/main.py`
- 基础设施组合：`app/services/container.py`
- 数据库：`app/repositories/db.py`

`build_container()` 已拆为三个职责：

```python
engine, sessions, redis = await build_infrastructure(settings)
retriever, reranker, store = await build_retrieval(settings, redis)
container = await build_container(settings, seed=False)
```

`build_infrastructure` 只创建数据库和 Redis；`build_retrieval` 只负责知识库 ingest、BM25、向量检索和 reranker；`build_container` 负责把它们组装成聊天服务。

### 选型思考

生产启动默认不 seed 演示数据，避免每次重启写入业务库。数据库迁移应由 Alembic 或部署作业执行；知识库 ingest 应由独立任务执行，而不是绑定到 API 进程启动。

### 工程化思维

启动失败要尽早失败，降级要可见。健康检查应区分 liveness（进程活着）和 readiness（依赖可用），并返回当前 backend，例如 `memory`、`redis`、`qdrant`、`fake-llm`。

## 5. 文档处理与知识库

### 知识

检索质量首先取决于数据处理。流程通常是解析、清洗、切块、元数据补充、embedding、索引写入。切块太大导致噪声，太小会丢失上下文；chunk id 必须稳定，才能重复 ingest 时覆盖旧数据。

### 对应代码

- ingest：`app/retrieval/ingest.py`
- 清洗：`app/retrieval/cleaning.py`
- 切块：`app/retrieval/chunking.py`
- 解析：`app/retrieval/unstructured_parser.py`
- 知识文件：`knowledge/`

### 选型思考

项目保留 Markdown 标题切分作为确定性降级路径，同时可选 Unstructured 处理 PDF、Office 和 HTML。生产中使用结构化解析，测试中使用轻量实现，能减少模型下载和 CI 不稳定。

### 工程化思维

把 `chunk_id`、来源文件、章节、版本和更新时间写入 payload。评测集要固定知识库版本，否则召回指标无法复现。敏感信息清洗必须在 embedding 前完成，避免把 PII 写入向量库。

## 6. 混合检索与自适应路由

### 知识

关键词检索擅长订单号、政策名和专有词，向量检索擅长语义改写；RRF 可以在不强行校准分数的情况下融合两者。问题复杂度决定是否需要一次检索、多路检索或 Agent 工具调用。

### 对应代码

- BM25：`app/retrieval/bm25.py`
- 向量：`app/retrieval/vector.py`
- 融合：`app/retrieval/fusion.py`
- 混合检索：`app/retrieval/hybrid.py`
- 路由：`app/retrieval/adaptive.py`
- 自纠错：`app/retrieval/self_rag.py`

### 选型思考

RRF 比直接加权分数更稳健，因为 BM25 分数和 cosine 分数尺度不同。Qdrant 适合持久化和扩展；内存向量库适合测试和本地开发。Cross-Encoder 精排质量更好，但延迟和内存成本更高，因此作为可选后端。

### 工程化思维

每一步都要有预算：候选数量、最大 token、超时、重试次数。检索结果要返回 citation，而不是只返回拼接后的文本。缓存 key 必须包含查询、过滤条件和知识库版本。

## 7. Agent Graph 与状态设计

### 知识

Agent Graph 的核心不是节点数量，而是显式状态和可观测的转移。状态应保存用户消息、意图、策略、检索结果、计划、工具结果、引用和延迟信息。

### 对应代码

- 状态：`app/agents/state.py`
- 图构建：`app/agents/graph.py`
- 节点：`app/agents/nodes/`
- 状态 schema：`app/schemas/agent.py`

典型路径：

```text
guardrail -> intent -> complexity
                         ├─ direct -> generate
                         ├─ single/multi -> retrieve -> generate
                         └─ agent -> plan -> execute -> generate
                         generate -> faithfulness -> memory
```

### 选型思考

LangGraph 提供条件边和状态持久化语义；如果流程永远是线性的，普通函数链更容易维护。节点要保持单一职责，模型调用、工具执行和状态更新不要全部写进一个函数。

### 工程化思维

状态字段要区分“输入事实”和“模型推断”。模型推断必须带 confidence 或可验证结果；节点失败要有明确的 fallback 边，而不是依靠异常冒泡到 API。

## 8. 工具、权限与人工确认

### 知识

工具调用是 Agent 连接真实世界的边界。查询类工具通常是只读，退款、取消、修改地址等是写操作。写操作必须使用最小权限、参数校验、幂等和 HITL 确认。

### 对应代码

- 工具协议：`app/tools/base.py`
- 注册表：`app/tools/registry.py`
- 权限：`app/tools/permissions.py`
- 订单工具：`app/tools/order_tools.py`
- 执行节点：`app/agents/nodes/executor.py`

### 选型思考

使用注册表而不是在节点中写大量 `if/else`，便于增加工具、做权限检查和测试。工具返回统一的 `ToolResult`，让模型和 API 都能处理成功、失败、待确认三种状态。

### 工程化思维

权限判断不能交给模型。模型只能提出 action proposal，服务端根据用户、风险等级和确认 token 决定是否执行。幂等指纹应包含工具名和规范化参数，防止重试造成重复写入。

## 9. 模型供应商与降级策略

### 知识

模型是外部不稳定依赖。供应商接口、超时、限流、JSON 输出和 embedding 模型都可能变化，因此需要协议层和 provider 适配层。

### 对应代码

- 协议：`app/providers/base.py`
- DeepSeek：`app/providers/deepseek.py`
- Fake provider：`app/providers/fake.py`
- JSON 解析：`app/providers/json_parser.py`
- 重试：`app/core/retry.py`

### 选型思考

用 Protocol 定义最小能力，便于测试替换 Fake provider。对 JSON 输出采用“提取对象 + Pydantic 校验”，比直接 `json.loads` 更能应对模型包裹 Markdown 的情况。重试只针对可恢复状态，且必须设置退避和上限。

### 工程化思维

记录 provider、模型名、耗时、token 和失败类别，但不要记录完整用户隐私内容。模型降级后要在响应 metadata 中标记，方便运营判断质量变化。

## 10. 可靠性、安全与可观测性

### 知识

可靠性来自超时、重试、熔断、幂等、限流和可恢复的降级。安全重点包括 Prompt Injection、越权工具调用、PII 泄露和不可信检索内容。

### 对应代码

- 护栏：`app/guardrails/`
- 安全脱敏：`app/core/security.py`
- 限流：`app/infra/rate_limit.py`
- 日志和上下文：`app/observability/`
- 指标：`app/observability/metrics.py`

### 选型思考

请求级 trace id 和 request id 使用 contextvars 传递，避免把上下文参数塞进每个函数。Redis 可用于多实例限流，内存实现用于本地和测试。Prometheus 指标适合聚合延迟、错误和工具调用次数。

### 工程化思维

每个 fallback 都应有日志和指标；每个外部请求都应有 timeout；日志要默认脱敏。readiness 不能只返回 HTTP 200，还要说明依赖状态。安全规则应由服务端执行，Prompt 只作为额外防线。

## 11. 测试、评测与发布

### 知识

单元测试验证算法和边界，集成测试验证数据库和检索组合，端到端测试验证 API 行为；离线评测衡量召回、引用和答案质量。测试通过不等于线上质量达标。

### 对应代码

- 单测：`tests/unit/`
- 集成：`tests/integration/`
- E2E：`tests/e2e/`
- 评测：`eval/runner.py`、`eval/metrics.py`
- 数据集：`eval/dataset/`

### 选型思考

测试默认使用 Fake LLM 和内存后端，避免 CI 调真实模型、下载权重或产生费用。真实模型评测单独运行，并把模型版本、Prompt 版本和知识库版本写入报告。

### 工程化思维

发布门禁至少包括 Ruff、编译检查、pytest 和关键评测。每次修改切块、Prompt、embedding 或 reranker，都应重新跑对应评测任务。报告中的数字必须来自生成文件，不能手工填写。

## 12. 重构后的工程实践

本次整理落实了三项基础改进：

1. 项目内容已提升到 Git 根目录，避免嵌套仓库和 CI 根目录错误。
2. `app/services/container.py` 拆出 `build_infrastructure`、`build_retrieval`，降低组合根复杂度。
3. `build_container` 默认不写入演示数据，生产启动不再隐式 seed；需要演示数据时显式传入 `seed=True`。

推荐开发循环：

```bash
ruff format .
ruff check .
python -m compileall -q app eval
pytest -q
python -m eval.runner --task retrieval
```

当功能变复杂时，优先增加接口、状态和可观测性，再增加 Agent 节点。工程化 RAG 的核心是让每次决策都可解释、每次失败都可定位、每次评测都可复现。

