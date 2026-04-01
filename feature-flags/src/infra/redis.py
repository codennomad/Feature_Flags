"""
Redis connection pool + pub/sub listener para invalidação de cache.

Invalidação via pub/sub (NÃO polling).
Canal: settings.redis_pubsub_channel (default: feature_flags:invalidate)

Formato da mensagem publicada:
    {"flag_key": "...", "version": N, "action": "update|delete"}
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable

import redis.asyncio as aioredis

from src.config import settings

log = logging.getLogger(__name__)

_client: aioredis.Redis | None = None
_pubsub: aioredis.client.PubSub | None = None
_listener_task: asyncio.Task | None = None
_invalidation_handlers: list[Callable[[dict], None]] = []


async def connect() -> None:
    """Inicializa o pool de conexões Redis."""
    global _client
    _client = aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
    )
    # Valida conectividade
    await _client.ping()
    log.info("Conexão com Redis estabelecida")


async def disconnect() -> None:
    """Fecha conexões Redis e cancela o listener de pub/sub."""
    global _client, _pubsub, _listener_task

    if _listener_task and not _listener_task.done():
        _listener_task.cancel()
        try:
            await _listener_task
        except asyncio.CancelledError:
            pass

    if _client:
        await _client.aclose()

    log.info("Conexão com Redis encerrada")


def register_invalidation_handler(callback: Callable[[dict], None]) -> None:
    """Registra um callback para receber mensagens de invalidação."""
    _invalidation_handlers.append(callback)


async def publish_invalidation(flag_key: str, version: int, action: str) -> None:
    """Publica mensagem de invalidação de cache."""
    if _client is None:
        raise RuntimeError("Redis não conectado")
    message = json.dumps({"flag_key": flag_key, "version": version, "action": action})
    await _client.publish(settings.redis_pubsub_channel, message)
    log.debug("Invalidação publicada: flag_key=%s version=%s action=%s", flag_key, version, action)


async def start_listener() -> None:
    """Inicia o loop de escuta do pub/sub em background."""
    global _listener_task
    _listener_task = asyncio.create_task(_listen_for_invalidations())
    log.info("Listener pub/sub iniciado no canal: %s", settings.redis_pubsub_channel)


async def _listen_for_invalidations() -> None:
    """Loop de escuta — roda até cancelamento."""
    if _client is None:
        raise RuntimeError("Redis não conectado")

    pubsub = _client.pubsub()
    await pubsub.subscribe(settings.redis_pubsub_channel)

    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            try:
                data = json.loads(message["data"])
                for handler in _invalidation_handlers:
                    # Suporta handlers sync e async
                    if asyncio.iscoroutinefunction(handler):
                        asyncio.create_task(handler(data))
                    else:
                        handler(data)
            except (json.JSONDecodeError, Exception) as exc:
                log.warning("Erro ao processar mensagem pub/sub: %s", exc)
    except asyncio.CancelledError:
        pass
    finally:
        await pubsub.unsubscribe(settings.redis_pubsub_channel)
        await pubsub.aclose()
