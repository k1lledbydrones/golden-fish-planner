from __future__ import annotations

from dataclasses import dataclass
import os

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class AppConfig:
    bot_token: str
    default_timezone: str
    database_path: str
    log_file_path: str


def load_config() -> AppConfig:
    bot_token = os.getenv("BOT_TOKEN", "").strip()
    default_timezone = os.getenv("DEFAULT_TIMEZONE", "Europe/Moscow").strip()
    database_path = os.getenv("DATABASE_PATH", "bot.db").strip()
    log_file_path = os.getenv("LOG_FILE_PATH", "logs/bot.log").strip()

    if not bot_token:
        raise RuntimeError("BOT_TOKEN is required")

    return AppConfig(
        bot_token=bot_token,
        default_timezone=default_timezone,
        database_path=database_path,
        log_file_path=log_file_path,
    )
