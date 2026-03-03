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

from config import Settings
from services.captcha_generator import generate_captcha
from services.mute_manager import mute_user
from services.storage import Storage

logger = logging.getLogger(__name__)
router = Router()

# user_id → running asyncio.Task for timeout
_timeout_tasks: Dict[int, asyncio.Task] = {}  # type: ignore[type-arg]


def _build_keyboard(user_id: int, options: list) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            text=str(opt),
            callback_data=f"captcha:{user_id}:{opt}",
        )
        for opt in options
    ]
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def cancel_timeout(user_id: int) -> None:
    task = _timeout_tasks.pop(user_id, None)
    if task:
        task.cancel()


@router.chat_member(ChatMemberUpdatedFilter(JOIN_TRANSITION))
async def on_new_member(
    event: ChatMemberUpdated,
    bot: Bot,
    storage: Storage,
    settings: Settings,
) -> None:
    user = event.new_chat_member.user
    if user.is_bot:
        return

    user_id = user.id
    chat_id = event.chat.id
    mention = f"@{user.username}" if user.username else user.full_name

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
        "attempts_left": settings.captcha_attempts,
        "message_id": None,
        "task_text": task.question,
        "options": task.options,
    }

    # 4. Send captcha message
    minutes, seconds = divmod(settings.captcha_timeout, 60)
    text = (
        f"👋 {mention}, добро пожаловать!\n\n"
        f"Для доступа к чату решите задачку:\n\n"
        f"{task.question}\n\n"
        f"У вас {settings.captcha_attempts} попытки. "
        f"Осталось: {minutes}:{seconds:02d}"
    )
    try:
        msg = await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=_build_keyboard(user_id, task.options),
        )
    except TelegramForbiddenError:
        logger.error("Cannot send captcha to chat %s — check bot admin rights", chat_id)
        return
    except Exception as exc:
        logger.error("Failed to send captcha for user %s: %s", user_id, exc)
        return

    captcha_data["message_id"] = msg.message_id

    # 5. Persist to Redis
    await storage.save_captcha(user_id, captcha_data, ttl=settings.captcha_timeout)

    # 6. Start timeout task (cancel previous one if user re-joined quickly)
    cancel_timeout(user_id)
    _timeout_tasks[user_id] = asyncio.create_task(
        _timeout_handler(bot, storage, chat_id, user_id, msg.message_id, settings)
    )


@router.chat_member(ChatMemberUpdatedFilter(LEAVE_TRANSITION))
async def on_member_left(
    event: ChatMemberUpdated,
    storage: Storage,
) -> None:
    """Cancel pending captcha when a user leaves before solving it."""
    user_id = event.old_chat_member.user.id
    cancel_timeout(user_id)
    await storage.delete_captcha(user_id)
    logger.info("User %s left — cancelled pending captcha", user_id)


async def _timeout_handler(
    bot: Bot,
    storage: Storage,
    chat_id: int,
    user_id: int,
    message_id: int,
    settings: Settings,
) -> None:
    try:
        await asyncio.sleep(settings.captcha_timeout)

        # Guard: already resolved
        if await storage.get_captcha(user_id) is None:
            return

        logger.info("Captcha timeout for user %s", user_id)

        try:
            await bot.delete_message(chat_id, message_id)
        except Exception as exc:
            logger.warning("Could not delete captcha message: %s", exc)

        await storage.set_muted_forever(user_id)
        await storage.delete_captcha(user_id)

    except asyncio.CancelledError:
        pass
    finally:
        _timeout_tasks.pop(user_id, None)
