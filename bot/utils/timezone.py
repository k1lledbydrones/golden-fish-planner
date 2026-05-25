from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


def get_zoneinfo(timezone_name: str) -> ZoneInfo:
    return ZoneInfo(timezone_name)


def attach_timezone(value: datetime, timezone_name: str) -> datetime:
    return value.replace(tzinfo=get_zoneinfo(timezone_name))


def to_utc(value: datetime, timezone_name: str) -> datetime:
    local_value = attach_timezone(value, timezone_name)
    return local_value.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def from_utc(value: datetime, timezone_name: str) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo("UTC"))
    return value.astimezone(get_zoneinfo(timezone_name))
