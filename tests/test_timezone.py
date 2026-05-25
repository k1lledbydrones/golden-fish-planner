from __future__ import annotations

from datetime import datetime

import pytest

from bot.utils.timezone import attach_timezone, from_utc, get_zoneinfo, to_utc


class TestGetZoneinfo:
    def test_valid_timezone(self):
        zi = get_zoneinfo("Europe/Moscow")
        assert str(zi) == "Europe/Moscow"

    def test_invalid_timezone(self):
        with pytest.raises(Exception):
            get_zoneinfo("Invalid/Timezone")


class TestAttachTimezone:
    def test_attaches_tzinfo(self):
        dt = datetime(2026, 5, 22, 10, 0)
        result = attach_timezone(dt, "Europe/Moscow")
        assert result.tzinfo is not None
        assert str(result.tzinfo) == "Europe/Moscow"
        assert result.hour == 10

    def test_preserves_values(self):
        dt = datetime(2026, 5, 22, 18, 30, 45)
        result = attach_timezone(dt, "Asia/Tokyo")
        assert result.year == 2026
        assert result.month == 5
        assert result.day == 22
        assert result.hour == 18
        assert result.minute == 30
        assert result.second == 45


class TestToUtc:
    def test_moscow_to_utc(self):
        dt = datetime(2026, 5, 22, 10, 0)
        result = to_utc(dt, "Europe/Moscow")
        assert result == datetime(2026, 5, 22, 7, 0)

    def test_tokyo_to_utc(self):
        dt = datetime(2026, 5, 22, 18, 0)
        result = to_utc(dt, "Asia/Tokyo")
        assert result == datetime(2026, 5, 22, 9, 0)

    def test_utc_to_utc(self):
        dt = datetime(2026, 5, 22, 12, 0)
        result = to_utc(dt, "UTC")
        assert result == datetime(2026, 5, 22, 12, 0)

    def test_returns_naive_datetime(self):
        dt = datetime(2026, 5, 22, 10, 0)
        result = to_utc(dt, "Europe/Moscow")
        assert result.tzinfo is None


class TestFromUtc:
    def test_utc_to_moscow(self):
        dt = datetime(2026, 5, 22, 7, 0)
        result = from_utc(dt, "Europe/Moscow")
        assert result.hour == 10
        assert str(result.tzinfo) == "Europe/Moscow"

    def test_preserves_date(self):
        dt = datetime(2026, 5, 22, 23, 0)
        result = from_utc(dt, "Europe/Moscow")
        assert result.day == 23
        assert result.hour == 2

    def test_handles_tz_aware_input(self):
        from zoneinfo import ZoneInfo

        dt = datetime(2026, 5, 22, 7, 0, tzinfo=ZoneInfo("UTC"))
        result = from_utc(dt, "Europe/Moscow")
        assert result.hour == 10

    def test_tokyo(self):
        dt = datetime(2026, 5, 22, 0, 0)
        result = from_utc(dt, "Asia/Tokyo")
        assert result.hour == 9
