"""FastAPI web panel for captcha_bot — multi-tenant edition."""
import datetime
import json
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from config import Settings
from services.storage import DEFAULT_CHAT_CONFIG, Storage
from web.auth import COOKIE_NAME, create_session_cookie, get_session_username
from web.users import bootstrap_superadmin, verify_password

# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(title="Captcha Bot Panel", docs_url=None, redoc_url=None)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# ── Helpers ───────────────────────────────────────────────────────────────────


async def get_current_user(request: Request) -> Optional[Dict[str, Any]]:
    settings: Settings = app.state.settings
    storage: Storage = app.state.storage
    username = get_session_username(settings.web_secret_key, request)
    if not username:
        return None
    return await storage.get_user(username)


def check_auth(user: Optional[Dict]) -> Optional[RedirectResponse]:
    """Return a redirect if not authenticated, else None."""
    if user is None:
        return RedirectResponse("/login", status_code=302)
    return None


def check_superadmin(user: Optional[Dict]) -> Optional[Response]:
    """Return 403 if not superadmin, else None."""
    if user is None or user.get("role") != "superadmin":
        return HTMLResponse("403 Forbidden", status_code=403)
    return None


def is_superadmin(user: Dict) -> bool:
    return user.get("role") == "superadmin"


# ── Startup / shutdown ────────────────────────────────────────────────────────


@app.on_event("startup")
async def startup() -> None:
    settings = Settings()
    storage = Storage(settings.redis_url)
    await storage.connect()
    app.state.settings = settings
    app.state.storage = storage
    await bootstrap_superadmin(storage, settings)


@app.on_event("shutdown")
async def shutdown() -> None:
    if hasattr(app.state, "storage") and app.state.storage._redis:
        await app.state.storage._redis.aclose()


# ── Auth routes ───────────────────────────────────────────────────────────────


@app.get("/login", response_class=HTMLResponse)
async def get_login(request: Request):
    user = await get_current_user(request)
    if user:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login", response_class=HTMLResponse)
async def post_login(request: Request, username: str = Form(...), password: str = Form(...)):
    storage: Storage = app.state.storage
    settings: Settings = app.state.settings

    user = await storage.get_user(username)
    if user and verify_password(password, user["password_hash"]):
        response = RedirectResponse("/", status_code=302)
        cookie_value = create_session_cookie(settings.web_secret_key, username)
        response.set_cookie(
            COOKIE_NAME,
            cookie_value,
            max_age=60 * 60 * 24 * 7,
            httponly=True,
            samesite="lax",
        )
        return response

    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": "Неверное имя пользователя или пароль."},
        status_code=401,
    )


@app.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie(COOKIE_NAME)
    return response


# ── Dashboard ─────────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    user = await get_current_user(request)
    if redir := check_auth(user):
        return redir

    storage: Storage = app.state.storage

    if is_superadmin(user):
        chat_ids = await storage.get_all_configured_chats()
    else:
        chat_ids = await storage.get_user_chats(user["username"])

    chats = []
    for chat_id in sorted(chat_ids):
        cfg = await storage.get_chat_config(chat_id) or dict(DEFAULT_CHAT_CONFIG)
        stats = await storage.get_stats(chat_id)
        owner = await storage.get_chat_owner(chat_id) if is_superadmin(user) else None
        chats.append({"chat_id": chat_id, "cfg": cfg, "stats": stats, "owner": owner})

    muted_count = await storage.get_muted_forever_count()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "chats": chats,
            "muted_count": muted_count,
            "is_superadmin": is_superadmin(user),
        },
    )


# ── Chat detail ───────────────────────────────────────────────────────────────


async def _can_access_chat(user: Dict, chat_id: int, storage: Storage) -> bool:
    if is_superadmin(user):
        return True
    owner = await storage.get_chat_owner(chat_id)
    return owner == user["username"]


