"""
Configuração centralizada via Pydantic v2 BaseSettings.
Todas as variáveis de ambiente são lidas aqui — NUNCA espalhadas pelo código.
"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Banco de dados ────────────────────────────────────────────────────────
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/feature_flags",
        description="URL de conexão assíncrona com PostgreSQL (asyncpg)",
    )

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="URL de conexão com Redis",
    )
    redis_pubsub_channel: str = Field(
        default="feature_flags:invalidate",
        description="Canal Redis para invalidação de cache via pub/sub",
    )

    # ── JWT ───────────────────────────────────────────────────────────────────
    secret_key: str = Field(
        default="CHANGE_ME_IN_PRODUCTION_THIS_IS_NOT_SECURE",
        description="Chave secreta para assinar JWTs (HS256)",
    )
    jwt_algorithm: str = Field(
        default="HS256",
        description="Algoritmo JWT — NUNCA use 'none'",
    )
    access_token_expire_minutes: int = Field(default=60)

    # ── Rate limiting ─────────────────────────────────────────────────────────
    rate_limit_evaluation: str = Field(
        default="1000/minute",
        description="Limite de requisições no endpoint de avaliação",
    )

    # ── Aplicação ─────────────────────────────────────────────────────────────
    app_name: str = Field(default="Feature Flags API")
    app_version: str = Field(default="1.0.0")
    debug: bool = Field(default=False)
    environment: str = Field(default="production")

    # ── SQLAlchemy pool ───────────────────────────────────────────────────────
    db_pool_size: int = Field(default=20)
    db_max_overflow: int = Field(default=10)

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
