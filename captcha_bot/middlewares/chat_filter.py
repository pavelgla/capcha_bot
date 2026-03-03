from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Update

from services.storage import Storage


class ChatFilterMiddleware(BaseMiddleware):
    """
    Outer middleware registered on dp.update.
    - Passes through /setup in any chat (so unconfigured chats can be activated).
    - For all other events: only passes through if the chat is configured in Redis.
    """

    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any],
    ) -> Any:
        chat_id = self._extract_chat_id(event)

        if chat_id is None:
            return await handler(event, data)

        # Always allow /setup so admins can activate the bot in new chats
        if self._is_setup_command(event):
            return await handler(event, data)

        if not await self.storage.is_chat_configured(chat_id):
            return  # silently ignore unconfigured chats

        return await handler(event, data)

    @staticmethod
    def _extract_chat_id(update: Update) -> int | None:
        if update.message:
            return update.message.chat.id
        if update.callback_query and update.callback_query.message:
            return update.callback_query.message.chat.id
        if update.chat_member:
            return update.chat_member.chat.id
        if update.my_chat_member:
            return update.my_chat_member.chat.id
        return None

    @staticmethod
    def _is_setup_command(update: Update) -> bool:
        if update.message and update.message.text:
            return update.message.text.strip().startswith("/setup")
        return False
