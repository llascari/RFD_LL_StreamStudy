"""A shared analysis window: presets or an explicit start/end date.

Both the rainfall→flow model and the temperature statistics use this, so
"last 30 days" means the same thing everywhere and can be reproduced later.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

PRESETS: tuple[tuple[str, str, int], ...] = (
    ("1d", "Last 24 hours", 1),
    ("7d", "Last 7 days", 7),
    ("30d", "Last 30 days", 30),
    ("90d", "Last 90 days", 90),
    ("1y", "Last 1 year", 365),
    ("2y", "Last 2 years", 730),
    ("5y", "Last 5 years", 1825),
)
PRESET_BY_KEY = {key: (label, days) for key, label, days in PRESETS}
PRESET_LABELS = [label for _key, label, _days in PRESETS]
LABEL_TO_KEY = {label: key for key, label, _days in PRESETS}
CUSTOM_LABEL = "Custom range\u2026"


@dataclass(frozen=True)
class TimeWindow:
    start: date
    end: date
    label: str = ""

    @property
    def days(self) -> int:
        return max(1, (self.end - self.start).days + 1)

    @property
    def hours(self) -> float:
        return self.days * 24.0

    @property
    def range_label(self) -> str:
        return f"{self.start.isoformat()} \u2192 {self.end.isoformat()}"

    def clipped(self, today: date | None = None) -> "TimeWindow":
        today = today or date.today()
        end = min(self.end, today)
        start = min(self.start, end)
        return TimeWindow(start=start, end=end, label=self.label)


def preset_window(key: str, today: date | None = None) -> TimeWindow:
    today = today or date.today()
    label, days = PRESET_BY_KEY.get(key, PRESET_BY_KEY["1y"])
    return TimeWindow(
        start=today - timedelta(days=days - 1), end=today, label=label
    )


def last_years_window(years: int, today: date | None = None) -> TimeWindow:
    today = today or date.today()
    years = max(1, int(years))
    try:
        start = today.replace(year=today.year - years)
    except ValueError:  # 29 February
        start = today.replace(year=today.year - years, day=28)
    return TimeWindow(start=start, end=today, label=f"Last {years} years")


def custom_window(start: date, end: date) -> TimeWindow:
    if end < start:
        raise ValueError("The end date must not be before the start date.")
    return TimeWindow(
        start=start, end=end, label=f"{start.isoformat()} \u2192 {end.isoformat()}"
    )


def parse_custom(start_text: str, end_text: str, today: date | None = None) -> TimeWindow:
    today = today or date.today()
    try:
        start = date.fromisoformat(start_text.strip())
        end = date.fromisoformat(end_text.strip())
    except ValueError:
        raise ValueError("Use dates in YYYY-MM-DD format.") from None
    if end > today:
        end = today
    if start > end:
        raise ValueError("The start date must not be after the end date.")
    return custom_window(start, end)


def key_for_window(window: TimeWindow, today: date | None = None) -> str | None:
    today = today or date.today()
    if window.end != today:
        return None
    for key, _label, days in PRESETS:
        if window.days == days:
            return key
    return None


def window_from_settings(data: dict | None, today: date | None = None) -> TimeWindow:
    today = today or date.today()
    data = data or {}
    mode = str(data.get("mode", "1y"))
    if mode in PRESET_BY_KEY:
        return preset_window(mode, today)
    if mode == "custom":
        try:
            return parse_custom(str(data.get("start", "")), str(data.get("end", "")), today)
        except ValueError:
            pass
    return preset_window("1y", today)


def window_to_settings(window: TimeWindow, today: date | None = None) -> dict:
    key = key_for_window(window, today)
    if key is not None:
        return {"mode": key}
    return {
        "mode": "custom",
        "start": window.start.isoformat(),
        "end": window.end.isoformat(),
    }
