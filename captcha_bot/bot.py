import asyncio
import logging

from aiogram import Bot, Dispatcher

from config import Settings
from handlers import admin_commands, captcha_callback, new_member
from middlewares.chat_filter import ChatFilterMiddleware
from services.mute_manager import unmute_user
from services.storage import DEFAULT_CHAT_CONFIG, Storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


async def _unmute_queue_worker(bot: Bot, storage: Storage) -> None:
    """Background task: processes pending unmute requests from the web panel."""
    while True:
        try:
            result = await storage.pop_unmute_request()
            if result is not None:
                chat_id, user_id = result
                await unmute_user(bot, chat_id, user_id)
                logger.info("Unmuted user %s in chat %s (via web panel)", user_id, chat_id)
        except Exception as exc:
            logger.error("Unmute queue worker error: %s", exc)
        await asyncio.sleep(2)


async def main() -> None:
    settings = Settings()

    storage = Storage(settings.redis_url)
    await storage.connect()

    # Backward compat: if CHAT_ID is set in .env, auto-configure that chat
    if settings.chat_id is not None:
        if not await storage.is_chat_configured(settings.chat_id):
            await storage.save_chat_config(
                settings.chat_id,
                {
                    **DEFAULT_CHAT_CONFIG,
                    "captcha_timeout": settings.captcha_timeout,
                    "captcha_attempts": settings.captcha_attempts,
                },
            )
            logger.info("Auto-configured chat %s from CHAT_ID env var", settings.chat_id)

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()

    # Outer middleware: pass events only for configured chats (+ /setup anywhere)
    dp.update.outer_middleware(ChatFilterMiddleware(storage))

    # Inject shared objects into every handler via aiogram DI
    dp["storage"] = storage
    dp["settings"] = settings

    dp.include_router(new_member.router)
    dp.include_router(captcha_callback.router)
    dp.include_router(admin_commands.router)

    configured = await storage.get_all_configured_chats()
    logger.info("Starting captcha_bot — configured chats: %s", configured or "none (use /setup)")

    asyncio.create_task(_unmute_queue_worker(bot, storage))

    await dp.start_polling(
        bot,
        allowed_updates=["message", "callback_query", "chat_member"],
    )


if __name__ == "__main__":
    asyncio.run(main())
