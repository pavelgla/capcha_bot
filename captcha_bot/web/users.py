"""Password hashing and superadmin bootstrap for the web panel."""
import datetime
import logging

from passlib.context import CryptContext

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


async def bootstrap_superadmin(storage, settings) -> None:
    """Create the superadmin account on first startup if it doesn't exist."""
    username = settings.superadmin_username
    if await storage.user_exists(username):
        return

    data = {
        "username": username,
        "password_hash": hash_password(settings.superadmin_password),
        "role": "superadmin",
        "plan": "pro",
        "max_chats": -1,
        "telegram_id": None,
        "created_at": datetime.datetime.utcnow().isoformat(),
    }
    await storage.create_user(username, data)
    logger.info("Superadmin account '%s' created on first startup", username)
