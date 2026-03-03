import logging

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

from config import Settings
from services.mute_manager import unmute_user
from services.storage import Storage

logger = logging.getLogger(__name__)
router = Router()


async def _is_admin(bot: Bot, chat_id: int, user_id: int, settings: Settings) -> bool:
    """Return True if user_id is in ADMIN_IDS or is a Telegram chat admin/creator."""
    if user_id in settings.admin_ids:
        return True
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


@router.message(Command("unmute"))
async def cmd_unmute(
    message: Message, bot: Bot, storage: Storage, settings: Settings
) -> None:
    if not await _is_admin(bot, message.chat.id, message.from_user.id, settings):
        await message.reply("⛔ Команда только для администраторов.")
        return

    parts = message.text.split()
    if len(parts) != 2 or not parts[1].lstrip("-").isdigit():
        await message.reply("Использование: /unmute <user_id>")
        return

    target_id = int(parts[1])
    await storage.remove_muted_forever(target_id)
    await unmute_user(bot, message.chat.id, target_id)
    await message.reply(f"✅ Пользователь {target_id} размьючен.")
    logger.info("Admin %s unmuted user %s", message.from_user.id, target_id)


@router.message(Command("mutestat"))
async def cmd_mutestat(
    message: Message, bot: Bot, storage: Storage, settings: Settings
) -> None:
    if not await _is_admin(bot, message.chat.id, message.from_user.id, settings):
        await message.reply("⛔ Команда только для администраторов.")
        return

    count = await storage.get_muted_forever_count()
    await message.reply(f"🚫 Замьючено навсегда: {count} пользователей.")


@router.message(Command("banned"))
async def cmd_banned(
    message: Message, bot: Bot, storage: Storage, settings: Settings
) -> None:
    if not await _is_admin(bot, message.chat.id, message.from_user.id, settings):
        await message.reply("⛔ Команда только для администраторов.")
        return

    ids = await storage.get_muted_forever_list()
    if not ids:
        await message.reply("Список пуст.")
        return

    text = "🚫 Замьюченные навсегда:\n" + "\n".join(f"• {uid}" for uid in ids)
    await message.reply(text)