@app.get("/chats/{chat_id}", response_class=HTMLResponse)
async def chat_detail(request: Request, chat_id: int):
    user = await get_current_user(request)
    if redir := check_auth(user):
        return redir

    storage: Storage = app.state.storage

    if not await _can_access_chat(user, chat_id, storage):
        return HTMLResponse("403 Доступ запрещён.", status_code=403)

    cfg = await storage.get_chat_config(chat_id)
    if cfg is None:
        return HTMLResponse("Чат не найден.", status_code=404)

    stats = await storage.get_stats(chat_id)
    muted_list = await storage.get_muted_forever_list()

    return templates.TemplateResponse(
        "chat.html",
        {
            "request": request,
            "user": user,
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
    user = await get_current_user(request)
    if redir := check_auth(user):
        return redir

    storage: Storage = app.state.storage

    if not await _can_access_chat(user, chat_id, storage):
        return HTMLResponse("403 Доступ запрещён.", status_code=403)

    cfg = await storage.get_chat_config(chat_id) or dict(DEFAULT_CHAT_CONFIG)
    cfg["captcha_timeout"] = max(30, captcha_timeout)
    cfg["captcha_attempts"] = max(1, captcha_attempts)
    cfg["enabled"] = enabled == "on"
    cfg["welcome_text"] = welcome_text.strip() or None
    await storage.save_chat_config(chat_id, cfg)

    stats = await storage.get_stats(chat_id)
    muted_list = await storage.get_muted_forever_list()

    return templates.TemplateResponse(
        "chat.html",
        {
            "request": request,
            "user": user,
            "chat_id": chat_id,
            "cfg": cfg,
            "stats": stats,
            "muted_list": muted_list,
            "saved": True,
        },
    )


@app.post("/chats/{chat_id}/unmute/{user_id}", response_class=HTMLResponse)
async def web_unmute(request: Request, chat_id: int, user_id: int):
    user = await get_current_user(request)
    if redir := check_auth(user):
        return redir

    storage: Storage = app.state.storage

    if not await _can_access_chat(user, chat_id, storage):
        return HTMLResponse("403 Доступ запрещён.", status_code=403)

    await storage.remove_muted_forever(user_id)
    await storage.push_unmute_request(chat_id, user_id)
    return HTMLResponse("")


# ── SSE event stream ──────────────────────────────────────────────────────────


@app.get("/events/stream")
async def events_stream(request: Request):
    user = await get_current_user(request)
    if user is None:
        return RedirectResponse("/login", status_code=302)

    storage: Storage = app.state.storage

    async def generator():
        async for event in storage.subscribe_events():
            if await request.is_disconnected():
                break
            yield {"data": json.dumps(event)}

    return EventSourceResponse(generator())


# ── Admin: user management ────────────────────────────────────────────────────


@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users(request: Request):
    user = await get_current_user(request)
    if redir := check_auth(user):
        return redir
    if err := check_superadmin(user):
        return err

    storage: Storage = app.state.storage
    usernames = await storage.list_users()

    users_data = []
    for uname in sorted(usernames):
        u = await storage.get_user(uname)
        if u:
            chat_count = len(await storage.get_user_chats(uname))
            users_data.append({**u, "chat_count": chat_count})

    return templates.TemplateResponse(
        "admin_users.html",
        {"request": request, "user": user, "users": users_data},
    )


@app.post("/admin/users/create", response_class=HTMLResponse)
async def admin_create_user(
    request: Request,
    new_username: str = Form(...),
    new_password: str = Form(...),
    plan: str = Form(default="free"),
    telegram_id: str = Form(default=""),
):
    user = await get_current_user(request)
    if redir := check_auth(user):
        return redir
    if err := check_superadmin(user):
        return err

    storage: Storage = app.state.storage
    settings: Settings = app.state.settings
    from web.users import hash_password

    new_username = new_username.strip().lower()
    error = None

    if not new_username or not new_password:
        error = "Имя пользователя и пароль обязательны."
    elif await storage.user_exists(new_username):
        error = f"Пользователь «{new_username}» уже существует."
    else:
        tg_id = int(telegram_id.strip()) if telegram_id.strip().lstrip("-").isdigit() else None
        max_chats = -1 if plan == "pro" else 1
        data = {
            "username": new_username,
            "password_hash": hash_password(new_password),
            "role": "user",
            "plan": plan,
            "max_chats": max_chats,
            "telegram_id": tg_id,
            "created_at": datetime.datetime.utcnow().isoformat(),
        }
        await storage.create_user(new_username, data)
        if tg_id:
            await storage.set_telegram_mapping(tg_id, new_username)

    usernames = await storage.list_users()
    users_data = []
    for uname in sorted(usernames):
        u = await storage.get_user(uname)
        if u:
            chat_count = len(await storage.get_user_chats(uname))
            users_data.append({**u, "chat_count": chat_count})

    return templates.TemplateResponse(
        "admin_users.html",
        {"request": request, "user": user, "users": users_data, "error": error, "success": not error},
    )


@app.post("/admin/users/{target_username}/update", response_class=HTMLResponse)
async def admin_update_user(
    request: Request,
    target_username: str,
    plan: str = Form(...),
    telegram_id: str = Form(default=""),
):
    user = await get_current_user(request)
    if redir := check_auth(user):
        return redir
    if err := check_superadmin(user):
        return err

    storage: Storage = app.state.storage
    target = await storage.get_user(target_username)
    if not target:
        return HTMLResponse("Пользователь не найден.", status_code=404)

    # Update telegram mapping if changed
    old_tg = target.get("telegram_id")
    new_tg = int(telegram_id.strip()) if telegram_id.strip().lstrip("-").isdigit() else None

    if old_tg and old_tg != new_tg:
        await storage.remove_telegram_mapping(old_tg)
    if new_tg:
        await storage.set_telegram_mapping(new_tg, target_username)

    target["plan"] = plan
    target["max_chats"] = -1 if plan == "pro" else 1
    target["telegram_id"] = new_tg
    await storage.update_user(target_username, target)

    return RedirectResponse("/admin/users", status_code=302)


@app.post("/admin/users/{target_username}/delete", response_class=HTMLResponse)
async def admin_delete_user(request: Request, target_username: str):
    user = await get_current_user(request)
    if redir := check_auth(user):
        return redir
    if err := check_superadmin(user):
        return err

    settings: Settings = app.state.settings
    if target_username == settings.superadmin_username:
        return HTMLResponse("Нельзя удалить суперадмина.", status_code=400)

    storage: Storage = app.state.storage
    target = await storage.get_user(target_username)
    if target and target.get("telegram_id"):
        await storage.remove_telegram_mapping(target["telegram_id"])
    await storage.delete_user(target_username)

    return RedirectResponse("/admin/users", status_code=302)


# ── Account (personal cabinet) ────────────────────────────────────────────────


@app.get("/account", response_class=HTMLResponse)
async def account_page(request: Request):
    user = await get_current_user(request)
    if redir := check_auth(user):
        return redir
    return templates.TemplateResponse(
        "account.html",
        {"request": request, "user": user, "saved": False, "error": None},
    )


@app.post("/account/password", response_class=HTMLResponse)
async def account_change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
):
    user = await get_current_user(request)
    if redir := check_auth(user):
        return redir

    storage: Storage = app.state.storage
    from web.users import hash_password, verify_password as vp

    error = None
    saved = False

    if not vp(current_password, user["password_hash"]):
        error = "Текущий пароль неверен."
    elif len(new_password) < 6:
        error = "Новый пароль должен быть не менее 6 символов."
    else:
        user["password_hash"] = hash_password(new_password)
        await storage.update_user(user["username"], user)
        saved = True

    # Reload fresh copy
    user = await storage.get_user(user["username"])
    return templates.TemplateResponse(
        "account.html",
        {"request": request, "user": user, "saved": saved, "error": error},
    )


@app.post("/account/telegram", response_class=HTMLResponse)
async def account_set_telegram(
    request: Request,
    telegram_id: str = Form(default=""),
):
    user = await get_current_user(request)
    if redir := check_auth(user):
        return redir

    storage: Storage = app.state.storage

    old_tg = user.get("telegram_id")
    new_tg = int(telegram_id.strip()) if telegram_id.strip().lstrip("-").isdigit() else None

    if old_tg and old_tg != new_tg:
        await storage.remove_telegram_mapping(old_tg)
    if new_tg:
        await storage.set_telegram_mapping(new_tg, user["username"])

    user["telegram_id"] = new_tg
    await storage.update_user(user["username"], user)

    user = await storage.get_user(user["username"])
    return templates.TemplateResponse(
        "account.html",
        {"request": request, "user": user, "saved": True, "error": None},
    )
