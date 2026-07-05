from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

Period = Literal["mtd", "last-7d", "last-30d"]


@dataclass(frozen=True)
class DateRange:
    start: date
    end_exclusive: date

    @property
    def end_inclusive(self) -> date:
        return self.end_exclusive - timedelta(days=1)

    def openai_start_seconds(self) -> int:
        return _utc_midnight(self.start).timestamp().__int__()

    def openai_end_seconds(self) -> int:
        return _utc_midnight(self.end_exclusive).timestamp().__int__()

    def anthropic_start(self) -> str:
        return _rfc3339_z(self.start)

    def anthropic_end(self) -> str:
        return _rfc3339_z(self.end_exclusive)


def range_for_period(period: Period, today: date | None = None) -> DateRange:
    today = today or date.today()
    if period == "mtd":
        start = today.replace(day=1)
    elif period == "last-7d":
        start = today - timedelta(days=6)
    elif period == "last-30d":
        start = today - timedelta(days=29)
    else:
        raise ValueError(f"Unsupported period: {period}")
    return DateRange(start=start, end_exclusive=today + timedelta(days=1))


def parse_cli_range(start: str, end: str) -> DateRange:
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)
    if start_date > end_date:
        raise ValueError("--start must be on or before --end")
    return DateRange(start=start_date, end_exclusive=end_date + timedelta(days=1))


def _utc_midnight(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def _rfc3339_z(value: date) -> str:
    return _utc_midnight(value).strftime("%Y-%m-%dT%H:%M:%SZ")
