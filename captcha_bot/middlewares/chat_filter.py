from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Update


class ChatFilterMiddleware(BaseMiddleware):
    """
    Outer middleware that drops all updates not originating from the configured chat.
    Registered on dp.update so it covers every event type.
    """

    def __init__(self, chat_id: int) -> None:
        self.chat_id = chat_id

    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any],
    ) -> Any:
        chat_id = self._extract_chat_id(event)
        if chat_id is not None and chat_id != self.chat_id:
            return  # silently ignore

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
