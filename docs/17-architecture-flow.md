# Adaptive-RAG 项目架构图

这张图按照“启动检查 → 知识库准备 → 查询分析 → 智能路由 → 检索/工具执行 → 生成回答 → 观测统计”的运行顺序绘制。所有节点和降级路径均对应当前仓库中的实际模块。

## 一、系统主流程

```mermaid
flowchart TD
    START([🚀 启动 Adaptive-RAG]) --> CONFIG[⚙️ 加载 Settings 配置]
    CONFIG --> CHECK{🔍 检查系统依赖}

    CHECK --> DB{PostgreSQL / SQLite 可用?}
    CHECK --> REDIS{Redis 可用?}
    CHECK --> VECTOR{Qdrant 可用?}
    CHECK --> LLM{LLM API 可用?}

    DB -->|✅ 成功| DB_OK[初始化数据库 Session]
    DB -->|❌ 失败| DB_FALLBACK[使用本地 SQLite 或报告不可用]
    REDIS -->|✅ 成功| REDIS_OK[启用 Redis 缓存和分布式限流]
    REDIS -->|❌ 失败| REDIS_FALLBACK[降级为进程内缓存和限流]
    VECTOR -->|✅ 成功| VECTOR_OK[启用 Qdrant 向量存储]
    VECTOR -->|❌ 失败| VECTOR_FALLBACK[降级为内存向量存储]
    LLM -->|✅ 成功| LLM_OK[启用真实 LLM Provider]
    LLM -->|❌ 失败| LLM_FALLBACK[启用 Fake Provider / 受限模式]

    DB_OK --> INFRA[✅ 基础设施初始化完成]
    DB_FALLBACK --> INFRA
    REDIS_OK --> INFRA
    REDIS_FALLBACK --> INFRA
    VECTOR_OK --> RETRIEVAL_INIT
    VECTOR_FALLBACK --> RETRIEVAL_INIT
    LLM_OK --> AGENT_INIT
    LLM_FALLBACK --> AGENT_INIT

    INFRA --> KNOWLEDGE{📚 知识库状态}
    KNOWLEDGE -->|已有索引| LOAD[⚡ 加载已有知识库]
    KNOWLEDGE -->|索引不存在或版本变化| INGEST[🔨 执行知识库构建]

    INGEST --> PARSE[📄 解析知识文档]
    PARSE --> CLEAN[🧹 清洗文本和元数据]
    CLEAN --> CHUNK[✂️ 文档切块]
    CHUNK --> EMBED[🎯 生成 Embedding]
    EMBED --> BM25_BUILD[🔤 构建 BM25 索引]
    EMBED --> VECTOR_BUILD[🗄️ 写入 Qdrant / 内存向量库]
    BM25_BUILD --> RETRIEVAL_INIT[初始化 Hybrid Retriever]
    VECTOR_BUILD --> RETRIEVAL_INIT
    LOAD --> RETRIEVAL_INIT

    RETRIEVAL_INIT --> AGENT_INIT[🧠 初始化 LangGraph Agent]
    AGENT_INIT --> READY([✅ 系统就绪])

    READY --> INPUT[👤 用户输入问题]
    INPUT --> COMMAND{🔍 特殊命令?}
    COMMAND -->|stats| STATS[📊 显示路由、依赖和知识库统计]
    COMMAND -->|rebuild| REBUILD[🔄 重建知识库]
    COMMAND -->|quit| QUIT([👋 退出系统])
    COMMAND -->|普通查询| REQUEST[📨 创建 ChatRequest]
    REBUILD --> INGEST
    STATS --> INPUT

    REQUEST --> GUARDRAIL[🛡️ Guardrail 检查]
    GUARDRAIL -->|越界 / 注入| REFUSE[🚫 拒绝或转人工]
    GUARDRAIL -->|✅ 通过| INTENT[🏷️ 意图识别]

    INTENT --> COMPLEXITY[🧠 复杂度分析]
    COMPLEXITY --> ROUTER[🎯 Adaptive Router]
    ROUTER -->|Direct| DIRECT[⚡ 直接生成]
    ROUTER -->|Single / Multi| RETRIEVE[🔍 检索知识]
    ROUTER -->|Agent| PLAN[📋 规划工具任务]
    ROUTER -->|Refuse| REFUSE

    RETRIEVE --> STRATEGY{选择检索策略}
    STRATEGY -->|Single| HYBRID[🔄 Hybrid Retrieval]
    STRATEGY -->|Multi / Self-RAG| REWRITE[✍️ 查询改写和多路检索]
    HYBRID --> BM25[🔤 BM25 关键词检索]
    HYBRID --> DENSE[🎯 Dense 向量检索]
    BM25 --> RRF[⚖️ RRF 融合排名]
    DENSE --> RRF
    REWRITE --> HYBRID
    RRF --> RERANK{Cross-Encoder 可用?}
    RERANK -->|✅ 成功| CE[📈 精排候选片段]
    RERANK -->|❌ 失败| LEXICAL[🔤 词法排序降级]
    CE --> CONTEXT[📚 组装上下文和 Citation]
    LEXICAL --> CONTEXT
    CONTEXT --> GENERATE[🎨 生成回答]

    PLAN --> TOOL_CHECK[🔧 工具注册表和参数校验]
    TOOL_CHECK -->|查询工具| READ_TOOL[🔎 执行只读工具]
    TOOL_CHECK -->|写操作| RISK[⚠️ 风险等级判断]
    RISK -->|低风险 / 已授权| IDEMPOTENCY[🔑 幂等检查]
    RISK -->|高风险| CONFIRM[⏸️ 返回 pending_action 等待确认]
    CONFIRM -->|确认 token 无效| WAIT[❌ 拒绝执行]
    CONFIRM -->|确认 token 有效| IDEMPOTENCY
    IDEMPOTENCY --> EXECUTE[⚙️ 执行业务工具]
    READ_TOOL --> TOOL_RESULT[📦 ToolResult]
    EXECUTE --> TOOL_RESULT
    TOOL_RESULT --> GENERATE

    DIRECT --> GENERATE
    REFUSE --> OUTPUT
    WAIT --> OUTPUT
    GENERATE --> FAITHFUL{🧪 事实性检查}
    FAITHFUL -->|✅ 有依据| MEMORY[🧠 压缩会话记忆]
    FAITHFUL -->|❌ 可能幻觉| SELF_CORRECT[🔁 自纠错 / 重新生成]
    SELF_CORRECT -->|成功| MEMORY
    SELF_CORRECT -->|失败| REFUSE
    MEMORY --> OUTPUT[📤 返回答案、引用、工具状态和 metadata]
    OUTPUT --> METRICS[📈 更新延迟、token、路由和错误指标]
    METRICS --> INPUT
```

