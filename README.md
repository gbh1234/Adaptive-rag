# Adaptive-RAG 电商客服

针对多条件政策咨询中证据不充分、回答缺乏依据的问题，实现具备自适应检索能力的电商客服系统。项目采用 FastAPI、LangGraph 和 React，通过动态检索路由、多轮证据补充与忠实度校验提升回答质量，支持政策引用、订单查询与人工确认。

意图识别支持 **TypeSafe Jev 与 DeepSeek 两种后端**：可使用 Jev 的结构化 choice 接口识别业务意图，由后续工作流完成检索、工具调用和回答；Jev 不可用时回退至原有分类链路。

> 当前适合本地演示、学习与工程验证。订单和物流来自演示数据，API 尚未验证请求中的 `user_id`，部署到公网前需要接入可信身份认证。

## 核心能力

- **Jev 意图识别**：支持 TypeSafe System One 接口，按预定义的 14 类业务意图返回标签、置信度与类别概率，使用 Pydantic 校验响应，并可通过规则覆盖层修正易混淆意图。
- **自适应路由**：结合意图与问题复杂度，选择直接回答、单轮检索、多轮检索、工具执行或拒答路径。
- **混合检索**：BM25 + 稠密向量召回，经 RRF 融合与可选 Cross-Encoder 精排。
- **证据校验**：查询改写、多轮补充检索、回答忠实度检查与自纠错。
- **文档入库**：支持 Markdown；安装可选依赖与系统工具后可解析 PDF、Office 等格式。
- **切块与引用**：按文档结构分段，普通文本采用 500 字符窗口、60 字符重叠；Unstructured 识别出的表格单独成块。切片携带标题、章节、来源等元数据。
- **工具执行**：提供订单等业务工具，包含权限检查、执行降级、人工确认与幂等机制，可接入 MCP。
- **聊天界面**：React 前端支持来源引用、本地会话管理和确认卡片；SSE 在答案完成校验后分段发送。
- **工程支持**：会话记忆压缩、结构化日志、Prometheus 指标、健康检查与自动化测试。

切片 ID 由文档路径和切片序号确定：相同路径和切分结果重复入库时可保持一致；文件迁移、内容编辑或切块策略变化后，不保证历史引用仍指向相同内容。

## 工作流程

```text
用户 → Web / HTTP API → 输入护栏
     → 意图识别（可选 Jev / 默认 DeepSeek）→ 复杂度路由
       ├─ 直接回答
       ├─ 检索 → 精排 → 必要时补充检索
       ├─ 规划 → 工具执行 / 人工确认
       └─ 拒答
     → 生成与忠实度检查 → 会话记忆 → 回答与引用
```

## 模型分工

| 组件 | 模型或实现 | 职责 |
| --- | --- | --- |
| 意图识别 | 可选 TypeSafe Jev，配置默认 `jev-1.13.0`；默认后端为 DeepSeek | 识别退款、退换货、物流、转人工等业务诉求 |
| 工作流中的 LLM | DeepSeek，默认 `deepseek-chat` | 复杂度判断、查询改写、任务规划、回答生成、忠实度检查与记忆摘要 |
| 稠密召回 | 本地 `BAAI/bge-small-zh-v1.5`，或配置的远程向量接口 | 将文本与查询编码为向量 |
| 精排 | 可选本地 `BAAI/bge-reranker-base` | 对召回片段重新评分 |

Jev 仅替换意图分类节点，切换后其余 LLM 节点仍使用 DeepSeek；未配置 DeepSeek 密钥时，其余流程使用离线演示逻辑。

## 本地快速开始

需要 Python 3.11+。Web 前端需要 Node.js 20.19+ 或 22.12+ 及 npm。本地默认使用 SQLite 和内存检索组件，无需先启动 Docker。

