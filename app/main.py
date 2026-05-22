import asyncio
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

from app.config import Settings
from app.config import load_settings
from app.db import ReminderRepository
from app.parser import (
    ReminderNeedsClarification,
    apply_time_clarification,
    is_time_clarification,
    parse_reminder,
)
from app.scheduler import ReminderScheduler
from app.transcribe import TranscriptionError, VoiceTranscriber


router = Router()


def format_dt(value) -> str:
    return value.strftime("%d.%m.%Y %H:%M")


def display_name(message: Message) -> str:
    user = message.from_user
    if user is None:
        return "друг"
    return user.first_name or user.full_name or "друг"


@router.message(CommandStart())
async def start(message: Message) -> None:
    name = display_name(message)
    await message.answer(
        f"Привет, {name}. Напиши дело с датой и временем, а я напомню.\n\n"
        "Примеры:\n"
        "завтра в 10:30 позвонить врачу\n"
        "через 2 часа проверить духовку\n\n"
        "Голосовые тоже можно отправлять."
    )


@router.message(Command("list"))
async def list_reminders(message: Message, repo: ReminderRepository) -> None:
    reminders = await repo.list_pending(message.chat.id)
    if not reminders:
        await message.answer("Активных напоминаний нет.")
        return

    lines = [
        f"{item.id}. {format_dt(item.remind_at)} - {item.text}"
        for item in reminders
    ]
    await message.answer("Активные напоминания:\n" + "\n".join(lines))


@router.message(Command("cancel"))
async def cancel_reminder(message: Message, repo: ReminderRepository, scheduler: ReminderScheduler) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Напиши так: /cancel 12")
        return

    reminder_id = int(parts[1])
    cancelled = await repo.cancel(reminder_id, message.chat.id)
    if not cancelled:
        await message.answer("Не нашел активное напоминание с таким ID.")
        return

    scheduler.remove(reminder_id)
    await message.answer("Готово, отменил.")


@router.message(F.voice)
async def handle_voice(
    message: Message,
    transcriber: VoiceTranscriber,
    repo: ReminderRepository,
    scheduler: ReminderScheduler,
    settings: Settings,
    pending_clarifications: dict[int, str],
) -> None:
    if not transcriber.enabled:
        await message.answer("Голосовые пока не включены: нужно добавить OPENAI_API_KEY в .env.")
        return

    try:
        text = await transcriber.transcribe_telegram_voice(message.bot, message.voice)
    except TranscriptionError as exc:
        logging.exception("Voice transcription failed")
        await message.answer(str(exc))
        return
    except Exception:
        logging.exception("Voice transcription failed")
        await message.answer("Не получилось расшифровать голосовое. Попробуй еще раз или напиши текстом.")
        return

    await message.answer(f"Расшифровал, {display_name(message)}: {text}")
    await create_reminder_from_text(
        message,
        text,
        repo,
        scheduler,
        settings.timezone,
        pending_clarifications,
    )


@router.message(F.text)
async def handle_text(
    message: Message,
    repo: ReminderRepository,
    scheduler: ReminderScheduler,
    settings: Settings,
    pending_clarifications: dict[int, str],
) -> None:
    source_text = message.text or ""
    if await handle_cancel_phrase(message, source_text, repo, scheduler, pending_clarifications):
        return

    pending_text = pending_clarifications.get(message.chat.id)
    if pending_text and is_time_clarification(source_text):
        clarified_text = apply_time_clarification(pending_text, source_text)
        if clarified_text:
            saved = await create_reminder_from_text(
                message,
                clarified_text,
                repo,
                scheduler,
                settings.timezone,
                pending_clarifications,
                store_clarification=False,
            )
            if saved:
                pending_clarifications.pop(message.chat.id, None)
            return

    await create_reminder_from_text(
        message,
        source_text,
        repo,
        scheduler,
        settings.timezone,
        pending_clarifications,
    )


async def handle_cancel_phrase(
    message: Message,
    source_text: str,
    repo: ReminderRepository,
    scheduler: ReminderScheduler,
    pending_clarifications: dict[int, str],
) -> bool:
    normalized = " ".join(source_text.strip().lower().split())
    if normalized == "отмени все напоминания":
        reminder_ids = await repo.cancel_all(message.chat.id)
        for reminder_id in reminder_ids:
            scheduler.remove(reminder_id)
        pending_clarifications.pop(message.chat.id, None)

        if not reminder_ids:
            await message.answer("Активных напоминаний нет.")
            return True

        await message.answer(f"Готово, отменил все активные напоминания: {len(reminder_ids)}.")
        return True

    if normalized == "отмени последнее напоминание":
        reminder = await repo.cancel_last(message.chat.id)
        pending_clarifications.pop(message.chat.id, None)

        if reminder is None:
            await message.answer("Активных напоминаний нет.")
            return True

        scheduler.remove(reminder.id)
        await message.answer(f"Готово, отменил последнее напоминание: {reminder.text}")
        return True

    return False


async def create_reminder_from_text(
    message: Message,
    source_text: str,
    repo: ReminderRepository,
    scheduler: ReminderScheduler,
    timezone: str,
    pending_clarifications: dict[int, str],
    store_clarification: bool = True,
) -> bool:
    try:
        parsed = parse_reminder(source_text, timezone)
    except ReminderNeedsClarification as exc:
        if store_clarification:
            pending_clarifications[message.chat.id] = source_text
        await message.answer(exc.message)
        return False

    if parsed is None:
        await message.answer(
            "Я не понял дату и время. Попробуй так: `завтра в 10:30 позвонить врачу`.",
            parse_mode="Markdown",
        )
        return False

    reminder = await repo.add(
        chat_id=message.chat.id,
        text=parsed.text,
        remind_at=parsed.remind_at,
        source_text=source_text,
    )
    scheduler.schedule(reminder)

    await message.answer(
        f"Запомнил, {display_name(message)}: {reminder.text}\n"
        f"Напомню: {format_dt(reminder.remind_at)}\n"
        f"ID: {reminder.id}"
    )
    return True


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = load_settings()

    bot = Bot(token=settings.telegram_bot_token)
    repo = ReminderRepository(settings.database_path)
    await repo.init()

    scheduler = ReminderScheduler(bot, repo, settings.timezone)
    await scheduler.start()

    dispatcher = Dispatcher(
        settings=settings,
        repo=repo,
        scheduler=scheduler,
        pending_clarifications={},
        transcriber=VoiceTranscriber(
            api_key=settings.openai_api_key,
            model=settings.openai_transcribe_model,
        ),
    )
    dispatcher.include_router(router)

    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