## 二、启动与依赖降级

```mermaid
flowchart LR
    A[加载 Settings] --> B{数据库}
    B -->|PostgreSQL| B1[生产连接池]
    B -->|SQLite| B2[本地开发/测试]
    B -->|失败| B3[readiness 失败]

    A --> C{Redis}
    C -->|成功| C1[缓存 + 分布式限流]
    C -->|失败| C2[内存缓存 + 进程内限流]

    A --> D{Qdrant}
    D -->|成功| D1[持久化向量索引]
    D -->|失败| D2[内存向量索引]

    A --> E{LLM}
    E -->|API 成功| E1[DeepSeek Provider]
    E -->|API 失败/测试环境| E2[Fake Provider]

    B1 --> READY[运行模式可观测]
    B2 --> READY
    C1 --> READY
    C2 --> READY
    D1 --> READY
    D2 --> READY
    E1 --> READY
    E2 --> READY
```

当前代码对应关系：

| 架构节点 | 代码位置 |
| --- | --- |
| Settings 配置 | `app/config/settings.py` |
| 生命周期与 API | `app/main.py`、`app/asgi.py` |
| 基础设施组合 | `app/services/container.py` 的 `build_infrastructure` |
| 检索组件组合 | `app/services/container.py` 的 `build_retrieval` |
| Redis 和限流 | `app/infra/redis_client.py`、`app/infra/rate_limit.py` |
| 知识库 ingest | `app/retrieval/ingest.py` |
| 文档解析清洗切块 | `app/retrieval/unstructured_parser.py`、`cleaning.py`、`chunking.py` |
| BM25 和向量检索 | `app/retrieval/bm25.py`、`vector.py` |
| Hybrid 和 RRF | `app/retrieval/hybrid.py`、`fusion.py` |
| Agent Graph | `app/agents/graph.py` |
| 路由和状态 | `app/agents/nodes/router.py`、`app/agents/state.py` |
| 工具权限与执行 | `app/tools/permissions.py`、`app/agents/nodes/executor.py` |
| 事实性检查 | `app/guardrails/hallucination.py`、`app/agents/nodes/faithfulness.py` |
| API 输出 | `app/api/routes/chat.py`、`app/schemas/chat.py` |
| 指标和日志 | `app/observability/` |

