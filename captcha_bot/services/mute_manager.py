import logging

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import ChatPermissions

logger = logging.getLogger(__name__)

_MUTED = ChatPermissions(
    can_send_messages=False,
    can_send_media_messages=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
)

_DEFAULT = ChatPermissions(
    can_send_messages=True,
    can_send_media_messages=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
)


async def mute_user(bot: Bot, chat_id: int, user_id: int) -> None:
    try:
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=_MUTED,
        )
        logger.info("Muted user %s in chat %s", user_id, chat_id)
    except TelegramForbiddenError:
        logger.error("Forbidden: cannot mute user %s (no admin rights?)", user_id)
    except Exception as exc:
        logger.error("Failed to mute user %s: %s", user_id, exc)


async def unmute_user(bot: Bot, chat_id: int, user_id: int) -> None:
    try:
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=_DEFAULT,
        )
        logger.info("Unmuted user %s in chat %s", user_id, chat_id)
    except TelegramForbiddenError:
        logger.error("Forbidden: cannot unmute user %s", user_id)
    except Exception as exc:
        logger.error("Failed to unmute user %s: %s", user_id, exc)
