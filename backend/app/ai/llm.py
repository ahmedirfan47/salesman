"""Provider-agnostic LLM client.

Talks to any OpenAI-compatible /v1/chat/completions endpoint. Defaults to a
local Ollama server, but the same code works with OpenAI, Together, etc.
by changing LLM_BASE_URL / LLM_MODEL / LLM_API_KEY.
"""
from openai import AsyncOpenAI

from app.config import settings

client = AsyncOpenAI(base_url=settings.LLM_BASE_URL, api_key=settings.LLM_API_KEY)


async def chat(messages: list[dict], tools: list[dict] | None = None):
    """Single completion turn. Returns the raw assistant message object
    (which may contain .content and/or .tool_calls)."""
    kwargs: dict = {"model": settings.LLM_MODEL, "messages": messages}
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    resp = await client.chat.completions.create(**kwargs)
    return resp.choices[0].message