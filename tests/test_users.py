from __future__ import annotations

import pytest
from telebot.types import User as TgUser

from bot.db.models import Category, User
from bot.services.users import (
    ensure_user,
    get_user_by_telegram_id,
    set_active_end,
    set_active_start,
    set_user_timezone,
)


class TestEnsureUser:
    def test_creates_new_user(self, tg_user: TgUser):
        user = ensure_user(tg_user)
        assert user.telegram_id == 12345
        assert user.timezone == "Europe/Moscow"
        assert user.day_start_hour == 8
        assert user.day_end_hour == 23

    def test_creates_default_categories(self, tg_user: TgUser):
        ensure_user(tg_user)
        cats = Category.select().where(Category.user == User.get_by_id(1))
        names = [c.name for c in cats]
        assert "учёба" in names
        assert "работа" in names

    def test_returns_existing_user(self, tg_user: TgUser):
        user1 = ensure_user(tg_user)
        user2 = ensure_user(tg_user)
        assert user1.id == user2.id

    def test_does_not_duplicate_categories(self, tg_user: TgUser):
        ensure_user(tg_user)
        ensure_user(tg_user)
        cats = Category.select().where(Category.user == User.get_by_id(1))
        assert cats.count() == 2

    def test_uses_provided_timezone(self):
        tg = TgUser(id=777, is_bot=False, first_name="Custom")
        user = ensure_user(tg)
        assert user.timezone == "Europe/Moscow"


class TestGetUserByTelegramId:
    def test_returns_user(self, user: User):
        result = get_user_by_telegram_id(12345)
        assert result.id == user.id

    def test_raises_if_not_found(self):
        with pytest.raises(Exception):
            get_user_by_telegram_id(-1)


class TestSetUserTimezone:
    def test_valid_timezone(self, user: User):
        result = set_user_timezone(12345, "Asia/Tokyo")
        assert "обновлена" in result
        fetched = User.get_by_id(user.id)
        assert fetched.timezone == "Asia/Tokyo"

    def test_invalid_timezone(self, user: User):
        result = set_user_timezone(12345, "Bad/Zone")
        assert "Неверная" in result

    def test_user_not_found(self):
        with pytest.raises(Exception):
            set_user_timezone(-1, "Europe/Moscow")


class TestSetActiveStart:
    def test_valid_hour(self, user: User):
        result = set_active_start(12345, 9)
        assert "9" in result
        fetched = User.get_by_id(user.id)
        assert fetched.day_start_hour == 9

    def test_hour_too_low(self, user: User):
        result = set_active_start(12345, -1)
        assert "0 до 23" in result

    def test_hour_too_high(self, user: User):
        result = set_active_start(12345, 24)
        assert "0 до 23" in result

    def test_hour_not_before_end(self, user: User):
        result = set_active_start(12345, 23)
        assert "раньше конца" in result

    def test_user_not_found(self):
        with pytest.raises(Exception):
            set_active_start(-1, 9)


class TestSetActiveEnd:
    def test_valid_hour(self, user: User):
        result = set_active_end(12345, 22)
        assert "22" in result
        fetched = User.get_by_id(user.id)
        assert fetched.day_end_hour == 22

    def test_hour_too_low(self, user: User):
        result = set_active_end(12345, -1)
        assert "0 до 23" in result

    def test_hour_too_high(self, user: User):
        result = set_active_end(12345, 24)
        assert "0 до 23" in result

    def test_hour_not_after_start(self, user: User):
        result = set_active_end(12345, 8)
        assert "позже начала" in result

    def test_user_not_found(self):
        with pytest.raises(Exception):
            set_active_end(-1, 22)
