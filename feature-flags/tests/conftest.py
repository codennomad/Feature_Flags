"""
conftest.py — fixtures compartilhadas para toda a suite de testes.

Usa SQLite in-memory para testes de integração sem Docker.
O lifespan da app é substituído por um no-op para evitar conexões reais.
"""
from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import settings
from src.core.cache import FlagCache
from src.core.evaluation import EvaluationEngine
from src.infra.database import Base
from src.main import create_app
from tests.factories import FlagFactory


# ── Lifespan no-op para testes (evita conexões externas) ─────────────────────


@asynccontextmanager
async def _noop_lifespan(app: FastAPI):
    """Substitui o lifespan real em testes — sem conexões externas."""
    yield


# ── Event loop ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


# ── Tokens JWT ────────────────────────────────────────────────────────────────


def generate_jwt(
    sub: str = "user-123",
    role: str = "admin",
    exp: datetime | None = None,
    secret: str | None = None,
    algorithm: str = "HS256",
) -> str:
    payload = {
        "sub": sub,
        "role": role,
        "exp": exp or (datetime.now(timezone.utc) + timedelta(hours=1)),
    }
    return jwt.encode(payload, secret or settings.secret_key, algorithm=algorithm)


def generate_valid_jwt(sub: str = "user-123", role: str = "admin") -> str:
    return generate_jwt(sub=sub, role=role)


@pytest.fixture
def admin_token() -> str:
    return generate_valid_jwt(role="admin")


@pytest.fixture
def editor_token() -> str:
    return generate_valid_jwt(role="editor")


@pytest.fixture
def viewer_token() -> str:
    return generate_valid_jwt(role="viewer")


@pytest.fixture
def auth_headers(admin_token: str) -> dict:
    return {"Authorization": f"Bearer {admin_token}"}


# ── Banco de dados (SQLite async para testes unitários) ───────────────────────


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    """Engine SQLite in-memory para testes de integração sem Docker."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Sessão de banco de dados para uso direto em testes."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            yield session


# ── Cache ─────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def cache() -> FlagCache:
    """Cache sem warm-up (não pronto)."""
    return FlagCache()


@pytest_asyncio.fixture
async def loaded_cache() -> FlagCache:
    """Cache pré-carregado com flags de teste."""
    c = FlagCache()

    flag_data = FlagFactory.build(
        key="test-flag",
        default_value=False,
        environments={
            "production": {
                "enabled": True,
                "override": None,
                "rollout_percentage": 50,
                "rules": [
                    {
                        "id": str(uuid.uuid4()),
                        "name": "Enterprise Rule",
                        "priority": 1,
                        "conditions": [{"attribute": "plan", "operator": "eq", "value": "enterprise"}],
                        "condition_combinator": "AND",
                        "serve": True,
                    }
                ],
            }
        },
    )

    async def _load():
        return [flag_data]

    await c.warm_up(_load)
    return c


# ── EvaluationEngine ──────────────────────────────────────────────────────────


@pytest.fixture
def engine(loaded_cache: FlagCache) -> EvaluationEngine:
    return EvaluationEngine(cache=loaded_cache)


# ── App FastAPI para testes de integração ─────────────────────────────────────


@pytest_asyncio.fixture
async def async_client(loaded_cache: FlagCache) -> AsyncGenerator[AsyncClient, None]:
    """
    Cliente HTTP assíncrono que usa a app FastAPI sem servidor real.
    Injeta cache pré-carregado no estado da app e usa lifespan no-op.
    """
    app = create_app()
    # Substitui o lifespan real pelo no-op para evitar conexões a DB/Redis
    app.router.lifespan_context = _noop_lifespan
    app.state.cache = loaded_cache
    app.state.engine = EvaluationEngine(cache=loaded_cache)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client
