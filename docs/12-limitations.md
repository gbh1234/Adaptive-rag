# 12 · 限制与路线图

> 一句话：文档必须和代码一致。下面是明确没做完或故意没做的；已补上的不要再写成缺口。

## 本章目录

1. [限制（对照代码）](#限制对照代码)
2. [已补上](#已补上不要再写成缺口)
3. [不计划堆料](#不计划用简历堆料补的)
4. [下一阶段](#建议的下一阶段)

## 限制（对照代码）

| 项 | 现状 | 看哪里 |
|---|---|---|
| Embedding | 生产本地 `BAAI/bge-small-zh-v1.5`；加载失败才 hash | `app/providers/embeddings.py` |
| Rerank | 本地 Cross-Encoder `BAAI/bge-reranker-base`；未装权重时词面降级 | `app/providers/reranker.py` |
| Tokenizer | 128k 启发式，非官方 tokenizer | `app/memory/budget.py` |
| 订单/物流 | 种子 + 仓储，无承运商 | `app/services/seed.py` |
| 知识库更新 | 启动全量 ingest，无删除 API | `app/retrieval/ingest.py` |
| 文档解析 | 生产 Unstructured（PDF/Office/HTML/图）；缺依赖或 testing 降级 Markdown 标题切分。OCR/复杂表格不保证 | `app/retrieval/unstructured_parser.py` |
| 文本清洗 | 切块后 NFKC/空白/硬换行；精确去重；近重复只日志。不做 embedding 聚类，不改中文数字。「七天」保持「七天」 | `app/retrieval/cleaning.py` |
| 知识库 PII | 仅非 `.md` 入库前 `mask_pii`；政策 Markdown 与日志脱敏分开 | `app/core/security.py` |
| 多租户 | 无；`user_id` 字符串隔离 | `OrderRepository.get_visible_order` |
| 身份认证 | API 直接接受请求体 `user_id`，尚未验证身份；生产需可信网关绑定用户身份 | `app/api/routes/chat.py` |
| 演示数据 | 启动不自动写入；显式运行 `python -m scripts.seed_demo`，可重复执行 | `scripts/seed_demo.py` |
| 启动迁移 | `create_all`，Alembic 有版本但默认不跑 | `alembic/versions/` |

## 已补上、不要再写成缺口

| 能力 | 代码 |
|---|---|
| SSE token | `ChatService.stream` 在答案完成校验后分段发送；生成期间客户端显示等待状态 |
| MCP 可执行 | `app/mcp/runtime.py`、`MCPToolProxy.execute` |
| Skill 按需加载 | `match_skill` + Planner 收缩目录 |
| 执行层 Fallback | `execute_with_fallback` |
| 忠实度 LLM 自纠错 | `self_correct_answer` |
| Unstructured 多格式 ingest | `app/retrieval/unstructured_parser.py`（testing / 缺 extra 降级 Markdown） |
| 切块后清洗与精确去重 | `app/retrieval/cleaning.py` |

## 不计划用「简历堆料」补的

- Kafka / Celery：没有出站异步作业
- Elasticsearch：政策规模内存 BM25 够
- 为 Hybrid 强行融合 hash 向量：评测会拉低 Hit@1
- 用词面 overlap 冒充 Cross-Encoder
- Unstructured Cloud / Transform MCP
- embedding 聚类丢掉近重复政策条款

## 建议的下一阶段

1. 换更大 embedding 后另跑 `--task retrieval`，不要把 small 的数字写成 bge-m3。
2. 本集上 RRF 未超过仅 small；若要证明融合有用，需要换集合或拆失败 case。
3. 增加可信身份认证，并由服务端绑定 `user_id`，不能直接信任请求体。
4. 启动走 Alembic。
5. 知识库增量删除与 `policy_version` 过滤。

改行为时同步改本章、[10](10-evaluation.md) 与 [14 · 测评报告](14-evaluation-report.md)。README 只保留入口和实测表。

---

上一章 [11](11-deployment.md) · [返回目录](README.md)
