"""Configuration loader. Reads secrets from environment / .env file.

Secrets never live in code. Copy .env.example to .env and fill in the values.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

# A token still holding its placeholder value counts as "not set".
_PLACEHOLDERS = {
    "",
    "PUT_YOUR_TELEGRAM_BOT_TOKEN_HERE",
    "PUT_YOUR_GEMINI_API_KEY_HERE",
}


def _clean(value: str | None) -> str:
    value = (value or "").strip()
    return "" if value in _PLACEHOLDERS else value


@dataclass
class Config:
    telegram_token: str
    gemini_api_key: str
    db_path: str

    @property
    def has_gemini(self) -> bool:
        return bool(self.gemini_api_key)

    def require_telegram(self) -> None:
        if not self.telegram_token:
            raise SystemExit(
                "TELEGRAM_BOT_TOKEN is missing.\n"
                "  1. Copy .env.example to .env\n"
                "  2. Paste your BotFather token into TELEGRAM_BOT_TOKEN\n"
                "See README.md for step-by-step setup."
            )


def load_config() -> Config:
    return Config(
        telegram_token=_clean(os.getenv("TELEGRAM_BOT_TOKEN")),
        gemini_api_key=_clean(os.getenv("GEMINI_API_KEY")),
        # On Fly.io / Oracle this points at a persistent volume so streaks survive restarts.
        db_path=os.getenv("DB_PATH", "ldr.db").strip() or "ldr.db",
    )
