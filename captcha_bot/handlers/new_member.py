import asyncio
import datetime
import logging
import time
from typing import Dict, List

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters.chat_member_updated import (
    ChatMemberUpdatedFilter,
    JOIN_TRANSITION,
    LEAVE_TRANSITION,
)
from aiogram.types import (
    ChatMemberUpdated,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    User,
)

from services.captcha_generator import generate_captcha
from services.mute_manager import mute_user
from services.storage import DEFAULT_CHAT_CONFIG, Storage

logger = logging.getLogger(__name__)
router = Router()

# Composite key "<chat_id>:<user_id>" → running asyncio.Task
_timeout_tasks: Dict[str, asyncio.Task] = {}  # type: ignore[type-arg]


def _task_key(chat_id: int, user_id: int) -> str:
    return f"{chat_id}:{user_id}"


def _build_keyboard(chat_id: int, user_id: int, options: list) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            text=str(opt),
            callback_data=f"captcha:{chat_id}:{user_id}:{opt}",
        )
        for opt in options
    ]
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def cancel_timeout(chat_id: int, user_id: int) -> None:
    task = _timeout_tasks.pop(_task_key(chat_id, user_id), None)
    if task:
        task.cancel()


async def _process_new_member(
    bot: Bot,
    storage: Storage,
    chat_id: int,
    user: User,
    service_message_id: int | None = None,
) -> None:
    """
    Core logic for handling a new member.
    Called from both the service-message handler and the chat_member handler.
    Deduplication: if a captcha already exists for this user, skip silently.
    """
    if user.is_bot:
        return

    user_id = user.id
    mention = f"@{user.username}" if user.username else user.full_name

    chat_cfg = await storage.get_chat_config(chat_id) or DEFAULT_CHAT_CONFIG
    if not chat_cfg.get("enabled", True):
        return

    timeout: int = chat_cfg["captcha_timeout"]
    attempts: int = chat_cfg["captcha_attempts"]

    # 1. Mute immediately
    await mute_user(bot, chat_id, user_id)

    # Delete service "X joined" message to keep chat clean
    if service_message_id is not None:
        try:
            await bot.delete_message(chat_id, service_message_id)
        except Exception:
            pass

    # 2. Permanent-mute check
    if await storage.is_muted_forever(user_id):
        logger.info("User %s is muted forever — skipping captcha", user_id)
        return

    # 3. Atomically claim slot — prevents double-captcha on duplicate events
    if not await storage.claim_captcha_slot(chat_id, user_id, ttl=timeout):
        logger.debug("Captcha slot already claimed for user %s in chat %s — skipping", user_id, chat_id)
        return

    # 4. Generate captcha
    task = generate_captcha()
    captcha_data = {
        "correct_answer": task.correct_answer,
        "attempts_left": attempts,
        "message_id": None,
        "task_text": task.question,
        "options": task.options,
        "chat_id": chat_id,
    }

    # 5. Send captcha message
    minutes, seconds = divmod(timeout, 60)
    welcome_text = chat_cfg.get("welcome_text") or None
    greeting = welcome_text if welcome_text else f"👋 {mention}, добро пожаловать!"
    text = (
        f"{greeting}\n\n"
        f"Для доступа к чату решите задачку:\n\n"
        f"{task.question}\n\n"
        f"У вас {attempts} попытки. "
        f"Осталось: {minutes}:{seconds:02d}"
    )
    try:
        msg = await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=_build_keyboard(chat_id, user_id, task.options),
        )
    except TelegramForbiddenError:
        logger.error("Cannot send captcha to chat %s — check bot admin rights", chat_id)
        return
    except Exception as exc:
        logger.error("Failed to send captcha for user %s: %s", user_id, exc)
        return

    captcha_data["message_id"] = msg.message_id

    # 6. Persist to Redis
    await storage.save_captcha(chat_id, user_id, captcha_data, ttl=timeout)
    await storage.add_captcha_message(chat_id, msg.message_id, time.time())

    # 7. Start timeout task
    cancel_timeout(chat_id, user_id)
    key = _task_key(chat_id, user_id)
    _timeout_tasks[key] = asyncio.create_task(
        _timeout_handler(bot, storage, chat_id, user_id, msg.message_id, timeout)
    )
    logger.info("Captcha sent to user %s in chat %s", user_id, chat_id)

    # 8. Stats + real-time event
    await storage.increment_stat(chat_id, "joined")
    await storage.publish_event({
        "type": "join",
        "chat_id": chat_id,
        "user_id": user_id,
        "username": mention,
        "ts": datetime.datetime.utcnow().isoformat(),
    })


