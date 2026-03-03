from typing import List, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    bot_token: str
    # Optional: if set, bot auto-configures this chat on startup (backward compat)
    chat_id: Optional[int] = None
    admin_ids: List[int] = []
    captcha_timeout: int = 300
    captcha_attempts: int = 2
    redis_url: str = "redis://redis:6379"
    # Web panel — cookie signing key (keep secret)
    web_secret_key: str = "changeme"
    # Superadmin credentials — used ONLY on first startup to create the account
    superadmin_username: str = "admin"
    superadmin_password: str = "changeme-admin"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "env_ignore_empty": True,  # empty ADMIN_IDS= → use default []
    }

    @field_validator("admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, v: object) -> List[int]:
        if isinstance(v, list):           # already decoded JSON array
            return [int(x) for x in v]
        if isinstance(v, int):            # single int from JSON decode
            return [v]
        if isinstance(v, str):
            v = v.strip()
            if not v or v == "[]":
                return []
            if v.startswith("["):         # "[123,456]" format
                import json
                return [int(x) for x in json.loads(v)]
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return []
