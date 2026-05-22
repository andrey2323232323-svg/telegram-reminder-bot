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

WEEKDAYS = {
    "понедельник": 0,
    "понедельника": 0,
    "вторник": 1,
    "вторника": 1,
    "среду": 2,
    "среда": 2,
    "четверг": 3,
    "четверга": 3,
    "пятницу": 4,
    "пятница": 4,
    "субботу": 5,
    "суббота": 5,
    "воскресенье": 6,
    "воскресенья": 6,
}

RU_NUMBERS = {
    "ноль": 0,
    "один": 1,
    "одну": 1,
    "два": 2,
    "две": 2,
    "три": 3,
    "четыре": 4,
    "пять": 5,
    "шесть": 6,
    "семь": 7,
    "восемь": 8,
    "девять": 9,
    "десять": 10,
    "одиннадцать": 11,
    "двенадцать": 12,
    "тринадцать": 13,
    "четырнадцать": 14,
    "пятнадцать": 15,
    "шестнадцать": 16,
    "семнадцать": 17,
    "восемнадцать": 18,
    "девятнадцать": 19,
    "двадцать": 20,
    "двадцать один": 21,
    "двадцать два": 22,
    "двадцать три": 23,
}


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
    if _needs_time_clarification(normalized, matched_text, remind_at):
        raise ReminderNeedsClarification(
            f"В какое время {matched_text} вы хотите, чтобы я напомнил?"
        )

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


def apply_time_clarification(
    original_text: str,
    time_text: str,
    timezone_name: str = "Europe/Moscow",
) -> str | None:
    normalized_original = " ".join(original_text.strip().split())
    normalized_time = " ".join(time_text.strip().split())
    if not normalized_original or not normalized_time:
        return None
    if not is_time_clarification(normalized_time):
        return None

    clause_text = _apply_time_to_remind_clause(normalized_original, normalized_time)
    if clause_text:
        return clause_text

    now = datetime.now(ZoneInfo(timezone_name))
    dt = _find_datetime(normalized_original, now, timezone_name)
    if dt is None:
        return None

    matched_text, _ = dt
    if _has_explicit_time(matched_text):
        return None

    normalized_time = _normalize_time_clarification(normalized_time)
    return re.sub(
        re.escape(matched_text),
        f"{matched_text} {normalized_time}",
        normalized_original,
        count=1,
        flags=re.IGNORECASE,
    )


def _apply_time_to_remind_clause(normalized_original: str, normalized_time: str) -> str | None:
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

    return f"{reminder_prefix}{remind_clause} {_normalize_time_clarification(normalized_time)}{task_clause}"


def is_time_clarification(text: str) -> bool:
    normalized = _clean_phrase(text)
    if _parse_spoken_time(normalized):
        return True

    return bool(
        re.fullmatch(r"(?:в\s+|к\s+)?\d{1,2}(?::\d{2}|[.]\d{2})?", normalized)
        or re.fullmatch(
            r"(?:в\s+|к\s+)?\d{1,2}\s*(?:час(?:а|ов)?|утра|дня|вечера|ночи)",
            normalized,
        )
        or re.fullmatch(r"(?:утром|днем|днём|вечером|ночью|в полдень|в полночь)", normalized)
    )


def _normalize_time_clarification(text: str) -> str:
    normalized = _clean_phrase(text)

    spoken_time = _parse_spoken_time(normalized)
    if spoken_time:
        hour, minute = spoken_time
        return f"в {hour:02d}:{minute:02d}"

    hour_only = re.fullmatch(r"(?:в\s+|к\s+)?(\d{1,2})", normalized)
    if hour_only:
        return f"в {int(hour_only.group(1)):02d}:00"

    hour_minute = re.fullmatch(r"(?:в\s+|к\s+)?(\d{1,2})[:.](\d{2})", normalized)
    if hour_minute:
        return f"в {int(hour_minute.group(1)):02d}:{hour_minute.group(2)}"

    if not _has_explicit_time(normalized):
        return f"в {normalized}"

    return normalized


def _clean_phrase(text: str) -> str:
    return " ".join(text.strip().lower().strip(" .,!?").split())


def _parse_spoken_time(text: str) -> tuple[int, int] | None:
    normalized = re.sub(r"^(?:в|к)\s+", "", text)
    normalized = re.sub(r"\s+час(?:а|ов)?$", "", normalized)
    normalized = normalized.replace("ноль ноль", "ноль")

    if normalized in RU_NUMBERS:
        return RU_NUMBERS[normalized], 0

    parts = normalized.split()
    if len(parts) >= 2:
        hour_text = " ".join(parts[:-1])
        minute_text = parts[-1]
        if hour_text in RU_NUMBERS and minute_text in RU_NUMBERS:
            hour = RU_NUMBERS[hour_text]
            minute = RU_NUMBERS[minute_text]
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return hour, minute

    return None


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

    weekday_with_time = _parse_weekday_with_time(text, now)
    if weekday_with_time:
        return weekday_with_time

    weekday_date = _parse_weekday_date(text, now)
    if weekday_date:
        return weekday_date

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


def _parse_weekday_with_time(text: str, now: datetime) -> tuple[str, datetime] | None:
    weekday_pattern = "|".join(WEEKDAYS)
    match = re.search(
        rf"\b(?:(?:в|во)\s+)?({weekday_pattern})\b.*?\b(?:в|к)\s+(\d{{1,2}})(?::(\d{{2}})|[.](\d{{2}}))?",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None

    weekday_text = match.group(1).lower()
    hour = int(match.group(2))
    minute = int(match.group(3) or match.group(4) or 0)
    if hour > 23 or minute > 59:
        return None

    target_weekday = WEEKDAYS[weekday_text]
    days_ahead = (target_weekday - now.weekday()) % 7
    remind_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=days_ahead)
    if remind_at <= now:
        remind_at += timedelta(days=7)

    return match.group(0), remind_at


def _parse_weekday_date(text: str, now: datetime) -> tuple[str, datetime] | None:
    weekday_pattern = "|".join(WEEKDAYS)
    match = re.search(
        rf"\b(?:(?:в|во)\s+)?({weekday_pattern})\b",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None

    weekday_text = match.group(1).lower()
    target_weekday = WEEKDAYS[weekday_text]
    days_ahead = (target_weekday - now.weekday()) % 7
    remind_at = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=days_ahead)
    if remind_at <= now:
        remind_at += timedelta(days=7)

    return match.group(0), remind_at


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


def _needs_time_clarification(full_text: str, matched_text: str, remind_at: datetime) -> bool:
    if _has_explicit_time(matched_text):
        return False

    if _has_explicit_time(full_text):
        return False

    # dateparser silently turns date-only phrases like "в четверг" into 00:00.
    # For reminders, midnight is almost never intended unless the user said it.
    if remind_at.hour == 0 and remind_at.minute == 0:
        return True

    return True


def _cleanup_task_text(text: str, matched_date_text: str) -> str:
    result = text
    for pattern in FILLER_PATTERNS:
        result = re.sub(pattern, "", result, flags=re.IGNORECASE)

    result = re.sub(re.escape(matched_date_text), "", result, count=1, flags=re.IGNORECASE)
    result = re.sub(r"\b(в|на|к|до)\s*$", "", result, flags=re.IGNORECASE)
    result = re.sub(r"\s+", " ", result)
    result = result.strip(" ,.-")
    return result