# ── Primary handler: service message (works in all group types) ───────────────

@router.message(F.new_chat_members)
async def on_new_member_message(
    message: Message,
    bot: Bot,
    storage: Storage,
) -> None:
    """
    Triggered by the 'X joined the group' service message.
    More reliable than chat_member events — works in regular groups and supergroups.
    """
    members: List[User] = message.new_chat_members
    for user in members:
        await _process_new_member(
            bot, storage, message.chat.id, user,
            service_message_id=message.message_id,
        )


# ── Secondary handler: chat_member event (supergroups with admin bot) ─────────

@router.chat_member(ChatMemberUpdatedFilter(JOIN_TRANSITION))
async def on_new_member_event(
    event: ChatMemberUpdated,
    bot: Bot,
    storage: Storage,
) -> None:
    """Fallback: chat_member update. Deduplication prevents double-processing."""
    await _process_new_member(bot, storage, event.chat.id, event.new_chat_member.user)


# ── Leave handler ─────────────────────────────────────────────────────────────

@router.chat_member(ChatMemberUpdatedFilter(LEAVE_TRANSITION))
async def on_member_left(
    event: ChatMemberUpdated,
    bot: Bot,
    storage: Storage,
) -> None:
    """Cancel pending captcha when a user leaves before solving it."""
    user_id = event.old_chat_member.user.id
    chat_id = event.chat.id
    cancel_timeout(chat_id, user_id)

    captcha_data = await storage.get_captcha(chat_id, user_id)
    if captcha_data and captcha_data.get("message_id"):
        try:
            await bot.delete_message(chat_id, captcha_data["message_id"])
        except Exception as exc:
            logger.warning("Could not delete captcha message on leave: %s", exc)
        await storage.remove_captcha_message(chat_id, captcha_data["message_id"])

    await storage.delete_captcha(chat_id, user_id)
    logger.info("User %s left chat %s — cancelled pending captcha", user_id, chat_id)


# ── Timeout handler ───────────────────────────────────────────────────────────

async def restore_pending_captchas(bot: Bot, storage: Storage) -> None:
    """On startup: reschedule timeout tasks for captchas that survived a bot restart."""
    pending = await storage.get_all_pending_captchas()
    for chat_id, user_id, data, remaining_ttl in pending:
        message_id = data["message_id"]
        key = _task_key(chat_id, user_id)
        if key not in _timeout_tasks:
            _timeout_tasks[key] = asyncio.create_task(
                _timeout_handler(bot, storage, chat_id, user_id, message_id, remaining_ttl)
            )
            logger.info(
                "Restored timeout task for user %s in chat %s (remaining: %ds)",
                user_id, chat_id, remaining_ttl,
            )
    if pending:
        logger.info("Restored %d pending captcha(s) after restart", len(pending))


async def _timeout_handler(
    bot: Bot,
    storage: Storage,
    chat_id: int,
    user_id: int,
    message_id: int,
    timeout: int,
) -> None:
    try:
        await asyncio.sleep(timeout)

        if await storage.get_captcha(chat_id, user_id) is None:
            return  # Already resolved

        logger.info("Captcha timeout for user %s in chat %s", user_id, chat_id)

        try:
            await bot.delete_message(chat_id, message_id)
        except Exception as exc:
            logger.warning("Could not delete captcha message: %s", exc)
        await storage.remove_captcha_message(chat_id, message_id)

        await storage.set_muted_forever(user_id)
        await storage.delete_captcha(chat_id, user_id)

        await storage.increment_stat(chat_id, "timeout")
        await storage.publish_event({
            "type": "timeout",
            "chat_id": chat_id,
            "user_id": user_id,
            "ts": datetime.datetime.utcnow().isoformat(),
        })

    except asyncio.CancelledError:
        pass
    finally:
        _timeout_tasks.pop(_task_key(chat_id, user_id), None)
