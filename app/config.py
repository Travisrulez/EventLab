from __future__ import annotations

import os
from dataclasses import dataclass

def load_env_file(path: str = ".env") -> None:
    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()

            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")

            os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    secret_key: str
    db_path: str
    base_url: str
    cookie_secure: bool
    token_ttl_hours: int
    app_name: str = "Diploma EventLab"


def get_settings() -> Settings:
    load_env_file()
    
    return Settings(
        secret_key=os.getenv("EVENTLAB_SECRET_KEY", "dev-secret-change-me"),
        db_path=os.getenv("EVENTLAB_DB_PATH", "./eventlab.db"),
        base_url=os.getenv("EVENTLAB_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
        cookie_secure=os.getenv("EVENTLAB_COOKIE_SECURE", "0") in {"1", "true", "True", "yes"},
        token_ttl_hours=int(os.getenv("EVENTLAB_TOKEN_TTL_HOURS", "24")),
    )
