from __future__ import annotations

from telebot.types import User as TgUser

from bot.config import load_config
from bot.db.models import Category, User
from bot.utils.timezone import get_zoneinfo

DEFAULT_CATEGORIES = ["учёба", "работа"]


def ensure_user(tg_user: TgUser) -> User:
    config = load_config()
    user, created = User.get_or_create(
        telegram_id=tg_user.id,
        defaults={"timezone": config.default_timezone},
    )
    if tg_user.username and user.username != tg_user.username:
        user.username = tg_user.username
        user.save()
    if created:
        for cat_name in DEFAULT_CATEGORIES:
            Category.get_or_create(user=user, name=cat_name)
    return user


def get_user_by_telegram_id(telegram_id: int) -> User:
    return User.get(User.telegram_id == telegram_id)


def set_user_timezone(telegram_id: int, timezone_name: str) -> str:
    try:
        get_zoneinfo(timezone_name)
    except Exception:
        return "🌍 Неверная таймзона. Пример: Europe/Moscow"
    user = User.get(User.telegram_id == telegram_id)
    user.timezone = timezone_name
    user.save()
    return f"✅ Таймзона обновлена: {timezone_name}"


def set_active_start(telegram_id: int, hour: int) -> str:
    if hour < 0 or hour > 23:
        return "⛔ Час должен быть от 0 до 23"
    user = User.get(User.telegram_id == telegram_id)
    if hour >= user.day_end_hour:
        return (
            f"⛔ Начало ({hour}:00) должно быть раньше конца ({user.day_end_hour}:00)"
        )
    user.day_start_hour = hour
    user.save()
    return f"✅ Начало активности: {hour}:00"


def set_active_end(telegram_id: int, hour: int) -> str:
    if hour < 0 or hour > 23:
        return "⛔ Час должен быть от 0 до 23"
    user = User.get(User.telegram_id == telegram_id)
    if hour <= user.day_start_hour:
        return (
            f"⛔ Конец ({hour}:00) должен быть позже начала ({user.day_start_hour}:00)"
        )
    user.day_end_hour = hour
    user.save()
    return f"✅ Конец активности: {hour}:00"
