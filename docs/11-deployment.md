# 11 · 部署与运维

> 一句话：本地 SQLite 即可开发；Compose 里 Postgres 是硬依赖，Redis/Qdrant 软依赖；`.env` 不进镜像。

## 本章目录

1. [本地](#本地)
2. [Docker Compose](#docker-compose)
3. [生产检查清单](#生产检查清单)
4. [扩容、知识库、回滚](#扩容知识库回滚)

## 本地

SQLite + 内存向量，见 [02](02-getting-started.md)。

## Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

| 容器 | 作用 | API 依赖 |
|---|---|---|
| `postgres` | 订单/会话/幂等 | **硬**（healthy 后才起 API） |
| `redis` | 限流、缓存 | 软 |
| `qdrant` | 向量 | 软；连不上内存库 |
| `api` | FastAPI | 8000 |

### 代码摘要

```yaml
# docker-compose.yml
api:
  env_file: [.env]          # 密钥不打进镜像
  environment:
    DATABASE_URL: postgresql+asyncpg://cs:cs@postgres:5432/adaptive_rag_cs
    REDIS_URL: redis://redis:6379/0
    QDRANT_URL: http://qdrant:6333
    APP_ENV: production
  depends_on:
    postgres:
      condition: service_healthy
    redis:
      condition: service_started
    qdrant:
      condition: service_started
```

健康检查打 `http://127.0.0.1:8000/api/v1/health`。镜像非 root，先 COPY 再 `pip install .`。

## 生产检查清单

- [ ] `APP_ENV=production`，`LOG_LEVEL=INFO`
- [ ] `ADMIN_API_TOKEN` 已设
- [ ] `DATABASE_URL` 指向 Postgres，连接池已看过
- [ ] 真实 embedding 网关（否则对外以 BM25 为准）
- [ ] `pip install -e ".[rerank]"` 后重跑 retrieval，报告含 `hybrid+cross-encoder`
- [ ] `pip install -e ".[docs]"` 后用真实 PDF/扫描件验证 ingest；换切分后重跑 `--task retrieval`
- [x] `u_demo` / `anonymous` 全局读单已关闭
- [ ] 在可信网关认证用户并绑定 `user_id`；当前请求体仍可伪造身份，不可直接对公网开放
- [ ] liveness / readiness 分开（见 [08](08-reliability.md#探活)）
- [ ] 密钥不在日志、镜像、README
- [ ] 长期 Postgres 用 Alembic（现在启动仍 `create_all`）

## 扩容、知识库、回滚

API 无粘滞：session 在 DB。进程内限流多副本不共享 → 生产配 Redis。Graph 每进程编译一次。

改 `knowledge/` 文档后重启 API。`chunk_id` 在同一切分结果下稳定，Qdrant upsert 覆盖。无 CMS。生产 ingest 走 Unstructured；系统包需要 poppler、tesseract（`chi_sim`）、处理 Office 时的 libreoffice。换解析器后重跑 `--task retrieval`。

应用无状态（除 DB）。回滚镜像即可。Alembic `0002` 退货表，schema 回滚需显式 `downgrade`。

---

上一章 [10](10-evaluation.md) · 下一章 [12 · 限制](12-limitations.md)
