# 02 · 快速开始

> 目标：本机 5 分钟内 `POST /api/v1/chat` 成功。默认 **SQLite + 内存向量**，不强制 Docker。

## 本章目录

1. [环境与安装](#环境与安装)
2. [启动时发生了什么](#启动时发生了什么)
3. [探活与第一问](#探活与第一问)
4. [演示订单与 HITL](#演示订单与-hitl)
5. [测试](#测试)
6. [Web 前端](#web-前端)

## 环境与安装

- Python **3.11+**（验证过 3.12）
- 可选 `DEEPSEEK_API_KEY`（没有则进入离线演示模式，显示检索原文或可核对的业务状态）

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
# 本地 bge-small 召回 + Cross-Encoder 精排：pip install -e ".[rerank]"
# Unstructured 解析 PDF/Office/HTML/图片：pip install -e ".[docs]"
# 系统包：poppler、tesseract（含 chi_sim）、Office 还需 libreoffice
# 首次请求会加载 BAAI/bge-small-zh-v1.5（~90MB）与 BAAI/bge-reranker-base（国内可设 HF_ENDPOINT）
cp .env.example .env
python -m scripts.seed_demo  # 需要演示订单时执行一次，可安全重跑
```

`.env` 最小集：

```bash
APP_ENV=development
DATABASE_URL=sqlite+aiosqlite:///./data/local/app.db
DEEPSEEK_API_KEY=sk-...   # 可选，演示质量依赖它
```

不要提交 `.env`。

```bash
uvicorn app.asgi:app --reload --port 8000
python -m app.cli
```

入口：`app/asgi.py` → `create_app()`。CLI 连已启动的 API 做终端一问一答（`/y` 确认 HITL，`/quit` 退出），不重复加载模型。

## 启动时发生了什么

### 要点

`lifespan` 调用 `build_container`：建表、ingest `knowledge/`、编译 Graph。演示订单由上面的显式命令创建，API 启动不自动 seed。

### 代码摘要

```python
# app/main.py
@asynccontextmanager
async def lifespan(app: FastAPI):
    container = await build_container(get_settings())  # ingest + 编译图
    app.state.container = container
    try:
        yield
    finally:
        await container.aclose()
```

```python
# scripts/seed_demo.py
async with factory.begin() as session:
    await seed_demo_data(session)  # 只补缺失的演示行
```

## 探活与第一问

```bash
curl -s localhost:8000/api/v1/health
curl -s localhost:8000/api/v1/ready
curl -s localhost:8000/api/v1/chat \
  -H 'content-type: application/json' \
  -d '{"message":"定制马克杯过了7天但是有质量问题能退吗","user_id":"u_demo"}'
```

- `/health`：进程活着  
- `/ready`：数据库硬依赖；Redis/Qdrant/LLM 只报告  

期望：`trace_id`、`strategy`（多为 `multi` 或 `single`）、回答提到定制/质量。

## 演示订单与 HITL

| 订单号 | 状态 | 商品 |
|---|---|---|
| `ORD10001` | 已发货 | 降噪耳机 |
| `ORD10002` | 已签收 | 定制马克杯 |
| `ORD10003` | 已支付未发货 | T 恤 |

先运行 `python -m scripts.seed_demo`，然后使用用户 `u_demo`。取消未发货会返回 `pending_action`：

```bash
curl -s localhost:8000/api/v1/chat \
  -H 'content-type: application/json' \
  -d '{"message":"取消订单ORD10003","user_id":"u_demo"}'
# 把上次响应的 session_id 和 pending_action.action_id 一起填回：
curl -s localhost:8000/api/v1/chat \
  -H 'content-type: application/json' \
  -d '{"message":"确认取消","user_id":"u_demo","session_id":"sess_...","confirm_action_id":"act_..."}'
```

机制见 [05 · HITL](05-agents-and-tools.md#hitl-与幂等)。

## 测试

```bash
pytest -q
python -m eval.runner --task retrieval
```

`tests/conftest.py` 会清空 `DEEPSEEK_API_KEY`，避免误打真实接口。

## Web 前端

保持 API 在 8000 端口运行，另开终端：

```bash
cd frontend
npm ci
npm run dev
```

打开 `http://127.0.0.1:5173`。Vite 会将 `/api` 代理到 8000 端口；生产构建由 `npm run build` 生成，FastAPI 检测到 `frontend/dist` 后会在 `/` 提供页面。前端实现和本地会话存储限制见 [`frontend/README.md`](../frontend/README.md)。

下一步：[11 · 部署](11-deployment.md)、[06 · API](06-api-reference.md)。

---

上一章 [01](01-overview.md) · 下一章 [03 · 架构](03-architecture.md)
