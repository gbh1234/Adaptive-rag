"""Environment-backed settings with a cached accessor."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    deepseek_api_key: SecretStr = SecretStr("")
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 3

    # Only classification changes; routing, planning and answers keep their LLM.
    intent_backend: Literal["deepseek", "jev"] = "deepseek"
    jev_api_key: SecretStr = SecretStr("")
    jev_endpoint: str = "https://api.typesafe.ai/v1/systemone"
    jev_model: str = "jev-1.13.0"
    jev_timeout_seconds: float = Field(default=10.0, gt=0)
    jev_max_retries: int = Field(default=2, ge=1, le=5)
    jev_intent_apply_overlay: bool = True

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
    knowledge_dir: str = "knowledge"
    unstructured_enabled: bool = True
    unstructured_strategy: str = "auto"
    unstructured_ocr_languages: str = "chi_sim+eng"
    unstructured_force: bool = False
    mcp_enabled: bool = True
    mcp_remote_url: str = ""

    @property
    def llm_configured(self) -> bool:
        return bool(self.deepseek_api_key.get_secret_value())

    @property
    def embedding_configured(self) -> bool:
        return bool(self.embedding_api_key.get_secret_value() and self.embedding_base_url)

    @property
    def local_embedding_configured(self) -> bool:
        """True when production will attempt to load the local dense model."""
        return self.local_embedding_enabled and (
            self.app_env != "testing" or self.local_embedding_force
        )

    @property
    def cross_encoder_configured(self) -> bool:
        """True when production path will attempt to load the Cross-Encoder.

        Tests stay on lexical fallback unless CROSS_ENCODER_FORCE is set.
        """
        return self.cross_encoder_enabled and (
            self.app_env != "testing" or self.cross_encoder_force
        )

    @property
    def unstructured_configured(self) -> bool:
        """True when ingest will attempt Unstructured partition.

        Tests stay on markdown heading split unless UNSTRUCTURED_FORCE is set.
        """
        return self.unstructured_enabled and (self.app_env != "testing" or self.unstructured_force)

    @property
    def redis_configured(self) -> bool:
        return bool(self.redis_url)

    @property
    def qdrant_configured(self) -> bool:
        return bool(self.qdrant_url)

    @property
    def use_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    """Used by tests after monkeypatching environment variables."""
    get_settings.cache_clear()