以下命令在项目根目录执行，适用于 Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m scripts.seed_demo
.\.venv\Scripts\python.exe -m uvicorn app.asgi:app --reload --host 127.0.0.1 --port 8000
```

已有 `.env` 时保留原文件，跳过复制步骤。macOS / Linux 可在创建虚拟环境后执行 `source .venv/bin/activate`，再使用 `python`、`pip` 与 `cp` 对应命令。

编辑本地 `.env`：

| 配置 | 说明 |
| --- | --- |
| `DEEPSEEK_API_KEY` | 启用 DeepSeek 工作流及默认意图分类；真实 API 调用可能产生费用 |
| `INTENT_BACKEND` | `deepseek`（默认）或 `jev`，只切换意图识别后端 |
| `JEV_API_KEY` | 使用 Jev 意图分类时需要，仅填写在本地 `.env` |
| `JEV_MODEL` | Jev 模型名，当前项目配置默认 `jev-1.13.0` |
| `DATABASE_URL` | 默认 `sqlite+aiosqlite:///./data/local/app.db` |
| `KNOWLEDGE_DIR` | 默认 `knowledge`，启动时入库 |
| `LOCAL_EMBEDDING_ENABLED` | 本地语义向量开关 |
| `CROSS_ENCODER_ENABLED` | 本地精排开关 |
| `REDIS_URL` / `QDRANT_URL` | 可选外部缓存与向量服务地址 |

不配置 DeepSeek 密钥时，系统使用离线演示逻辑，回答质量与真实模型模式不同。完整变量见 [配置参考](docs/07-configuration.md) 与 [.env.example](.env.example)。

### 启用 Jev 意图识别

在本地 `.env` 中修改以下配置，并填入自己的密钥；下面的值仅为占位示例：

```dotenv
INTENT_BACKEND=jev
JEV_API_KEY=your_jev_api_key
JEV_ENDPOINT=https://api.typesafe.ai/v1/systemone
JEV_MODEL=jev-1.13.0
JEV_TIMEOUT_SECONDS=10
JEV_MAX_RETRIES=2
JEV_INTENT_APPLY_OVERLAY=true

# 后续 LLM 节点及 Jev 失败后的原有分类链路仍使用此配置
DEEPSEEK_API_KEY=your_deepseek_api_key
```

修改后重启后端。恢复原有意图分类只需将 `INTENT_BACKEND` 改回 `deepseek`。

Jev 接入通过 HTTP 请求完成，无需额外安装专用 SDK。请求使用预定义的意图选项，响应经 Pydantic 校验后转换为统一的分类结果。密钥缺失、请求失败或响应不合法时，自动回退至原有 `IntentClassifier`；该链路优先使用配置的 DeepSeek，离线或模型调用失败时采用规则分类。可重试错误使用指数退避，`JEV_MAX_RETRIES` 在实现中表示最大尝试次数。

`JEV_INTENT_APPLY_OVERLAY` 控制 Jev 成功分类后的规则纠偏，默认开启；它不控制回退分类器自身的覆盖层。实现见 [Jev 分类器](app/agents/nodes/intent_jev.py) 与 [工作流接入](app/agents/graph.py)。

