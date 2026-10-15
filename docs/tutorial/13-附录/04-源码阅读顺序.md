# 源码阅读顺序

本附录给出按调用顺序阅读本项目代码的建议路径。

读者如果直接打开 `app/` 目录，会看到上百个文件，很容易迷失。按本附录的顺序阅读，读者可以顺着一条请求的生命周期，把每个文件放在它该在的位置上。

> 阅读代码的要诀是"顺着一条请求走"，而不是"逐个文件翻"。

---

## 一、先读入口与配置

阅读的第一步是找到系统的入口。

读者应先读 `app/main.py`，理解应用如何启动、生命周期如何管理、中间件如何绑定 trace_id。接着读 `app/config/settings.py`，理解全部配置项的来源与默认值。

> 这两份文件回答了"系统如何被启动、如何被配置"。

---

## 二、再读容器与编排

第二步是理解系统如何组装。

读者应读 `app/services/container.py`，它负责构建基础设施、检索组件与图。接着读 `app/services/chat_service.py`，它负责限流、事务与调用已编译的图。

> 这两份文件回答了"各个组件在哪里被创建、被谁调用"。

---

## 三、接着读图与状态

第三步是理解处理流程。

读者应读 `app/agents/state.py`，理解状态包含哪些字段；再读 `app/agents/graph.py`，理解节点如何连接、条件边如何分派。

这两份文件是理解整条链路的骨架。读者应当在这里画一张图，把九个节点与它们之间的边标出来。

---

## 四、然后按节点顺序深入

第四步是逐个理解节点。读者应按图中的顺序阅读。

- `app/agents/nodes/guardrail.py` 讲安全。
- `app/agents/nodes/intent.py` 与 `app/agents/nodes/intent_overlay.py` 讲意图。
- `app/agents/nodes/router.py` 与 `app/retrieval/adaptive.py` 讲路由。
- `app/agents/nodes/retrieval.py` 讲检索。
- `app/agents/nodes/planner.py` 与 `app/agents/nodes/executor.py` 讲规划与执行。
- `app/agents/nodes/generate.py` 讲生成。
- `app/agents/nodes/faithfulness.py` 讲自纠错。
- `app/agents/nodes/memory.py` 讲压缩。

---

## 五、再深入检索与工具内部

第五步是理解两个最复杂的子系统。

检索侧，读者应按**"解析、清洗、切块、入库、召回、融合、精排、改写、自纠错"**的顺序读 `app/retrieval/` 目录：`unstructured_parser.py`、`cleaning.py`、`chunking.py`、`ingest.py`、`bm25.py`、`vector.py`、`hybrid.py`、`fusion.py`、`reranker.py`、`query_rewrite.py`、`self_rag.py`。

工具侧，读者应先读 `app/tools/base.py` 与 `app/tools/registry.py`，再读 `app/tools/permissions.py` 与 `app/repositories/idempotency.py`，最后读各业务工具。

---

## 六、最后读保障层

第六步是理解支撑系统运行的部分。

读者应读 `app/core/retry.py` 理解重试，读 `app/guardrails/` 理解护栏，读 `app/memory/` 理解预算与压缩，读 `app/observability/` 理解日志与指标，读 `app/providers/` 理解模型接入。

---

## 七、配套阅读评测

在阅读代码的同时，读者应当读 `eval/` 目录。

- `eval/metrics.py` 给出指标定义。
- `eval/runner.py` 给出评测流程。
- `eval/dataset/` 给出数据集。

> 读评测代码能帮助读者理解"代码里的每一个设计，最终是为哪个数字服务"。

---

## 八、测试是最好的文档

最后，读者不应忽略 `tests/` 目录。

本项目的单元测试覆盖了 RRF、路由、护栏、压缩、权限、Skill、MCP、执行降级与自纠错。这些测试往往比注释更清楚地说明了每个模块的预期行为。

读者在读完一个模块后，可以打开对应的测试，确认自己理解了它的边界条件。

---

## 九、推荐的一条最短路径

如果读者时间有限，可以走一条最短路径。

| 顺序 | 文件 | 作用 |
| --- | --- | --- |
| 1 | `app/agents/graph.py` | 建立全局印象 |
| 2 | `app/agents/state.py` | 理解数据流 |
| 3 | `app/retrieval/hybrid.py` 与 `app/retrieval/adaptive.py` | 理解检索与路由两个核心 |
| 4 | `eval/runner.py` | 理解验证方式 |

> 走完这条路径，读者就能对本项目有一个可讲述的整体把握。
