from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import aiosqlite


@dataclass(frozen=True)
class Reminder:
    id: int
    chat_id: int
    text: str
    remind_at: datetime
    status: str
    source_text: str


class ReminderRepository:
    def __init__(self, database_path: str) -> None:
        self.database_path = database_path

    async def init(self) -> None:
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    remind_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    source_text TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            await db.commit()

    async def add(self, chat_id: int, text: str, remind_at: datetime, source_text: str) -> Reminder:
        now = datetime.now(remind_at.tzinfo).isoformat()
        async with aiosqlite.connect(self.database_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO reminders (chat_id, text, remind_at, status, source_text, created_at)
                VALUES (?, ?, ?, 'pending', ?, ?)
                """,
                (chat_id, text, remind_at.isoformat(), source_text, now),
            )
            await db.commit()
            reminder_id = cursor.lastrowid

        return Reminder(
            id=int(reminder_id),
            chat_id=chat_id,
            text=text,
            remind_at=remind_at,
            status="pending",
            source_text=source_text,
        )

    async def list_pending(self, chat_id: int | None = None) -> list[Reminder]:
        query = """
            SELECT id, chat_id, text, remind_at, status, source_text
            FROM reminders
            WHERE status = 'pending'
        """
        params: tuple[int, ...] = ()
        if chat_id is not None:
            query += " AND chat_id = ?"
            params = (chat_id,)
        query += " ORDER BY remind_at ASC"

        async with aiosqlite.connect(self.database_path) as db:
            rows = await db.execute_fetchall(query, params)

        return [
            Reminder(
                id=row[0],
                chat_id=row[1],
                text=row[2],
                remind_at=datetime.fromisoformat(row[3]),
                status=row[4],
                source_text=row[5],
            )
            for row in rows
        ]

    async def mark_sent(self, reminder_id: int) -> None:
        await self._set_status(reminder_id, "sent")

    async def cancel(self, reminder_id: int, chat_id: int) -> bool:
        async with aiosqlite.connect(self.database_path) as db:
            cursor = await db.execute(
                """
                UPDATE reminders
                SET status = 'cancelled'
                WHERE id = ? AND chat_id = ? AND status = 'pending'
                """,
                (reminder_id, chat_id),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def cancel_all(self, chat_id: int) -> list[int]:
        reminders = await self.list_pending(chat_id)
        if not reminders:
            return []

        reminder_ids = [item.id for item in reminders]
        placeholders = ",".join("?" for _ in reminder_ids)
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                f"""
                UPDATE reminders
                SET status = 'cancelled'
                WHERE chat_id = ? AND status = 'pending' AND id IN ({placeholders})
                """,
                (chat_id, *reminder_ids),
            )
            await db.commit()
        return reminder_ids

    async def cancel_last(self, chat_id: int) -> Reminder | None:
        async with aiosqlite.connect(self.database_path) as db:
            row = await db.execute_fetchone(
                """
                SELECT id, chat_id, text, remind_at, status, source_text
                FROM reminders
                WHERE chat_id = ? AND status = 'pending'
                ORDER BY id DESC
                LIMIT 1
                """,
                (chat_id,),
            )
            if row is None:
                return None

            await db.execute(
                "UPDATE reminders SET status = 'cancelled' WHERE id = ?",
                (row[0],),
            )
            await db.commit()

        return Reminder(
            id=row[0],
            chat_id=row[1],
            text=row[2],
            remind_at=datetime.fromisoformat(row[3]),
            status="cancelled",
            source_text=row[5],
        )

    async def _set_status(self, reminder_id: int, status: str) -> None:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                "UPDATE reminders SET status = ? WHERE id = ?",
                (status, reminder_id),
            )
            await db.commit()
