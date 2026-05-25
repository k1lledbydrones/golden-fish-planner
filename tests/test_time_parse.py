from __future__ import annotations

from datetime import datetime

import pytest

from bot.utils.time_parse import DATE_TIME_FORMAT, TIME_FORMAT, parse_datetime


class TestParseDatetime:
    def test_valid_format(self):
        result = parse_datetime("22.05.2026 18:30")
        assert result == datetime(2026, 5, 22, 18, 30)

    def test_midnight(self):
        result = parse_datetime("01.01.2026 00:00")
        assert result == datetime(2026, 1, 1, 0, 0)

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError):
            parse_datetime("not a date")

    def test_invalid_date_raises(self):
        with pytest.raises(ValueError):
            parse_datetime("32.13.2026 10:00")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            parse_datetime("")


class TestFormatConstants:
    def test_date_time_format(self):
        assert DATE_TIME_FORMAT == "%d.%m.%Y %H:%M"

    def test_time_format(self):
        assert TIME_FORMAT == "%H:%M"
