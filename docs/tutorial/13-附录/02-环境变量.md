# 环境变量

本表汇总本项目的主要配置项，它们定义在 `.env.example` 中，并由 `app/config/settings.py` 读取。

读者在部署或调试时，可以对照本表确认配置。每一组变量先说明分组用途，再以表格列出关键项、默认值与作用。

---

## 一、应用基础

`APP_ENV` 决定了本地模型是否加载、演示账号是否可用等行为。

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `APP_ENV` | `development` | 指定运行环境，取值有 `development`、`testing`、`production` |
| `APP_NAME` | `adaptive-rag-cs` | 应用名 |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `API_V1_PREFIX` | `/api/v1` | 接口前缀 |

`app/config/settings.py` —— `Settings` 类与基础字段

```python
class Settings(BaseSettings):
    """Environment-backed runtime configuration.

    Secrets stay in SecretStr so accidental str() / logs do not leak keys.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["development", "testing", "production"] = "development"
    app_name: str = "adaptive-rag-cs"
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"
```

`Settings` 继承 `BaseSettings`，`model_config` 指定从 `.env` 读取、按 utf-8 解码并忽略多余键，环境变量名与字段名大小写不敏感地对应。四个基础字段就是上表里的 `APP_ENV`、`APP_NAME`、`LOG_LEVEL` 与 `API_V1_PREFIX`，字段默认值与表格中的"默认值"一列完全一致。

---

## 二、大模型

这一组变量控制真实模型的接入。

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | 必须配置 | 模型密钥，必须配置才能走真实模型 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | 接口地址 |
| `DEEPSEEK_MODEL` | `deepseek-chat` | 模型名 |
| `LLM_TIMEOUT_SECONDS` | 30 秒 | 读取超时 |
| `LLM_MAX_RETRIES` | 3 | 最大重试次数 |

---

## 三、稠密召回

`EMBEDDING_API_KEY` 与 `EMBEDDING_BASE_URL` 同时配置时，系统优先使用远程嵌入接口。

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `EMBEDDING_API_KEY` | — | 与 `EMBEDDING_BASE_URL` 同时配置时，系统优先使用远程嵌入接口 |
| `EMBEDDING_BASE_URL` | — | 与 `EMBEDDING_API_KEY` 同时配置时，系统优先使用远程嵌入接口 |
| `EMBEDDING_MODEL` | `bge-small-zh-v1.5` | 远程模型名 |
| `EMBEDDING_DIM` | 512 | 向量维度 |
| `LOCAL_EMBEDDING_ENABLED` | 启用 | 控制是否启用本地嵌入 |
| `LOCAL_EMBEDDING_MODEL` | `BAAI/bge-small-zh-v1.5` | 本地模型名 |
| `LOCAL_EMBEDDING_DEVICE` | 留空则自动选择 | 指定设备 |
| `LOCAL_EMBEDDING_FORCE` | 关闭 | 控制测试环境是否强制加载本地模型 |

---

## 四、精排

这一组变量控制 Cross-Encoder 精排与模型下载来源。

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `CROSS_ENCODER_ENABLED` | 启用 | 控制是否启用精排 |
| `CROSS_ENCODER_MODEL` | `BAAI/bge-reranker-base` | 精排模型名 |
| `CROSS_ENCODER_DEVICE` | 留空则自动选择 | 指定设备 |
| `CROSS_ENCODER_MAX_LENGTH` | 512 | 最大序列长度 |
| `CROSS_ENCODER_FORCE` | 关闭 | 控制测试环境是否强制加载精排模型 |
| `HF_ENDPOINT` | — | 模型下载镜像，国内可设为 `https://hf-mirror.com` |

`app/config/settings.py` —— 大模型、稠密召回与精排字段

```python
    deepseek_api_key: SecretStr = SecretStr("")
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 3

    embedding_api_key: SecretStr = SecretStr("")
    embedding_base_url: str = ""
    embedding_model: str = "bge-small-zh-v1.5"
    embedding_dim: int = 512
    local_embedding_enabled: bool = True
    local_embedding_model: str = "BAAI/bge-small-zh-v1.5"
    local_embedding_device: str = ""
    local_embedding_force: bool = False

    cross_encoder_enabled: bool = True
    cross_encoder_model: str = "BAAI/bge-reranker-base"
    cross_encoder_device: str = ""
    cross_encoder_max_length: int = 512
    cross_encoder_force: bool = False
```

密钥类字段一律声明为 `SecretStr`，这样即使被误打印也不会泄露明文，这也是"密钥不进仓库"提醒在代码层的体现。其余字段的默认值对应大模型、稠密召回与精排三张表，其中 `embedding_model` 与 `cross_encoder_model` 的取值就是文档反复强调的 `bge-small-zh-v1.5` 与 `BAAI/bge-reranker-base`。

---

