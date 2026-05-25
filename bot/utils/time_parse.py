from __future__ import annotations

from datetime import datetime

DATE_TIME_FORMAT = "%d.%m.%Y %H:%M"
TIME_FORMAT = "%H:%M"


def parse_datetime(value: str) -> datetime:
    return datetime.strptime(value, DATE_TIME_FORMAT)
