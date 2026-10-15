# 考点索引 · 从 zero2Agent 的问题走进本项目

> 本索引按 [zero2Agent 面试通关目录](https://github.com/ranxi2001/zero2Agent/tree/main/learn-agent-interview) 的 17 个考察维度定位内容。正文已改为连续章节，采用「场景 → 机制 → 源码 → 取舍 → 边界」的讲述顺序；章节组织参考 [《深入理解 AI Agent》](https://github.com/bojieli/ai-agent-book/tree/main/book) 的按章阅读形式。文字与案例围绕本仓库独立撰写。

## 三章主线

| 章节 | 要回答的核心问题 | 对应代码 |
|---|---|---|
| [Chapter 1 · 从一句客服提问到一张可控的执行图](interview/chapter1.md) | 为什么同一入口要分五条路径？模型与程序如何分工？ | `app/agents/`、`app/retrieval/adaptive.py` |
| [Chapter 2 · 知识如何成为可核验的答案](interview/chapter2.md) | 文档如何变成证据？召回、精排、多跳各解决什么问题？ | `app/retrieval/`、`app/guardrails/hallucination.py` |
| [Chapter 3 · 当系统开始行动](interview/chapter3.md) | 工具如何约束权限、确认、重试、幂等和上下文预算？ | `app/tools/`、`app/memory/`、`app/core/retry.py` |

三章后面附有 [逐题追问资料](interview/README.md#逐题追问资料)。指标统一以历史离线记录 [eval/MEASURED.md](../eval/MEASURED.md) 为准。

## 17 个考察维度怎样对应三章

| zero2Agent 维度 | 从哪章开始 | 项目实现边界 |
|---|---|---|
| 01 架构选型 | [Chapter 1](interview/chapter1.md) | LangGraph、五策略路由、一次计划后顺序执行 |
| 02 工具管理 | [Chapter 3](interview/chapter3.md) | ToolRegistry、参数校验、Skill、HITL、MCP |
| 03 容错与鲁棒性 | [Chapter 3](interview/chapter3.md) | 可重试错误退避、读工具降级、护栏与忠实度 |
| 04 记忆与上下文 | [Chapter 3](interview/chapter3.md) | 会话存储与三级压缩；无长期向量记忆 |
| 05 评估与全局观 | [Chapter 2](interview/chapter2.md) → [Chapter 3](interview/chapter3.md) | 意图、检索、生成和 E2E 分任务评测 |
| 06 多智能体协作 | [Chapter 1](interview/chapter1.md) | 单图多节点；**无多 Agent 团队** |
| 07 工程化踩坑 | [Chapter 3](interview/chapter3.md) | 步数上限、流式风险、限流和观测 |
| 08 Prompt 工程与框架原理 | [Chapter 1](interview/chapter1.md) → [Chapter 3](interview/chapter3.md) | 模板、JSON schema、Skill |
| 09 RAG 与检索 | [Chapter 2](interview/chapter2.md) | 解析、切块、Hybrid、RRF、Cross-Encoder、多跳 |
| 10 训练、数据与模型优化 | [Chapter 2](interview/chapter2.md) | 知识清洗和评测集；**无微调训练** |
| 11 AI 代码分析与测试 | [Chapter 3](interview/chapter3.md) | 应用测试；**无代码生成/插桩平台** |
| 12 业务 AI 工程分析 | [Chapter 1](interview/chapter1.md) | 按客服任务成本和操作风险分流 |
| 13 简历项目拷打 | [Chapter 1](interview/chapter1.md) → [Chapter 3](interview/chapter3.md) | 用真实请求路径、数字与局限讲项目 |
| 14 各公司面试偏好 | [原题库章节](https://github.com/ranxi2001/zero2Agent/tree/main/learn-agent-interview/14-company-preferences) | 备考视角，非项目功能 |
| 15 概念考察 | [Chapter 3](interview/chapter3.md) | Tool、Skill、MCP 的分层；无 A2A/Harness 平台 |
| 16 Agent Infra | [Chapter 3](interview/chapter3.md) | 幂等与观测；无节点检查点和通用沙箱 |
| 17 AI Infra | [Chapter 3](interview/chapter3.md) | 模型 API 与本地检索模型；无 GPU 调度平台 |

**阅读建议**：先连续读三章，建立一条完整请求的因果链；再回到表格选维度，打开对应逐题问答。面试答题按「场景 → 决策 → 代码证据 → 失败边界」展开。`无` 表示当前仓库没有该能力，可以讨论设计思路，但不能作为项目成果。
