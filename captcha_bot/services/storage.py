import json
import logging
from typing import Any, Dict, List, Optional

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

DEFAULT_CHAT_CONFIG: Dict[str, Any] = {
    "captcha_timeout": 300,
    "captcha_attempts": 2,
    "enabled": True,
}


class Storage:
    """
    Redis-backed storage with an in-memory fallback when Redis is unavailable.
    """

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._redis: Optional[aioredis.Redis] = None  # type: ignore[type-arg]
        self._fallback: Dict[str, str] = {}
        self._use_fallback = False

    async def connect(self) -> None:
        try:
            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
            await self._redis.ping()
            logger.info("Connected to Redis at %s", self._redis_url)
        except Exception as exc:
            logger.warning(
                "Redis unavailable (%s). Using in-memory fallback — data will be lost on restart.",
                exc,
            )
            self._use_fallback = True

    # ── Low-level helpers ────────────────────────────────────────────────────

    async def set(self, key: str, value: str, ex: Optional[int] = None) -> None:
        if self._use_fallback:
            self._fallback[key] = value
            return
        try:
            await self._redis.set(key, value, ex=ex)
        except Exception as exc:
            logger.error("Redis SET error: %s", exc)
            self._fallback[key] = value

    async def get(self, key: str) -> Optional[str]:
        if self._use_fallback:
            return self._fallback.get(key)
        try:
            return await self._redis.get(key)
        except Exception as exc:
            logger.error("Redis GET error: %s", exc)
            return self._fallback.get(key)

    async def delete(self, key: str) -> None:
        if self._use_fallback:
            self._fallback.pop(key, None)
            return
        try:
            await self._redis.delete(key)
        except Exception as exc:
            logger.error("Redis DEL error: %s", exc)
            self._fallback.pop(key, None)

    async def exists(self, key: str) -> bool:
        if self._use_fallback:
            return key in self._fallback
        try:
            return bool(await self._redis.exists(key))
        except Exception as exc:
            logger.error("Redis EXISTS error: %s", exc)
            return key in self._fallback

    async def keys(self, pattern: str) -> List[str]:
        if self._use_fallback:
            import fnmatch
            return [k for k in self._fallback if fnmatch.fnmatch(k, pattern)]
        try:
            return await self._redis.keys(pattern)
        except Exception as exc:
            logger.error("Redis KEYS error: %s", exc)
            return []

    # ── Chat config ──────────────────────────────────────────────────────────

    async def save_chat_config(self, chat_id: int, config: Dict[str, Any]) -> None:
        await self.set(f"chat_config:{chat_id}", json.dumps(config))

    async def get_chat_config(self, chat_id: int) -> Optional[Dict[str, Any]]:
        raw = await self.get(f"chat_config:{chat_id}")
        return json.loads(raw) if raw else None

    async def delete_chat_config(self, chat_id: int) -> None:
        await self.delete(f"chat_config:{chat_id}")

    async def is_chat_configured(self, chat_id: int) -> bool:
        return await self.exists(f"chat_config:{chat_id}")

    async def get_all_configured_chats(self) -> List[int]:
        ks = await self.keys("chat_config:*")
        return [int(k.split(":", 1)[1]) for k in ks]

    # ── Captcha (composite key: chat_id + user_id) ───────────────────────────

    async def save_captcha(
        self, chat_id: int, user_id: int, data: Dict[str, Any], ttl: int
    ) -> None:
        await self.set(f"captcha:{chat_id}:{user_id}", json.dumps(data), ex=ttl)

    async def get_captcha(self, chat_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        raw = await self.get(f"captcha:{chat_id}:{user_id}")
        return json.loads(raw) if raw else None

    async def delete_captcha(self, chat_id: int, user_id: int) -> None:
        await self.delete(f"captcha:{chat_id}:{user_id}")

    # ── Permanent mute ───────────────────────────────────────────────────────

    async def set_muted_forever(self, user_id: int) -> None:
        await self.set(f"muted_forever:{user_id}", "1")

    async def is_muted_forever(self, user_id: int) -> bool:
        return await self.exists(f"muted_forever:{user_id}")

    async def remove_muted_forever(self, user_id: int) -> None:
        await self.delete(f"muted_forever:{user_id}")

    async def get_muted_forever_count(self) -> int:
        return len(await self.keys("muted_forever:*"))

    async def get_muted_forever_list(self) -> List[str]:
        keys = await self.keys("muted_forever:*")
        return [k.split(":", 1)[1] for k in keys]
