from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import re

from dateparser.search import search_dates


@dataclass(frozen=True)
class ParsedReminder:
    text: str
    remind_at: datetime
    matched_date_text: str


FILLER_PATTERNS = [
    r"^\s*напомни(?:\s+мне)?\s+",
    r"^\s*поставь\s+напоминание\s+",
    r"^\s*создай\s+напоминание\s+",
]


def parse_reminder(raw_text: str, timezone_name: str) -> ParsedReminder | None:
    normalized = " ".join(raw_text.strip().split())
    if not normalized:
        return None

    tz = ZoneInfo(timezone_name)
    now = datetime.now(tz)
    dt = _find_datetime(normalized, now, timezone_name)
    if dt is None:
        return None

    matched_text, remind_at = dt
    if remind_at <= now:
        return None

    reminder_text = _cleanup_task_text(normalized, matched_text)
    if not reminder_text:
        reminder_text = normalized

    return ParsedReminder(
        text=reminder_text,
        remind_at=remind_at,
        matched_date_text=matched_text,
    )


def _find_datetime(text: str, now: datetime, timezone_name: str) -> tuple[str, datetime] | None:
    relative = _parse_relative(text, now)
    if relative:
        return relative

    found = search_dates(
        text,
        languages=["ru"],
        settings={
            "RELATIVE_BASE": now.replace(tzinfo=None),
            "TIMEZONE": timezone_name,
            "RETURN_AS_TIMEZONE_AWARE": True,
            "PREFER_DATES_FROM": "future",
        },
    )
    if not found:
        return None

    matched_text, parsed_dt = max(found, key=lambda item: len(item[0]))
    if parsed_dt.tzinfo is None:
        parsed_dt = parsed_dt.replace(tzinfo=ZoneInfo(timezone_name))

    return matched_text, parsed_dt.astimezone(ZoneInfo(timezone_name))


def _parse_relative(text: str, now: datetime) -> tuple[str, datetime] | None:
    match = re.search(
        r"(?:через|спустя)\s+(\d+)\s+"
        r"(минуту|минуты|минут|час|часа|часов|день|дня|дней|неделю|недели|недель)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None

    amount = int(match.group(1))
    unit = match.group(2).lower()
    if unit.startswith("минут"):
        delta = timedelta(minutes=amount)
    elif unit.startswith("час"):
        delta = timedelta(hours=amount)
    elif unit.startswith("д"):
        delta = timedelta(days=amount)
    else:
        delta = timedelta(weeks=amount)

    return match.group(0), now + delta


def _cleanup_task_text(text: str, matched_date_text: str) -> str:
    result = text
    for pattern in FILLER_PATTERNS:
        result = re.sub(pattern, "", result, flags=re.IGNORECASE)

    result = re.sub(re.escape(matched_date_text), "", result, count=1, flags=re.IGNORECASE)
    result = re.sub(r"\b(в|на|к|до)\s*$", "", result, flags=re.IGNORECASE)
    result = re.sub(r"\s+", " ", result)
    result = result.strip(" ,.-")
    return result
