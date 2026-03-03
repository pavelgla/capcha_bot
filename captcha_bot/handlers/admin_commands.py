import logging

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

from config import Settings
from services.mute_manager import unmute_user
from services.storage import DEFAULT_CHAT_CONFIG, Storage

logger = logging.getLogger(__name__)
router = Router()

_ALLOWED_PARAMS = {"timeout", "attempts"}


async def _is_telegram_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    """True if user is creator or administrator of this specific chat."""
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


async def _is_admin(bot: Bot, chat_id: int, user_id: int, settings: Settings) -> bool:
    """True if Telegram chat admin OR in global ADMIN_IDS."""
    if user_id in settings.admin_ids:
        return True
    return await _is_telegram_admin(bot, chat_id, user_id)


# ── Chat setup & config ───────────────────────────────────────────────────────

@router.message(Command("setup"))
async def cmd_setup(
    message: Message, bot: Bot, storage: Storage, settings: Settings
) -> None:
    """Activate bot in this chat. Available to any Telegram admin of the chat."""
    if not await _is_telegram_admin(bot, message.chat.id, message.from_user.id):
        await message.reply("⛔ Только для администраторов чата.")
        return

    existing = await storage.get_chat_config(message.chat.id)
    if existing:
        await message.reply(
            "ℹ️ Бот уже настроен в этом чате.\n"
            "Используйте /chatconfig чтобы посмотреть текущие настройки."
        )
        return

    config = {
        "captcha_timeout": settings.captcha_timeout,
        "captcha_attempts": settings.captcha_attempts,
        "enabled": True,
    }
    await storage.save_chat_config(message.chat.id, config)
    logger.info("Chat %s configured by admin %s", message.chat.id, message.from_user.id)

    await message.reply(
        f"✅ Бот настроен для этого чата!\n\n"
        f"⏱ Таймаут: {config['captcha_timeout']} сек\n"
        f"🔁 Попыток: {config['captcha_attempts']}\n\n"
        f"Доступные команды:\n"
        f"  /chatconfig — текущие настройки\n"
        f"  /setparam timeout 600 — изменить таймаут\n"
        f"  /setparam attempts 3 — изменить кол-во попыток\n"
        f"  /disable — отключить бота в этом чате\n"
        f"  /enable — включить обратно"
    )


@router.message(Command("chatconfig"))
async def cmd_chatconfig(
    message: Message, bot: Bot, storage: Storage, settings: Settings
) -> None:
    if not await _is_admin(bot, message.chat.id, message.from_user.id, settings):
        await message.reply("⛔ Команда только для администраторов.")
        return

    cfg = await storage.get_chat_config(message.chat.id)
    if not cfg:
        await message.reply("Бот не настроен. Используйте /setup")
        return

    status = "✅ включён" if cfg.get("enabled", True) else "⛔ выключен"
    await message.reply(
        f"Настройки чата {message.chat.id}:\n"
        f"• Статус: {status}\n"
        f"• Таймаут: {cfg['captcha_timeout']} сек\n"
        f"• Попыток: {cfg['captcha_attempts']}"
    )


@router.message(Command("setparam"))
async def cmd_setparam(
    message: Message, bot: Bot, storage: Storage, settings: Settings
) -> None:
    """Usage: /setparam timeout 600  |  /setparam attempts 3"""
    if not await _is_admin(bot, message.chat.id, message.from_user.id, settings):
        await message.reply("⛔ Команда только для администраторов.")
        return

    parts = message.text.split()
    if len(parts) != 3 or parts[1] not in _ALLOWED_PARAMS or not parts[2].isdigit():
        await message.reply(
            "Использование:\n"
            "  /setparam timeout <секунды>\n"
            "  /setparam attempts <число>"
        )
        return

    param, value = parts[1], int(parts[2])
    if param == "timeout" and value < 30:
        await message.reply("Минимальный таймаут — 30 секунд.")
        return
    if param == "attempts" and value < 1:
        await message.reply("Минимум 1 попытка.")
        return

    cfg = await storage.get_chat_config(message.chat.id) or dict(DEFAULT_CHAT_CONFIG)
    key = "captcha_timeout" if param == "timeout" else "captcha_attempts"
    cfg[key] = value
    await storage.save_chat_config(message.chat.id, cfg)

    label = "Таймаут" if param == "timeout" else "Попыток"
    unit = " сек" if param == "timeout" else ""
    await message.reply(f"✅ {label} изменён: {value}{unit}")
    logger.info("Admin %s set %s=%s in chat %s", message.from_user.id, param, value, message.chat.id)


@router.message(Command("disable"))
async def cmd_disable(
    message: Message, bot: Bot, storage: Storage, settings: Settings
) -> None:
    if not await _is_admin(bot, message.chat.id, message.from_user.id, settings):
        await message.reply("⛔ Команда только для администраторов.")
        return

    cfg = await storage.get_chat_config(message.chat.id) or dict(DEFAULT_CHAT_CONFIG)
    cfg["enabled"] = False
    await storage.save_chat_config(message.chat.id, cfg)
    await message.reply("⛔ Бот отключён в этом чате. Новые участники не будут проверяться.\n/enable — включить обратно.")


@router.message(Command("enable"))
async def cmd_enable(
    message: Message, bot: Bot, storage: Storage, settings: Settings
) -> None:
    if not await _is_admin(bot, message.chat.id, message.from_user.id, settings):
        await message.reply("⛔ Команда только для администраторов.")
        return

    cfg = await storage.get_chat_config(message.chat.id) or dict(DEFAULT_CHAT_CONFIG)
    cfg["enabled"] = True
    await storage.save_chat_config(message.chat.id, cfg)
    await message.reply("✅ Бот включён в этом чате.")


# ── Mute management ───────────────────────────────────────────────────────────

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
