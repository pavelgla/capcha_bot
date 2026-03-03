import asyncio
import logging
from typing import Dict

from aiogram import Bot, Router
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters.chat_member_updated import (
    ChatMemberUpdatedFilter,
    JOIN_TRANSITION,
    LEAVE_TRANSITION,
)
from aiogram.types import ChatMemberUpdated, InlineKeyboardButton, InlineKeyboardMarkup

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


@router.chat_member(ChatMemberUpdatedFilter(JOIN_TRANSITION))
async def on_new_member(
    event: ChatMemberUpdated,
    bot: Bot,
    storage: Storage,
) -> None:
    user = event.new_chat_member.user
    if user.is_bot:
        return

    user_id = user.id
    chat_id = event.chat.id
    mention = f"@{user.username}" if user.username else user.full_name

    # Load per-chat config (fall back to defaults if somehow missing)
    chat_cfg = await storage.get_chat_config(chat_id) or DEFAULT_CHAT_CONFIG
    if not chat_cfg.get("enabled", True):
        return

    timeout: int = chat_cfg["captcha_timeout"]
    attempts: int = chat_cfg["captcha_attempts"]

    # 1. Mute immediately
    await mute_user(bot, chat_id, user_id)

    # 2. Permanent-mute check
    if await storage.is_muted_forever(user_id):
        logger.info("User %s is muted forever — skipping captcha", user_id)
        return

    # 3. Generate captcha
    task = generate_captcha()
    captcha_data = {
        "correct_answer": task.correct_answer,
        "attempts_left": attempts,
        "message_id": None,
        "task_text": task.question,
        "options": task.options,
        "chat_id": chat_id,
    }

    # 4. Send captcha message
    minutes, seconds = divmod(timeout, 60)
    text = (
        f"👋 {mention}, добро пожаловать!\n\n"
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

    # 5. Persist to Redis
    await storage.save_captcha(chat_id, user_id, captcha_data, ttl=timeout)

    # 6. Start timeout task
    cancel_timeout(chat_id, user_id)
    key = _task_key(chat_id, user_id)
    _timeout_tasks[key] = asyncio.create_task(
        _timeout_handler(bot, storage, chat_id, user_id, msg.message_id, timeout)
    )


@router.chat_member(ChatMemberUpdatedFilter(LEAVE_TRANSITION))
async def on_member_left(
    event: ChatMemberUpdated,
    storage: Storage,
) -> None:
    """Cancel pending captcha when a user leaves before solving it."""
    user_id = event.old_chat_member.user.id
    chat_id = event.chat.id
    cancel_timeout(chat_id, user_id)
    await storage.delete_captcha(chat_id, user_id)
    logger.info("User %s left chat %s — cancelled pending captcha", user_id, chat_id)


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

        await storage.set_muted_forever(user_id)
        await storage.delete_captcha(chat_id, user_id)

    except asyncio.CancelledError:
        pass
    finally:
        _timeout_tasks.pop(_task_key(chat_id, user_id), None)
