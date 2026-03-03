import asyncio
import logging

from aiogram import Bot, Dispatcher

from config import Settings
from handlers import admin_commands, captcha_callback, new_member
from middlewares.chat_filter import ChatFilterMiddleware
from services.storage import Storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = Settings()

    storage = Storage(settings.redis_url)
    await storage.connect()

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()

    # Outer middleware filters events from unwanted chats
    dp.update.outer_middleware(ChatFilterMiddleware(settings.chat_id))

    # Inject shared objects into every handler via aiogram DI
    dp["storage"] = storage
    dp["settings"] = settings

    dp.include_router(new_member.router)
    dp.include_router(captcha_callback.router)
    dp.include_router(admin_commands.router)

    logger.info("Starting captcha_bot (chat_id=%s)", settings.chat_id)
    await dp.start_polling(
        bot,
        allowed_updates=["message", "callback_query", "chat_member"],
    )


if __name__ == "__main__":
    asyncio.run(main())
