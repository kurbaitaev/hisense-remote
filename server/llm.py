"""LLM helpers for voice command parsing (Groq preferred, Gemini fallback)."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Literal

import httpx

import server.env  # noqa: F401 — load .env before reading keys

Provider = Literal["groq", "gemini"]

GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)


def groq_available() -> bool:
    return bool(os.getenv("GROQ_API_KEY"))


def gemini_available() -> bool:
    return bool(os.getenv("GEMINI_API_KEY"))


def llm_available() -> bool:
    return groq_available() or gemini_available()


def llm_provider() -> Provider | None:
    if groq_available():
        return "groq"
    if gemini_available():
        return "gemini"
    return None


async def ask_groq(prompt: str, *, timeout: float = 20.0) -> str | None:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return None

    payload = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    choices = data.get("choices") or []
    if not choices:
        return None
    content = choices[0].get("message", {}).get("content")
    return str(content).strip() if content else None


async def ask_gemini(prompt: str, *, timeout: float = 20.0) -> str | None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2},
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            GEMINI_URL,
            params={"key": api_key},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    candidates = data.get("candidates") or []
    if not candidates:
        return None
    parts = candidates[0].get("content", {}).get("parts") or []
    if not parts:
        return None
    return str(parts[0].get("text", "")).strip()


async def ask_llm(prompt: str, *, timeout: float = 20.0) -> str | None:
    if groq_available():
        try:
            result = await ask_groq(prompt, timeout=timeout)
            if result:
                return result
        except httpx.HTTPError:
            pass
    if gemini_available():
        try:
            return await ask_gemini(prompt, timeout=timeout)
        except httpx.HTTPError:
            return None
    return None


def _extract_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


async def parse_voice_json(prompt: str) -> dict[str, Any] | None:
    raw = await ask_llm(prompt)
    if not raw:
        return None
    return _extract_json(raw)