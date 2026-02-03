from __future__ import annotations

from datetime import datetime

from dateutil import tz
from dateutil.parser import isoparse


class TimeParseError(ValueError):
    pass


def parse_datetime(value: str, *, default_tz: str | None = None) -> datetime:
    """Parse an ISO-ish datetime string.

    - Accepts common ISO variants (including a trailing `Z`).
    - If the parsed datetime is naive, assume local timezone unless default_tz is provided.
    - Returns an aware datetime.
    """
    try:
        dt = isoparse(value)
    except (ValueError, TypeError) as e:
        raise TimeParseError(f"Invalid datetime: {value!r}. Use ISO format.") from e

    if dt.tzinfo is None:
        tzinfo = tz.gettz(default_tz) if default_tz else tz.tzlocal()
        if tzinfo is None:
            raise TimeParseError(f"Unknown timezone: {default_tz!r}")
        dt = dt.replace(tzinfo=tzinfo)

    return dt
