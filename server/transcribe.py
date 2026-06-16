"""Groq Whisper transcription for voice commands."""

from __future__ import annotations

import os

import httpx

import server.env  # noqa: F401

GROQ_TRANSCRIBE_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
WHISPER_MODEL = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3")

# Bias recognition toward TV remote phrases and streaming apps.
WHISPER_PROMPT = (
    "TV remote voice commands. Play, watch, open, search, launch, go home, press down, "
    "press up, click ok, go back, type, volume up, volume down, mute, pause, channel up, "
    "Netflix, Prime Video, Amazon Prime, YouTube, Disney Plus, Hulu, Paramount Plus."
)


def transcribe_available() -> bool:
    return bool(os.getenv("GROQ_API_KEY"))


async def transcribe_audio(
    audio_bytes: bytes,
    *,
    filename: str = "voice.webm",
    content_type: str = "audio/webm",
) -> str:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not configured")

    files = {"file": (filename, audio_bytes, content_type)}
    data = {
        "model": WHISPER_MODEL,
        "language": "en",
        "response_format": "json",
        "temperature": "0",
        "prompt": WHISPER_PROMPT,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            GROQ_TRANSCRIBE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            files=files,
            data=data,
        )
        if resp.status_code >= 400:
            detail = resp.text[:200]
            raise RuntimeError(f"Transcription failed ({resp.status_code}): {detail}")
        payload = resp.json()

    text = str(payload.get("text", "")).strip()
    if not text:
        raise RuntimeError("No speech detected")
    return text