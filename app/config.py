from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_JWT_SECRET = "change-me-in-production"


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
    bedrock_model_id: str = "us.amazon.nova-pro-v1:0"

    # AWS Bedrock Embeddings (Titan v2)
    embedding_model_id: str = "amazon.titan-embed-text-v2:0"
    embedding_dimensions: int = 1024

    # Application
    debug: bool = False
    log_level: str = "INFO"
    environment: str = "development"  # development/staging/production
    cors_origins: list[str] = ["*"]  # Override in production
    enable_metrics: bool = True

    # Admin dashboard auth (self-signed JWT)
    jwt_secret: str = DEFAULT_JWT_SECRET
    jwt_expiry_hours: int = 24

    # Knowledge Graphs - Phase 1 uses YAML only
    use_db_graphs: bool = False

    @model_validator(mode="after")
    def _reject_default_jwt_secret_in_production(self) -> "Settings":
        if self.environment == "production" and self.jwt_secret == DEFAULT_JWT_SECRET:
            raise ValueError(
                "JWT_SECRET must be set to a strong random value in production. "
                "Refusing to start with the default placeholder."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
