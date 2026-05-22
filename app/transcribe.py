from pathlib import Path
from tempfile import NamedTemporaryFile

from aiogram import Bot
from aiogram.types import Voice
from openai import APIConnectionError, APIStatusError, AuthenticationError, AsyncOpenAI


class TranscriptionError(Exception):
    """Raised when a voice message cannot be transcribed."""


class VoiceTranscriber:
    def __init__(self, api_key: str | None, model: str) -> None:
        self.model = model
        normalized_key = (api_key or "").strip()
        self.client = (
            AsyncOpenAI(api_key=normalized_key)
            if normalized_key and normalized_key != "sk-replace_me"
            else None
        )

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
                try:
                    result = await self.client.audio.transcriptions.create(
                        model=self.model,
                        file=audio_file,
                    )
                except AuthenticationError as exc:
                    raise TranscriptionError("OpenAI отклонил API-ключ. Проверь OPENAI_API_KEY в .env.") from exc
                except APIConnectionError as exc:
                    raise TranscriptionError("VPS не смог подключиться к OpenAI. Проверь сеть сервера.") from exc
                except APIStatusError as exc:
                    raise TranscriptionError(f"OpenAI вернул ошибку {exc.status_code}.") from exc
            return result.text.strip()
        finally:
            tmp_path.unlink(missing_ok=True)
