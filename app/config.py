from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database (optional for Phase 1)
    database_url: str | None = None
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle: int = 3600

    # AWS Bedrock
    aws_region: str = "us-east-2"
    bedrock_model_id: str = "anthropic.claude-3-5-haiku-20241022-v1:0"

    # AWS Bedrock Embeddings (Titan v2)
    embedding_model_id: str = "amazon.titan-embed-text-v2:0"
    embedding_dimensions: int = 1024

    # Application
    debug: bool = False
    log_level: str = "INFO"
    environment: str = "development"  # development/staging/production
    cors_origins: list[str] = ["*"]  # Override in production
    enable_metrics: bool = True

    # Knowledge Graphs - Phase 1 uses YAML only
    use_db_graphs: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
