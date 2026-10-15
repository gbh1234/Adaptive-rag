# 部署与上线

> 本文是第十二部分的第三篇正文，它讲清系统如何从一个环境迁移到另一个环境。全文分为五节，前两节讲本地开发与容器编排，中间两节讲依赖关系与上线检查，最后一节给出反例与练习。

---

## 一、本地开发

本地开发追求的是"零依赖启动"。本项目在本地默认使用 SQLite 存储订单与会话，使用内存库存储向量，因此开发者不需要启动任何外部服务就能跑通整个链路。

这条路径降低了入门门槛：开发者克隆代码、配置一个模型密钥，就能开始调试。

本地路径的代价是它与生产环境存在差异。SQLite 与 Postgres 在并发与类型上有差别，内存向量库与 Qdrant 在检索行为上也有差别。

> 因此本地跑通不等于生产可用，开发者必须理解这条差异，不能把本地行为直接当成线上行为。

---

## 二、容器编排

生产路径使用 Docker Compose，它定义了四个服务。

| 服务 | 职责 |
| --- | --- |
| `postgres` | 存储订单、会话与幂等记录 |
| `redis` | 限流与缓存 |
| `qdrant` | 向量存储 |
| `api` | 应用本体，暴露 8000 端口 |

这四个服务在依赖关系上并不相同，本项目据此把它们分为两类。

- `postgres` 是**硬依赖**：`api` 通过 `depends_on` 的 `service_healthy` 条件等待它健康后才启动，因为订单与幂等数据不可缺失。
- `redis` 与 `qdrant` 是**软依赖**：`api` 只等待它们启动，不等待它们健康，因为即使它们不可用，系统也能降级运行。

> 这种硬软之分，正是上一篇降级矩阵在部署层的体现。

`api` 服务通过 `env_file` 读取 `.env`，密钥因此不打进镜像。它还显式声明了数据库、缓存与向量库的连接地址，以及运行环境为生产。健康检查通过访问健康端点完成，确保容器编排系统能够判断服务是否真正就绪。

`docker-compose.yml` —— `api` 服务定义

```yaml
  api:
    build: .
    ports:
      - "8000:8000"
    env_file:
      - .env
    environment:
      DATABASE_URL: postgresql+asyncpg://cs:cs@postgres:5432/adaptive_rag_cs
      REDIS_URL: redis://redis:6379/0
      QDRANT_URL: http://qdrant:6333
      APP_ENV: production
      LOG_LEVEL: INFO
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_started
      qdrant:
        condition: service_started
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health')"]
      interval: 10s
      timeout: 5s
      retries: 10
```

`api` 服务的 `depends_on` 把 `postgres` 标为 `condition: service_healthy`，把 `redis` 与 `qdrant` 标为 `condition: service_started`，这就是"硬依赖等健康、软依赖只等启动"在编排层的写法。`env_file` 从 `.env` 注入密钥，`environment` 则把容器内的连接地址指向各服务名，健康检查通过访问 `/api/v1/health` 端点判断就绪。

`Dockerfile` —— 镜像构建指令

```dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN useradd --create-home --uid 1000 appuser
WORKDIR /app

COPY pyproject.toml README.md /app/
COPY app /app/app
COPY knowledge /app/knowledge
RUN pip install --upgrade pip && pip install ".[rerank]" \
    && mkdir -p /app/data/local \
    && chown -R appuser:appuser /app

USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.asgi:app", "--host", "0.0.0.0", "--port", "8000"]
```

镜像基于 `python:3.11-slim`，先创建一个非 root 的 `appuser`，再拷贝 `pyproject.toml`、`app` 与 `knowledge` 目录并安装含精排的依赖。`USER appuser` 与末尾的 `CMD` 表明容器以非特权用户运行 `uvicorn`，`EXPOSE 8000` 与 `api` 服务的端口映射一致。

---

## 三、依赖关系与降级

把部署与降级连起来看，可以得到一张完整的依赖关系图。

| 依赖 | 类型 | 挂了会怎样 |
| --- | --- | --- |
| 数据库 | 硬依赖 | 整个服务不可用 |
| Redis | 软依赖 | 限流与缓存退回进程内 |
| Qdrant | 软依赖 | 向量退回内存库 |
| 嵌入与精排模型 | 软依赖 | 退回更弱的能力 |

这里有一条关于扩缩容的说明。本项目的 API 是无状态的，会话状态存在数据库里，因此可以水平扩容而不需要粘滞会话。

> 但进程内的限流与缓存不共享，所以生产环境应当配置 Redis，让限流与缓存在多个副本之间一致。

---

## 四、上线检查清单

上线之前，系统需要逐项核对一批配置。本项目在 `docs/11-deployment.md` 中给出了一份检查清单，它覆盖了环境、密钥、数据库、模型、依赖与安全几个方面。

| 方面 | 核对项 |
| --- | --- |
| 环境 | 生产模式，日志级别 INFO |
| 密钥 | 设置管理令牌，否则管理接口返回未授权 |
| 数据库 | 连接地址指向 Postgres，核对连接池参数 |
| 模型 | 配置真实嵌入网关；安装精排依赖并重跑检索评测 |
| 文档解析 | 安装依赖，用真实 PDF 或扫描件验证入库 |
| 安全 | 隔离演示账号全库权限，密钥不进日志、镜像、说明文件 |

这份清单里有几处需要特别留意。其一，系统应当配置真实的嵌入网关，否则对外应当以关键词检索为准。其二，精排依赖应当安装，并重跑检索评测，确认报告里出现 `hybrid+cross-encoder`。

> 这份清单的意义在于把"上线"从一次感觉变成一次核对。读者应当养成习惯：每次上线前逐项打勾，而不是凭经验判断。

---

## 五、反例与练习

假设系统直接把开发环境的配置搬到生产：数据库仍是 SQLite，向量仍是内存库，精排依赖没有安装。上线之后，系统在并发稍高时就会出现数据库锁等待；重启一次，内存向量全部丢失，检索能力归零；精排缺失，检索质量退回融合前的水平。

> 这个反例说明，部署不是把代码拷过去，而是把一整套依赖与配置正确地对齐。

本部分的练习有两项。

- **第一项，区分依赖。** 读者应说明本项目里哪些依赖是硬依赖、哪些是软依赖，并说明依据。
- **第二项，执行检查。** 读者应对照上线检查清单，逐项核对一个假想的部署配置，指出哪些项没有满足。

> 本篇是全书技术部分的收尾。读者读完本篇，就完成了从"文本如何变成向量"到"系统如何上线"的完整旅程。

附录将提供术语表、环境变量、练习答案、源码阅读顺序与完整测评数据表，供读者查阅与复习。

---

**本篇涉及的源码：** `docker-compose.yml`、`Dockerfile`
