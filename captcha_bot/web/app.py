"""FastAPI web panel for captcha_bot administration."""
import asyncio
import json
import os
from pathlib import Path
from typing import Optional

from fastapi import Cookie, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from config import Settings
from services.mute_manager import unmute_user
from services.storage import DEFAULT_CHAT_CONFIG, Storage
from web.auth import COOKIE_NAME, create_session_cookie, verify_session_cookie

# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(title="Captcha Bot Panel", docs_url=None, redoc_url=None)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _get_settings() -> Settings:
    return Settings()


def _get_storage(settings: Settings) -> Storage:
    return app.state.storage


def _is_auth(request: Request) -> bool:
    settings: Settings = app.state.settings
    cookie = request.cookies.get(COOKIE_NAME)
    return verify_session_cookie(settings.web_secret_key, cookie)


def _require_auth(request: Request):
    if not _is_auth(request):
        return RedirectResponse("/login", status_code=302)
    return None


# ── Startup/shutdown ──────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup() -> None:
    settings = Settings()
    storage = Storage(settings.redis_url)
    await storage.connect()
    app.state.settings = settings
    app.state.storage = storage


@app.on_event("shutdown")
async def shutdown() -> None:
    if hasattr(app.state, "storage") and app.state.storage._redis:
        await app.state.storage._redis.aclose()


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
async def get_login(request: Request):
    if _is_auth(request):
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login", response_class=HTMLResponse)
async def post_login(request: Request, password: str = Form(...)):
    settings: Settings = app.state.settings
    if password == settings.web_secret_key:
        response = RedirectResponse("/", status_code=302)
        cookie_value = create_session_cookie(settings.web_secret_key)
        response.set_cookie(
            COOKIE_NAME,
            cookie_value,
            max_age=60 * 60 * 24 * 7,
            httponly=True,
            samesite="lax",
        )
        return response
    return templates.TemplateResponse(
        "login.html", {"request": request, "error": "Неверный пароль."}, status_code=401
    )


@app.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie(COOKIE_NAME)
    return response


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    redirect = _require_auth(request)
    if redirect:
        return redirect

    storage: Storage = app.state.storage
    chat_ids = await storage.get_all_configured_chats()

    chats = []
    for chat_id in sorted(chat_ids):
        cfg = await storage.get_chat_config(chat_id) or dict(DEFAULT_CHAT_CONFIG)
        stats = await storage.get_stats(chat_id)
        chats.append({"chat_id": chat_id, "cfg": cfg, "stats": stats})

    muted_count = await storage.get_muted_forever_count()

    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "chats": chats, "muted_count": muted_count},
    )


# ── Chat detail ───────────────────────────────────────────────────────────────

@app.get("/chats/{chat_id}", response_class=HTMLResponse)
async def chat_detail(request: Request, chat_id: int):
    redirect = _require_auth(request)
    if redirect:
        return redirect

    storage: Storage = app.state.storage
    cfg = await storage.get_chat_config(chat_id)
    if cfg is None:
        return HTMLResponse("Чат не найден.", status_code=404)

    stats = await storage.get_stats(chat_id)
    muted_list = await storage.get_muted_forever_list()

    return templates.TemplateResponse(
        "chat.html",
        {
            "request": request,
            "chat_id": chat_id,
            "cfg": cfg,
            "stats": stats,
            "muted_list": muted_list,
            "saved": False,
        },
    )


@app.post("/chats/{chat_id}/config", response_class=HTMLResponse)
async def save_chat_config(
    request: Request,
    chat_id: int,
    captcha_timeout: int = Form(...),
    captcha_attempts: int = Form(...),
    enabled: Optional[str] = Form(default=None),
    welcome_text: str = Form(default=""),
):
    redirect = _require_auth(request)
    if redirect:
        return redirect

    storage: Storage = app.state.storage
    cfg = await storage.get_chat_config(chat_id) or dict(DEFAULT_CHAT_CONFIG)

    captcha_timeout = max(30, captcha_timeout)
    captcha_attempts = max(1, captcha_attempts)

    cfg["captcha_timeout"] = captcha_timeout
    cfg["captcha_attempts"] = captcha_attempts
    cfg["enabled"] = enabled == "on"
    cfg["welcome_text"] = welcome_text.strip() or None

    await storage.save_chat_config(chat_id, cfg)

    stats = await storage.get_stats(chat_id)
    muted_list = await storage.get_muted_forever_list()

    return templates.TemplateResponse(
        "chat.html",
        {
            "request": request,
            "chat_id": chat_id,
            "cfg": cfg,
            "stats": stats,
            "muted_list": muted_list,
            "saved": True,
        },
    )


@app.post("/chats/{chat_id}/unmute/{user_id}", response_class=HTMLResponse)
async def web_unmute(request: Request, chat_id: int, user_id: int):
    redirect = _require_auth(request)
    if redirect:
        return redirect

    storage: Storage = app.state.storage
    await storage.remove_muted_forever(user_id)
    await storage.push_unmute_request(chat_id, user_id)

    # Return empty response — HTMX will remove the row via hx-swap="outerHTML"
    return HTMLResponse("")


# ── SSE event stream ──────────────────────────────────────────────────────────

@app.get("/events/stream")
async def events_stream(request: Request):
    if not _is_auth(request):
        return RedirectResponse("/login", status_code=302)

    storage: Storage = app.state.storage

    async def generator():
        async for event in storage.subscribe_events():
            if await request.is_disconnected():
                break
            yield {"data": json.dumps(event)}

    return EventSourceResponse(generator())
