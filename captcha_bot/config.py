from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    bot_token: str
    chat_id: int
    admin_ids: List[int] = []
    captcha_timeout: int = 300
    captcha_attempts: int = 2
    redis_url: str = "redis://redis:6379"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @field_validator("admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, v: object) -> List[int]:
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        if isinstance(v, int):
            return [v]
        return v  # type: ignore[return-value]
