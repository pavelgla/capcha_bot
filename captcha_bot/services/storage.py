import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

DEFAULT_CHAT_CONFIG: Dict[str, Any] = {
    "captcha_timeout": 300,
    "captcha_attempts": 2,
    "enabled": True,
    "welcome_text": None,
}

_EVENTS_CHANNEL = "captcha_events"
_UNMUTE_QUEUE = "unmute_queue"


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

    async def claim_captcha_slot(self, chat_id: int, user_id: int, ttl: int) -> bool:
        """Atomically claim a captcha slot. Returns True if claimed, False if already exists."""
        key = f"captcha:{chat_id}:{user_id}"
        if self._use_fallback:
            if key in self._fallback:
                return False
            self._fallback[key] = "{}"
            return True
        try:
            result = await self._redis.set(key, "{}", ex=ttl, nx=True)
            return result is not None
        except Exception as exc:
            logger.error("Redis SET NX error: %s", exc)
            return False

    async def save_captcha(
        self, chat_id: int, user_id: int, data: Dict[str, Any], ttl: int
    ) -> None:
        await self.set(f"captcha:{chat_id}:{user_id}", json.dumps(data), ex=ttl)

    async def get_captcha(self, chat_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        raw = await self.get(f"captcha:{chat_id}:{user_id}")
        return json.loads(raw) if raw else None

    async def delete_captcha(self, chat_id: int, user_id: int) -> None:
        await self.delete(f"captcha:{chat_id}:{user_id}")

    async def get_all_pending_captchas(self) -> List[Tuple[int, int, Dict[str, Any], int]]:
        """Return list of (chat_id, user_id, data, remaining_ttl_seconds) for all active captchas."""
        keys = await self.keys("captcha:*")
        result = []
        for key in keys:
            parts = key.split(":")
            if len(parts) != 3:
                continue
            chat_id, user_id = int(parts[1]), int(parts[2])
            data = await self.get_captcha(chat_id, user_id)
            if not data or not data.get("message_id"):
                continue
            ttl = 1
            if not self._use_fallback and self._redis:
                try:
                    ttl = await self._redis.ttl(key)
                    if ttl <= 0:
                        ttl = 1
                except Exception as exc:
                    logger.error("Redis TTL error: %s", exc)
            result.append((chat_id, user_id, data, ttl))
        return result

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

    # ── Statistics ───────────────────────────────────────────────────────────

    async def increment_stat(self, chat_id: int, stat: str) -> None:
        """Increment a counter: stat ∈ {joined, passed, failed, timeout}."""
        if self._use_fallback:
            key = f"stats:{chat_id}:{stat}"
            self._fallback[key] = str(int(self._fallback.get(key, "0")) + 1)
            return
        try:
            await self._redis.incr(f"stats:{chat_id}:{stat}")
        except Exception as exc:
            logger.error("Redis INCR error: %s", exc)

    async def get_stats(self, chat_id: int) -> Dict[str, int]:
        result = {}
        for stat in ("joined", "passed", "failed", "timeout"):
            raw = await self.get(f"stats:{chat_id}:{stat}")
            result[stat] = int(raw) if raw else 0
        return result

    # ── Pub/Sub events ────────────────────────────────────────────────────────

    async def publish_event(self, data: Dict[str, Any]) -> None:
        """Publish an event to the captcha_events channel."""
        if self._use_fallback:
            return  # Pub/Sub not available in fallback mode
        try:
            await self._redis.publish(_EVENTS_CHANNEL, json.dumps(data))
        except Exception as exc:
            logger.error("Redis PUBLISH error: %s", exc)

    async def subscribe_events(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Async generator yielding events from the captcha_events channel.
        Creates its own Redis connection so pub/sub doesn't block main client.
        """
        if self._use_fallback:
            return

        sub_redis = aioredis.from_url(self._redis_url, decode_responses=True)
        pubsub = sub_redis.pubsub()
        await pubsub.subscribe(_EVENTS_CHANNEL)
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        yield json.loads(message["data"])
                    except Exception:
                        pass
        finally:
            await pubsub.unsubscribe(_EVENTS_CHANNEL)
            await sub_redis.aclose()

    # ── Unmute queue ──────────────────────────────────────────────────────────

    async def push_unmute_request(self, chat_id: int, user_id: int) -> None:
        """Web panel calls this to request an unmute via the bot worker."""
        if self._use_fallback:
            return
        try:
            await self._redis.rpush(_UNMUTE_QUEUE, f"{chat_id}:{user_id}")
        except Exception as exc:
            logger.error("Redis RPUSH error: %s", exc)

    async def pop_unmute_request(self) -> Optional[Tuple[int, int]]:
        """Bot worker calls this to retrieve the next pending unmute."""
        if self._use_fallback:
            return None
        try:
            val = await self._redis.lpop(_UNMUTE_QUEUE)
            if val:
                chat_id_str, user_id_str = val.split(":", 1)
                return int(chat_id_str), int(user_id_str)
        except Exception as exc:
            logger.error("Redis LPOP error: %s", exc)
        return None

    # ── User accounts ─────────────────────────────────────────────────────────

    async def create_user(self, username: str, data: Dict[str, Any]) -> None:
        await self.set(f"user:{username}", json.dumps(data))
        if not self._use_fallback:
            try:
                await self._redis.sadd("users", username)
            except Exception as exc:
                logger.error("Redis SADD users error: %s", exc)

    async def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        raw = await self.get(f"user:{username}")
        return json.loads(raw) if raw else None

    async def update_user(self, username: str, data: Dict[str, Any]) -> None:
        await self.set(f"user:{username}", json.dumps(data))

    async def delete_user(self, username: str) -> None:
        await self.delete(f"user:{username}")
        if not self._use_fallback:
            try:
                await self._redis.srem("users", username)
            except Exception as exc:
                logger.error("Redis SREM users error: %s", exc)

    async def list_users(self) -> List[str]:
        if self._use_fallback:
            return []
        try:
            return list(await self._redis.smembers("users"))
        except Exception as exc:
            logger.error("Redis SMEMBERS users error: %s", exc)
            return []

    async def user_exists(self, username: str) -> bool:
        return await self.exists(f"user:{username}")

    # ── Telegram ID ↔ username ────────────────────────────────────────────────

    async def set_telegram_mapping(self, telegram_id: int, username: str) -> None:
        await self.set(f"telegram_to_user:{telegram_id}", username)

    async def get_user_by_telegram(self, telegram_id: int) -> Optional[str]:
        return await self.get(f"telegram_to_user:{telegram_id}")

    async def remove_telegram_mapping(self, telegram_id: int) -> None:
        await self.delete(f"telegram_to_user:{telegram_id}")

    # ── Chat ownership ────────────────────────────────────────────────────────

    async def set_chat_owner(self, chat_id: int, username: str) -> None:
        await self.set(f"chat_owner:{chat_id}", username)

    async def get_chat_owner(self, chat_id: int) -> Optional[str]:
        return await self.get(f"chat_owner:{chat_id}")

    async def add_user_chat(self, username: str, chat_id: int) -> None:
        if not self._use_fallback:
            try:
                await self._redis.sadd(f"user_chats:{username}", str(chat_id))
                return
            except Exception as exc:
                logger.error("Redis SADD user_chats error: %s", exc)

    async def remove_user_chat(self, username: str, chat_id: int) -> None:
        if not self._use_fallback:
            try:
                await self._redis.srem(f"user_chats:{username}", str(chat_id))
                return
            except Exception as exc:
                logger.error("Redis SREM user_chats error: %s", exc)

    async def get_user_chats(self, username: str) -> List[int]:
        if not self._use_fallback:
            try:
                members = await self._redis.smembers(f"user_chats:{username}")
                return [int(m) for m in members]
            except Exception as exc:
                logger.error("Redis SMEMBERS user_chats error: %s", exc)
        return []
