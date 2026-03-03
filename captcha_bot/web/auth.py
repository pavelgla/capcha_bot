"""Cookie-based authentication for the web panel (multi-user)."""
from typing import Optional

from fastapi import Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

COOKIE_NAME = "session"
_MAX_AGE = 60 * 60 * 24 * 7  # 7 days
_SALT = "captcha-web-panel-v2"


def _signer(secret: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret, salt=_SALT)


def create_session_cookie(secret: str, username: str) -> str:
    """Return a signed cookie value storing the username."""
    return _signer(secret).dumps(username)


def get_session_username(secret: str, request: Request) -> Optional[str]:
    """Return the username from the signed cookie, or None if invalid/missing."""
    cookie = request.cookies.get(COOKIE_NAME)
    if not cookie:
        return None
    try:
        return _signer(secret).loads(cookie, max_age=_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