## 五、文档解析

这一组变量控制 Unstructured 解析行为。

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `UNSTRUCTURED_ENABLED` | 启用 | 控制是否启用 Unstructured 解析 |
| `UNSTRUCTURED_STRATEGY` | `auto` | 解析策略 |
| `UNSTRUCTURED_OCR_LANGUAGES` | `chi_sim+eng` | OCR 语言 |
| `UNSTRUCTURED_FORCE` | 关闭 | 控制测试环境是否强制启用 |

---

## 六、MCP

这一组变量控制 MCP 工具的注册。

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `MCP_ENABLED` | 启用 | 控制是否注册本地 MCP 工具 |
| `MCP_REMOTE_URL` | — | 配置后，系统会额外注册一个远程 HTTP 工具 |

---

## 七、持久化

这一组变量控制数据库、缓存与向量库的连接。

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `DATABASE_URL` | — | 数据库连接地址；本地默认使用 SQLite，容器编排中使用 Postgres |
| `REDIS_URL` | 留空则退回进程内实现 | 缓存与限流地址 |
| `QDRANT_URL` | 留空则使用内存库 | 向量库地址 |
| `QDRANT_COLLECTION` | `cs_knowledge` | 集合名 |

---

## 八、检索参数

这一组变量控制检索链路的候选与跳数。

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `RETRIEVAL_TOP_K_SIMPLE` | 3 | 简单路径的候选数 |
| `RETRIEVAL_TOP_K_COMPLEX` | 8 | 多跳路径的候选数 |
| `RRF_K` | 60 | RRF 的常数 |
| `RERANK_TOP_N` | 5 | 精排保留数 |
| `MAX_RETRIEVAL_HOPS` | 3 | 最大检索跳数 |

---

## 九、记忆参数

这一组变量控制上下文预算与三级压缩阈值。

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `TOKEN_BUDGET` | 128000 | 上下文预算 |
| `COMPRESS_SOFT_RATIO` | 0.50 | 软截断阈值 |
| `COMPRESS_HARD_RATIO` | 0.70 | 硬压缩阈值 |
| `AUTO_COMPACT_RATIO` | 0.85 | 自动压缩阈值 |

---

## 十、智能体与限流

这一组变量控制智能体步数、限流、缓存与管理接口。

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `MAX_AGENT_STEPS` | 8 | 最大智能体步数 |
| `MAX_TOOL_CALLS` | 6 | 最大工具调用次数 |
| `RATE_LIMIT_PER_MINUTE` | 60 | 每分钟限流额度 |
| `RETRIEVAL_CACHE_TTL_SECONDS` | 60 秒 | 检索缓存存活时间 |
| `ADMIN_API_TOKEN` | — | 管理接口令牌，生产模式必须配置 |
| `DB_POOL_SIZE` | 5 | 连接池大小 |
| `DB_MAX_OVERFLOW` | 10 | 连接池溢出上限 |

`app/config/settings.py` —— 持久化、检索、记忆与限流字段

```python
    database_url: str = "sqlite+aiosqlite:///./data/local/app.db"
    redis_url: str = ""
    qdrant_url: str = ""
    qdrant_collection: str = "cs_knowledge"

    retrieval_top_k_simple: int = 3
    retrieval_top_k_complex: int = 8
    rrf_k: int = 60
    rerank_top_n: int = 5
    max_retrieval_hops: int = 3

    token_budget: int = 128_000
    compress_soft_ratio: float = 0.50
    compress_hard_ratio: float = 0.70
    auto_compact_ratio: float = 0.85

    max_agent_steps: int = 8
    max_tool_calls: int = 6

    rate_limit_per_minute: int = 60
    retrieval_cache_ttl_seconds: int = 60
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    admin_api_token: SecretStr = SecretStr("")
```

这一段覆盖持久化、检索、记忆与限流四组变量：`database_url` 的默认值是本地 SQLite，`redis_url` 与 `qdrant_url` 留空时系统分别退回进程内实现与内存库，正是"留空则降级"的开关。`token_budget` 写成 `128_000` 与文档中的 `128000` 是同一个值，`compress_*_ratio` 与 `auto_compact_ratio` 则是三级压缩阈值的来源。

---

## 十一、使用提醒

读者在配置时应当注意三条。

- **密钥不进仓库**：`.env` 应当被忽略，密钥不应出现在日志、镜像或说明文件里。
- **生产必须显式配置**：管理令牌、数据库地址与真实嵌入网关都应当在生产环境明确设置。
- **模型名要与代码一致**：稠密路是 `bge-small-zh-v1.5`，精排是 `bge-reranker-base`，不要写成 `bge-m3` 或 Cohere。

> 三条提醒分别对应密钥安全、生产可运行与模型名一致三个常见坑。

---

**本篇涉及的源码：** `app/config/settings.py`
