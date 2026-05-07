from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    secret_key: str
    db_path: str
    base_url: str
    cookie_secure: bool
    token_ttl_hours: int
    app_name: str = "Diploma EventLab"


def get_settings() -> Settings:
    return Settings(
        secret_key=os.getenv("EVENTLAB_SECRET_KEY", "dev-secret-change-me"),
        db_path=os.getenv("EVENTLAB_DB_PATH", "./eventlab.db"),
        base_url=os.getenv("EVENTLAB_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
        cookie_secure=os.getenv("EVENTLAB_COOKIE_SECURE", "0") in {"1", "true", "True", "yes"},
        token_ttl_hours=int(os.getenv("EVENTLAB_TOKEN_TTL_HOURS", "24")),
    )
