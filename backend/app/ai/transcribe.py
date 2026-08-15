"""Speech-to-text via an OpenAI-compatible Whisper endpoint (e.g. Groq).

Uses the same API key as the LLM. Groq's free tier covers Whisper and it
supports Arabic + English, which is exactly what we need for voice notes.
"""
import io

from openai import AsyncOpenAI

from app.config import settings


def _client() -> AsyncOpenAI:
    base_url = settings.STT_BASE_URL or settings.LLM_BASE_URL
    return AsyncOpenAI(api_key=settings.LLM_API_KEY, base_url=base_url)


async def transcribe(audio_bytes: bytes, filename: str = "audio.ogg") -> str:
    """Transcribe audio to text in its original language (Whisper auto-detects)."""
    client = _client()
    file_obj = io.BytesIO(audio_bytes)
    file_obj.name = filename  # the SDK needs a name to infer the format
    result = await client.audio.transcriptions.create(
        model=settings.STT_MODEL,
        file=file_obj,
    )
    return (result.text or "").strip()