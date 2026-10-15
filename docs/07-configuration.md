# 07 · 配置参考

> 一句话：所有运行时配置在 `Settings`；密钥用 `SecretStr`；测试用 conftest 覆盖环境变量。

## 本章目录

1. [加载方式](#加载方式)
2. [应用 / 模型 / 存储 / Agent](#变量表)
3. [能力开关](#能力开关)

对应：`app/config/settings.py`、`.env.example`、`tests/conftest.py`。

## 加载方式

### 代码摘要

```python
# app/config/settings.py
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    deepseek_api_key: SecretStr = SecretStr("")
    deepseek_model: str = "deepseek-chat"  # API 上的 DeepSeek-V3

    @property
    def llm_configured(self) -> bool:
        return bool(self.deepseek_api_key.get_secret_value())

    @property
    def cross_encoder_configured(self) -> bool:
        return self.cross_encoder_enabled and (
            self.app_env != "testing" or self.cross_encoder_force
        )
```

`get_settings()` 有 `lru_cache`。测试改环境后必须 `clear_settings_cache()`。

`APP_ENV=development|testing|production`。`tests/conftest.py` 强制 `APP_ENV=testing` 并清空 LLM/Embedding key；测试环境不下载 Cross-Encoder。

## 变量表

### 应用

| 变量 | 默认 | 说明 |
|---|---|---|
| `APP_ENV` | `development` | 日志细节、admin 是否强制 token |
| `LOG_LEVEL` | `INFO` | 生产建议 INFO |
| `API_V1_PREFIX` | `/api/v1` | |

### 模型

| 变量 | 默认 | 说明 |
|---|---|---|
| `DEEPSEEK_API_KEY` | 空 | 空则 Fake LLM |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | OpenAI 兼容 |
| `DEEPSEEK_MODEL` | `deepseek-chat` | |
| `LLM_TIMEOUT_SECONDS` | `30` | 读超时 |
| `LLM_MAX_RETRIES` | `3` | 仅可重试错误 |
| `EMBEDDING_API_KEY` / `BASE_URL` | 空 | 两者都有才走远程 OpenAI 兼容接口 |
| `EMBEDDING_MODEL` | `bge-small-zh-v1.5` | 仅远程网关使用 |
| `EMBEDDING_DIM` | `512` | 须与向量库一致；本地 `bge-small-zh-v1.5` 是 512 |
| `LOCAL_EMBEDDING_ENABLED` | true | 生产召回走本地 `BAAI/bge-small-zh-v1.5` |
| `LOCAL_EMBEDDING_MODEL` | `BAAI/bge-small-zh-v1.5` | sentence-transformers 双塔；精排是另一套 `bge-reranker-*` |
| `LOCAL_EMBEDDING_DEVICE` | 空（自动 cuda/mps/cpu） | |
| `LOCAL_EMBEDDING_FORCE` | false | testing 下仍加载权重 |
| `CROSS_ENCODER_ENABLED` | true | 生产精排走 Cross-Encoder |
| `CROSS_ENCODER_MODEL` | `BAAI/bge-reranker-base` | sentence-transformers CrossEncoder |
| `CROSS_ENCODER_DEVICE` | 空（自动 cuda/mps/cpu） | |
| `CROSS_ENCODER_MAX_LENGTH` | 512 | |
| `CROSS_ENCODER_FORCE` | false | testing 下仍加载权重（评测用） |
| `UNSTRUCTURED_ENABLED` | true | 生产 ingest 走 Unstructured |
| `UNSTRUCTURED_STRATEGY` | `auto` | PDF/图片：`auto` / `fast` / `hi_res` / `ocr_only` |
| `UNSTRUCTURED_OCR_LANGUAGES` | `chi_sim+eng` | Tesseract 语言包，`+` 或逗号分隔 |
| `UNSTRUCTURED_FORCE` | false | testing 下仍走 Unstructured（需 `.[docs]`） |
| `MCP_ENABLED` | true | 注册本地 MCP 工具 |
| `MCP_REMOTE_URL` | 空 | 非空则加 HTTP 远程 MCP |

### 存储

| 变量 | 本地默认 | 说明 |
|---|---|---|
| `DATABASE_URL` | sqlite 文件 | Postgres：`postgresql+asyncpg://` |
| `DB_POOL_SIZE` / `MAX_OVERFLOW` / `POOL_TIMEOUT` | 5 / 10 / 30 | 仅非 SQLite |
| `REDIS_URL` | 空 | 空则进程内限流/缓存 |
| `QDRANT_URL` | 空 | 空或连不上则内存向量 |
| `QDRANT_COLLECTION` | `cs_knowledge` | |

### 检索与 Agent

| 变量 | 默认 | 说明 |
|---|---|---|
| `RETRIEVAL_TOP_K_SIMPLE` | 3 | single |
| `RETRIEVAL_TOP_K_COMPLEX` | 8 | multi |
| `RRF_K` | 60 | 论文默认，非调参结论 |
| `RERANK_TOP_N` | 5 | |
| `MAX_RETRIEVAL_HOPS` | 3 | Self-RAG |
| `MAX_AGENT_STEPS` | 8 | |
| `MAX_TOOL_CALLS` | 6 | |
| `TOKEN_BUDGET` | 128000 | |
| `COMPRESS_SOFT_RATIO` | 0.50 | |
| `COMPRESS_HARD_RATIO` | 0.70 | |
| `AUTO_COMPACT_RATIO` | 0.85 | |
| `RATE_LIMIT_PER_MINUTE` | 60 | 按 `user_id` |
| `RETRIEVAL_CACHE_TTL_SECONDS` | 60 | 政策问 |
| `ADMIN_API_TOKEN` | 空 | 生产必填才能开 admin |
| `KNOWLEDGE_DIR` | `knowledge` | 支持 `.md` `.pdf` `.docx` `.pptx` `.html` 与常见图片后缀 |

完整模板：仓库根目录 `.env.example`。

## 能力开关

| 条件 | 行为 |
|---|---|
| 无 DeepSeek key | `FakeLLMProvider` |
| 无 embedding 网关且本地稠密模型未加载 | `HashEmbeddingProvider`（CI 占位） |
| 未装 `.[rerank]` 或权重加载失败 | 词面 rerank 降级；评测不出现 `hybrid+cross-encoder` |
| 未装 `.[docs]`、testing 且未 `UNSTRUCTURED_FORCE` | Markdown 标题切分降级；非 `.md` 跳过 |
| Hugging Face 超时（国内） | 设 `HF_ENDPOINT=https://hf-mirror.com` |
| `MCP_ENABLED=false` | 只有 15 个业务工具 |
| 无 Redis | 进程内限流/缓存 |
| 无 Qdrant | 内存向量 |

容器组装：`app/services/container.py` 的 `build_container`。

---

上一章 [06](06-api-reference.md) · 下一章 [08 · 可靠性](08-reliability.md)
