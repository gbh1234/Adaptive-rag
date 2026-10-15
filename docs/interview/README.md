# Adaptive-RAG 电商客服 · 项目面试书

一个客服系统从回答政策问题走向执行订单操作，需要同时解决三个问题：**如何选择执行路径，如何找到可靠证据，如何约束有副作用的行动。** 本书沿一次请求的生命周期展开，而不是把技术名词排成一张问答表。

章节结构参考 [《深入理解 AI Agent：设计原理与工程实践》的正文目录](https://github.com/bojieli/ai-agent-book/tree/main/book)：从具体场景出发，逐步说明机制、源码和工程取舍。面试维度来自 [zero2Agent](https://github.com/ranxi2001/zero2Agent/tree/main/learn-agent-interview)，所有项目描述以本仓库为准。两份参考资料提供组织思路；本书的内容和案例独立写成。

## 目录

| 章节 | 从一个问题开始 | 读完应该能解释 |
|---|---|---|
| [Chapter 1 · 从一句客服提问到一张可控的执行图](chapter1.md) | 同一个入口为什么要走不同路径？ | 意图、复杂度、LangGraph、Planner 与 Executor |
| [Chapter 2 · 知识如何成为可核验的答案](chapter2.md) | 政策文档怎样变成有依据的回答？ | ingest、切块、混合检索、精排、多跳与忠实度 |
| [Chapter 3 · 当系统开始行动](chapter3.md) | 取消订单时如何避免越权和重复执行？ | Tool、Skill、MCP、HITL、幂等、降级、记忆与评测 |

[17 个 zero2Agent 考察维度与章节对应表](../16-interview-bagu-map.md) 可以用来按岗位查漏。历史指标请核对 [实测记录](../../eval/MEASURED.md) 与 [测评报告](../14-evaluation-report.md)；三章中的指标都不是实时线上成绩。

## 逐题追问资料

读完正文后，再用这些材料练习面试官的连续追问。它们按问题组织，保留「简短回答 + 源码细节」的形式，与三章叙述互为补充。

| 问题库 | 内容 |
|---|---|
| [工作流、规划、意图与评测](01-langgraph-planning-intent.md) | 状态机、Planner/Executor、流式、重试、意图数字 |
| [Adaptive-RAG 与检索](02-adaptive-rag-chunking-hybrid.md) | 解析切块、改写、Hybrid、多跳、召回指标 |
| [精排、记忆、Skill/MCP 与护栏](03-rerank-memory-skill-mcp.md) | 数字口径、上下文预算、工具接入与幻觉治理 |

> **答题原则**：每个能力先指出它解决的业务失败，再指向实现文件，最后说明测试或评测口径。没有实现的多智能体团队、模型训练、节点检查点和 GPU 平台，应当明确说出边界。
