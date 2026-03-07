import asyncio
import datetime
import logging

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from handlers.new_member import cancel_timeout
from services.mute_manager import unmute_user
from services.storage import DEFAULT_CHAT_CONFIG, Storage

logger = logging.getLogger(__name__)
router = Router()


def _build_keyboard(chat_id: int, user_id: int, options: list) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            text=str(opt),
            callback_data=f"captcha:{chat_id}:{user_id}:{opt}",
        )
        for opt in options
    ]
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


async def _auto_delete(bot: Bot, chat_id: int, message_id: int, delay: int) -> None:
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception as exc:
        logger.warning("Auto-delete failed for message %s: %s", message_id, exc)


@router.callback_query(F.data.startswith("captcha:"))
async def on_captcha_answer(
    callback: CallbackQuery,
    bot: Bot,
    storage: Storage,
) -> None:
    # Format: captcha:<chat_id>:<user_id>:<answer>
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Неверный формат.", show_alert=False)
        return

    _, chat_id_str, target_id_str, answer_str = parts
    chat_id = int(chat_id_str)
    target_user_id = int(target_id_str)
    answer = int(answer_str)

    # Reject if someone else clicks the button
    if callback.from_user.id != target_user_id:
        await callback.answer("Эта проверка не для вас.", show_alert=True)
        return

    captcha_data = await storage.get_captcha(chat_id, target_user_id)
    if captcha_data is None:
        await callback.answer("Время вышло.", show_alert=True)
        return

    message_id = callback.message.message_id
    mention = (
        f"@{callback.from_user.username}"
        if callback.from_user.username
        else callback.from_user.full_name
    )

    if answer == captcha_data["correct_answer"]:
        # ── Correct ──────────────────────────────────────────────────────────
        cancel_timeout(chat_id, target_user_id)
        await unmute_user(bot, chat_id, target_user_id)

        try:
            await bot.delete_message(chat_id, message_id)
        except Exception as exc:
            logger.warning("Could not delete captcha message: %s", exc)
        await storage.remove_captcha_message(chat_id, message_id)

        await storage.delete_captcha(chat_id, target_user_id)

        await storage.increment_stat(chat_id, "passed")
        await storage.publish_event({
            "type": "pass",
            "chat_id": chat_id,
            "user_id": target_user_id,
            "username": mention,
            "ts": datetime.datetime.utcnow().isoformat(),
        })

        try:
            ok_msg = await bot.send_message(chat_id, f"✅ {mention} прошёл(а) проверку!")
            asyncio.create_task(_auto_delete(bot, chat_id, ok_msg.message_id, 10))
        except Exception as exc:
            logger.error("Failed to send success message: %s", exc)

        await callback.answer("✅ Верно!", show_alert=False)

    else:
        # ── Wrong ─────────────────────────────────────────────────────────────
        captcha_data["attempts_left"] -= 1

        if captcha_data["attempts_left"] > 0:
            # Reload timeout from chat config for TTL refresh
            chat_cfg = await storage.get_chat_config(chat_id) or DEFAULT_CHAT_CONFIG
            timeout: int = chat_cfg["captcha_timeout"]
            await storage.save_captcha(chat_id, target_user_id, captcha_data, ttl=timeout)

            try:
                new_text = (
                    f"❌ Неверно. Осталось попыток: {captcha_data['attempts_left']}\n\n"
                    f"{captcha_data['task_text']}"
                )
                keyboard = _build_keyboard(chat_id, target_user_id, captcha_data["options"])
                await callback.message.edit_text(new_text, reply_markup=keyboard)
            except Exception as exc:
                logger.warning("Could not edit captcha message: %s", exc)

            await callback.answer("❌ Неверно!", show_alert=False)

        else:
            # ── Out of attempts ───────────────────────────────────────────────
            cancel_timeout(chat_id, target_user_id)

            try:
                await bot.delete_message(chat_id, message_id)
            except Exception as exc:
                logger.warning("Could not delete captcha message: %s", exc)
            await storage.remove_captcha_message(chat_id, message_id)

            await storage.set_muted_forever(target_user_id)
            await storage.delete_captcha(chat_id, target_user_id)

            await storage.increment_stat(chat_id, "failed")
            await storage.publish_event({
                "type": "fail",
                "chat_id": chat_id,
                "user_id": target_user_id,
                "username": mention,
                "ts": datetime.datetime.utcnow().isoformat(),
            })

            try:
                fail_msg = await bot.send_message(
                    chat_id, f"🚫 {mention} не прошёл(а) проверку."
                )
                asyncio.create_task(_auto_delete(bot, chat_id, fail_msg.message_id, 15))
            except Exception as exc:
                logger.error("Failed to send failure message: %s", exc)

            await callback.answer("❌ Попытки исчерпаны.", show_alert=False)
