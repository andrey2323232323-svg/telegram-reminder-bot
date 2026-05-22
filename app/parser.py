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


class ReminderNeedsClarification(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


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
    clause_reminder = _parse_remind_clause_before_what(normalized, now, timezone_name)
    if clause_reminder:
        return clause_reminder

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


def apply_time_clarification(original_text: str, time_text: str) -> str | None:
    normalized_original = " ".join(original_text.strip().split())
    normalized_time = " ".join(time_text.strip().split())
    if not normalized_original or not normalized_time:
        return None
    if not is_time_clarification(normalized_time):
        return None

    match = re.match(
        r"^(\s*(?:напомни(?:\s+мне)?|поставь\s+напоминание|создай\s+напоминание)\s+)(.+?)(\s*,?\s+что\s+.+)$",
        normalized_original,
        re.IGNORECASE,
    )
    if not match:
        return None

    reminder_prefix = match.group(1)
    remind_clause = match.group(2).strip()
    task_clause = match.group(3)
    if not _has_explicit_time(normalized_time):
        normalized_time = f"в {normalized_time}"

    return f"{reminder_prefix}{remind_clause} {normalized_time}{task_clause}"


def is_time_clarification(text: str) -> bool:
    normalized = " ".join(text.strip().lower().split())
    return bool(
        re.fullmatch(r"(?:в\s+|к\s+)?\d{1,2}(?::\d{2}|[.]\d{2})?", normalized)
        or re.fullmatch(
            r"(?:в\s+|к\s+)?\d{1,2}\s*(?:час(?:а|ов)?|утра|дня|вечера|ночи)",
            normalized,
        )
        or re.fullmatch(r"(?:утром|днем|днём|вечером|ночью|в полдень|в полночь)", normalized)
    )


def _parse_remind_clause_before_what(
    text: str,
    now: datetime,
    timezone_name: str,
) -> ParsedReminder | None:
    match = re.match(
        r"^\s*(?:напомни(?:\s+мне)?|поставь\s+напоминание|создай\s+напоминание)\s+(.+?)\s*,?\s+что\s+(.+)$",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None

    remind_clause = match.group(1).strip()
    task_text = match.group(2).strip(" ,.-")
    if not remind_clause:
        return None

    dt = _find_datetime(remind_clause, now, timezone_name)
    if dt is None:
        return None

    matched_text, remind_at = dt
    if not _has_explicit_time(remind_clause):
        raise ReminderNeedsClarification(
            f"В какое время {remind_clause} вы хотите, чтобы я напомнил?"
        )

    if remind_at <= now:
        return None

    return ParsedReminder(
        text=task_text,
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


def _has_explicit_time(text: str) -> bool:
    return bool(
        re.search(r"\b\d{1,2}[:.]\d{2}\b", text)
        or re.search(
            r"\b(?:в|к|на)\s+\d{1,2}\s*(?:час(?:а|ов)?|утра|дня|вечера|ночи)?\b",
            text,
            re.IGNORECASE,
        )
        or re.search(r"\b(утром|днем|днём|вечером|ночью|полдень|полночь)\b", text, re.IGNORECASE)
    )


def _cleanup_task_text(text: str, matched_date_text: str) -> str:
    result = text
    for pattern in FILLER_PATTERNS:
        result = re.sub(pattern, "", result, flags=re.IGNORECASE)

    result = re.sub(re.escape(matched_date_text), "", result, count=1, flags=re.IGNORECASE)
    result = re.sub(r"\b(в|на|к|до)\s*$", "", result, flags=re.IGNORECASE)
    result = re.sub(r"\s+", " ", result)
    result = result.strip(" ,.-")
    return result