### 可选模型与文档解析

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[rerank]"
.\.venv\Scripts\python.exe -m pip install -e ".[docs]"
```

`rerank` 依赖用于本地稠密向量模型与 Cross-Encoder，模型默认分别为 `BAAI/bge-small-zh-v1.5` 和 `BAAI/bge-reranker-base`。首次加载可能下载权重；本地模型不可用时会降级，检索效果不能与完整模型配置等同。

`docs` 依赖用于 Unstructured 文档解析。PDF、OCR、Office 等格式还可能需要 Poppler、Tesseract（含中文语言包）、LibreOffice，具体见 [解析与检索说明](docs/15-ingest-and-retrieval.md)。

### 启动 Web 前端

保持后端运行，在另一个终端执行：

```powershell
cd frontend
npm ci
npm run dev
```

访问 [聊天页面](http://127.0.0.1:5173)。开发服务器将 `/api` 请求代理到本机 8000 端口。

运行 `npm run build` 后，FastAPI 会在检测到 `frontend/dist` 时从根路径提供页面。更多说明见 [前端 README](frontend/README.md)。

## 体验接口

- [交互式 API 文档](http://127.0.0.1:8000/docs)
- [进程健康检查](http://127.0.0.1:8000/api/v1/health)
- [依赖就绪检查](http://127.0.0.1:8000/api/v1/ready)

PowerShell 请求示例：

```powershell
$payload = @{
    message = "定制马克杯过了七天，但是有质量问题，可以退吗？"
    user_id = "u_demo"
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/chat" -Method Post -ContentType "application/json; charset=utf-8" -Body ([System.Text.Encoding]::UTF8.GetBytes($payload))
```

演示订单由 `python -m scripts.seed_demo` 显式创建，API 启动不会自动写入。演示用户为 `u_demo`：

| 订单 | 状态 | 商品 |
| --- | --- | --- |
| `ORD10001` | 已发货 | 降噪耳机 |
| `ORD10002` | 已签收 | 定制马克杯 |
| `ORD10003` | 已支付未发货 | T 恤 |

例如发送“取消订单 ORD10003”，系统可能返回 `pending_action`。确认时需带回响应中的 `session_id` 与 `pending_action.action_id`（放入 `confirm_action_id`）；Web 页面提供确认卡片。接口详情见 [API 参考](docs/06-api-reference.md)。

也可在后端运行时执行 `python -m app.cli` 使用终端客户端。

## Docker 运行

先准备本地 `.env`，再运行：

```powershell
docker compose up --build
```

Compose 启动 API、PostgreSQL、Redis 和 Qdrant，镜像构建时生成 Web 前端。启动后访问 [本机页面](http://127.0.0.1:8000)。

Compose 中的数据库口令和服务端口映射用于本地演示。面向公网部署前，需要替换演示口令、限制数据库与缓存端口访问，并接入身份认证、TLS 和持久化运维方案。详见 [部署说明](docs/11-deployment.md)。

## 测试与评测

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app eval tests
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m eval.runner --task retrieval
```

前端在 `frontend` 目录执行：

```powershell
npm test
npm run build
```

测试配置会隔离本地模型密钥，并使用测试数据库。独立运行评测时，应确认模型和网络配置；真实模型评测可能产生费用。

历史评测及其数据集、模型、日期和局限见 [实测记录](eval/MEASURED.md) 与 [评测报告](docs/14-evaluation-report.md)。历史结果不代表当前版本已重新验证，也不代表真实业务场景的效果保证。

### Jev 与 DeepSeek 意图对比

配置两种模型的本地密钥后，可在相同样本与相同规则覆盖设置下进行对比：

```powershell
.\.venv\Scripts\python.exe -m eval.compare_intent --backend both --limit 10 --no-overlay --output data/local/intent-comparison.json
```

报告包含准确率、P50/P95 延迟、回退次数与规则覆盖次数。`--no-overlay` 会关闭两种分类器的规则纠偏，便于观察模型分类结果；省略此参数可比较包含覆盖层的效果。当前数据集属于开发集，报告准确率包含回退样本，不能直接作为 Jev 独立模型的泛化能力结论。该命令会调用真实接口，可能产生费用；历史 DeepSeek 评测数字不应作为 Jev 的成绩。实现见 [意图对比脚本](eval/compare_intent.py)。

## 项目结构

```text
app/
  api/              HTTP API 与 SSE
  agents/           LangGraph 执行图与节点
  retrieval/        文档解析、切块、召回、融合与精排
  providers/        模型与向量服务适配
  tools/            业务工具、注册与权限
  mcp/              MCP 工具接入
  memory/           会话记忆与压缩
  guardrails/       输入与回答检查
  repositories/     数据访问与幂等
  observability/    日志与指标
frontend/           React + TypeScript 聊天界面
knowledge/          政策知识文档
scripts/            演示数据与入库脚本
alembic/            数据库迁移文件
tests/              单元、集成与端到端测试
eval/               评测数据集与执行器
docs/               技术手册与系统教程
```

## 当前边界与数据安全

- API 直接接受客户端传入的 `user_id`，尚未完成可信身份认证，不能作为真实用户身份边界。
- 订单和物流使用演示数据，未对接真实电商或承运商系统。
- 待确认操作保存在服务端进程内，默认保留 15 分钟；重启或多进程切换可能需要重新发起。
- Web 会话列表保存在浏览器本地，清除数据或更换浏览器后不会恢复。
- 知识库启动时全量入库，目前没有完整的增量删除流程；默认启动建表使用 `create_all`。
- `.env`、真实密钥、本地数据库、日志、用户上传文档和私人资料不得提交到 GitHub。示例配置只填写占位值。
- 使用外部模型或远程 MCP 时，应先确认发送内容中没有不应外传的用户信息。

更多边界见 [限制与路线图](docs/12-limitations.md) 和 [安全说明](docs/09-security.md)。

## 文档与贡献

- [技术手册目录](docs/README.md)
- [系统化工程教程](docs/tutorial/README.md)
- [架构与运行流程](docs/17-architecture-flow.md)
- [检索设计](docs/04-adaptive-rag.md)
- [贡献指南](CONTRIBUTING.md)

## 许可证

本项目使用 [MIT License](LICENSE)。

