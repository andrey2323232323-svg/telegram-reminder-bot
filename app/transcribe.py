from pathlib import Path
from tempfile import NamedTemporaryFile

from aiogram import Bot
from aiogram.types import Voice
from openai import AsyncOpenAI


class VoiceTranscriber:
    def __init__(self, api_key: str | None, model: str) -> None:
        self.model = model
        self.client = AsyncOpenAI(api_key=api_key) if api_key else None

    @property
    def enabled(self) -> bool:
        return self.client is not None

    async def transcribe_telegram_voice(self, bot: Bot, voice: Voice) -> str:
        if self.client is None:
            raise RuntimeError("OPENAI_API_KEY is required for voice transcription")

        file = await bot.get_file(voice.file_id)
        with NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            await bot.download_file(file.file_path, destination=tmp)

        try:
            with tmp_path.open("rb") as audio_file:
                result = await self.client.audio.transcriptions.create(
                    model=self.model,
                    file=audio_file,
                )
            return result.text.strip()
        finally:
            tmp_path.unlink(missing_ok=True)
