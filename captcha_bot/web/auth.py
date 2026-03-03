"""Simple cookie-based authentication for the web panel."""
from typing import Optional

from fastapi import Cookie, Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

_COOKIE_NAME = "session"
_MAX_AGE = 60 * 60 * 24 * 7  # 7 days


def _signer(secret: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret, salt="captcha-web-panel")


def create_session_cookie(secret: str) -> str:
    return _signer(secret).dumps("admin")


def verify_session_cookie(secret: str, cookie: Optional[str]) -> bool:
    if not cookie:
        return False
    try:
        _signer(secret).loads(cookie, max_age=_MAX_AGE)
        return True
    except (BadSignature, SignatureExpired):
        return False


def require_auth(secret: str, session: Optional[str] = Cookie(default=None, alias=_COOKIE_NAME)):
    """Dependency: raises redirect if not authenticated."""
    if not verify_session_cookie(secret, session):
        raise _redirect_to_login()
    return True


def _redirect_to_login() -> RedirectResponse:
    # We raise this; FastAPI treats raised responses as actual responses
    from fastapi import HTTPException
    # Can't redirect via dependency raise easily, so we use a workaround in routes
    raise HTTPException(status_code=307, headers={"Location": "/login"})


COOKIE_NAME = _COOKIE_NAME
