from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

from app.db import Reminder, ReminderRepository


class ReminderScheduler:
    def __init__(self, bot: Bot, repo: ReminderRepository, timezone: str) -> None:
        self.bot = bot
        self.repo = repo
        self.scheduler = AsyncIOScheduler(timezone=timezone)

    async def start(self) -> None:
        self.scheduler.start()
        for reminder in await self.repo.list_pending():
            self.schedule(reminder)

    def schedule(self, reminder: Reminder) -> None:
        self.scheduler.add_job(
            self._send_reminder,
            trigger=DateTrigger(run_date=reminder.remind_at),
            args=[reminder],
            id=f"reminder:{reminder.id}",
            replace_existing=True,
            misfire_grace_time=3600,
        )

    def remove(self, reminder_id: int) -> None:
        job_id = f"reminder:{reminder_id}"
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)

    async def _send_reminder(self, reminder: Reminder) -> None:
        await self.bot.send_message(reminder.chat_id, f"Напоминание: {reminder.text}")
        await self.repo.mark_sent(reminder.id)