## 三、查询策略路由图

```mermaid
flowchart TD
    Q[用户查询] --> A[意图识别]
    A --> B[复杂度评分 0.0 - 1.0]
    B --> C[关系/实体密集度]
    C --> D[是否需要工具或多跳推理?]

    D -->|否，复杂度 < 0.4| DIRECT[Direct：直接回答]
    D -->|是，复杂度 0.4 - 0.7| SINGLE[Single：一次 Hybrid 检索]
    D -->|是，复杂度 > 0.7| MULTI[Multi：查询改写 + 多路检索]
    D -->|需要业务动作| AGENT[Agent：Planner + Executor]

    DIRECT --> CHECK[事实性和安全检查]
    SINGLE --> CHECK
    MULTI --> CHECK
    AGENT --> CHECK
    CHECK -->|成功| ANSWER[返回结构化答案]
    CHECK -->|失败| FALLBACK[降级、重试或转人工]
```

## 四、检索降级链路

```mermaid
flowchart TD
    START[开始检索] --> CACHE{缓存命中?}
    CACHE -->|是| RESULT[返回缓存结果]
    CACHE -->|否| HYBRID[执行 BM25 + Dense]
    HYBRID --> FUSION{融合成功?}
    FUSION -->|是| RERANK[执行 Reranker]
    FUSION -->|否| BM25_ONLY[仅 BM25 关键词检索]
    RERANK -->|成功| RESULT
    RERANK -->|模型不可用| LEXICAL[词法排序降级]
    LEXICAL --> RESULT
    BM25_ONLY --> RESULT
    RESULT --> GENERATION[交给生成节点]
    GENERATION --> FAITHFUL{答案有依据?}
    FAITHFUL -->|是| SUCCESS[✅ 成功]
    FAITHFUL -->|否| RETRY[重新检索/自纠错]
    RETRY -->|成功| SUCCESS
    RETRY -->|失败| REFUSE[❌ 拒答或转人工]
```

## 五、图例

| 图形/标记 | 含义 |
| --- | --- |
| `✅` | 当前步骤成功，继续主流程 |
| `❌` | 当前依赖或处理失败 |
| `⚡` | 低延迟或直接路径 |
| `🔄` | 重试、融合或循环 |
| `⏸️` | 暂停等待用户确认 |
| `⬇️` | 降级到成本更低、能力更弱的实现 |
| `🛡️` | 安全、边界或权限控制 |

这张图与 All-in-RAG 中“数据准备 → 索引构建 → 检索优化 → 生成评估 → 项目实战”的学习顺序对应，但把本项目特有的 Agent 路由、工具权限、确认机制和运行时降级也放进了同一张图中。
