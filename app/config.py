from dataclasses import dataclass
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    openai_api_key: str | None
    openai_transcribe_model: str
    timezone: str
    database_path: str


def load_settings() -> Settings:
    load_dotenv()

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

    return Settings(
        telegram_bot_token=token,
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_transcribe_model=os.getenv("OPENAI_TRANSCRIBE_MODEL", "whisper-1"),
        timezone=os.getenv("TIMEZONE", "Europe/Moscow"),
        database_path=os.getenv("DATABASE_PATH", "data/reminders.sqlite3"),
    )
