"""Unit tests for services/storage.py using in-memory fallback (no Redis needed)."""
import pytest

from services.storage import Storage


def _make_storage() -> Storage:
    """Return a Storage instance that uses the in-memory fallback."""
    s = Storage("redis://localhost:6379")
    s._use_fallback = True
    return s


# ── Basic key/value ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_set_and_get():
    s = _make_storage()
    await s.set("key", "value")
    assert await s.get("key") == "value"


@pytest.mark.asyncio
async def test_get_missing_returns_none():
    s = _make_storage()
    assert await s.get("nonexistent") is None


@pytest.mark.asyncio
async def test_delete():
    s = _make_storage()
    await s.set("key", "value")
    await s.delete("key")
    assert await s.get("key") is None


@pytest.mark.asyncio
async def test_exists():
    s = _make_storage()
    assert not await s.exists("key")
    await s.set("key", "1")
    assert await s.exists("key")


# ── Captcha helpers ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_save_and_get_captcha():
    s = _make_storage()
    data = {"correct_answer": 42, "attempts_left": 2, "message_id": 99, "task_text": "2+2?", "options": [42, 4, 6, 8]}
    await s.save_captcha(1, 111, data, ttl=300)
    result = await s.get_captcha(1, 111)
    assert result == data


@pytest.mark.asyncio
async def test_delete_captcha():
    s = _make_storage()
    await s.save_captcha(1, 222, {"correct_answer": 5}, ttl=300)
    await s.delete_captcha(1, 222)
    assert await s.get_captcha(1, 222) is None


# ── Muted-forever helpers ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_muted_forever_lifecycle():
    s = _make_storage()
    user_id = 99999

    assert not await s.is_muted_forever(user_id)

    await s.set_muted_forever(user_id)
    assert await s.is_muted_forever(user_id)

    await s.remove_muted_forever(user_id)
    assert not await s.is_muted_forever(user_id)


@pytest.mark.asyncio
async def test_muted_forever_count():
    s = _make_storage()
    assert await s.get_muted_forever_count() == 0

    await s.set_muted_forever(1)
    await s.set_muted_forever(2)
    await s.set_muted_forever(3)
    assert await s.get_muted_forever_count() == 3


@pytest.mark.asyncio
async def test_muted_forever_list():
    s = _make_storage()
    await s.set_muted_forever(10)
    await s.set_muted_forever(20)

    ids = await s.get_muted_forever_list()
    assert set(ids) == {"10", "20"}
