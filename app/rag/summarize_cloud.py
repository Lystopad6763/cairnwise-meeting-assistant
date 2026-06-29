"""Хмарне резюме (OpenAI) — опційний рушій Агента-2 для «непублічних» зустрічей. TORCH-FREE.

Дзеркало app.rag.entities.extract_entities, але виклик іде в OpenAI Chat Completions замість
Ollama. ТОЙ САМИЙ промпт (build_prompt) і ТА САМА форма результату -> summary-воркер обирає
рушій лише за рядком engine, решта пайплайна (relabel -> numbered -> JSON -> Summary) спільна.

Лише stdlib (urllib) — без залежності openai-SDK. Приватність: у хмару йде ЛИШЕ текст транскрипту
(аудіо ніколи не покидає машину), і тільки коли користувач свідомо обрав cloud-режим.
"""
from __future__ import annotations

import json
import urllib.request

from app.config import settings
from app.rag.entities import build_prompt, number_transcript, parse_json

OPENAI_URL = "https://api.openai.com/v1/chat/completions"


def call_openai(prompt: str, model: str, timeout: int = 120) -> str:
    """POST /v1/chat/completions з response_format=json_object. Повертає content (рядок JSON)."""
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY не задано — хмарний режим недоступний")
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},   # форсить валідний JSON (як format=json в Ollama)
    }).encode("utf-8")
    req = urllib.request.Request(
        OPENAI_URL, data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.openai_api_key}",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def extract_entities_cloud(segments: list[dict], date: str, model: str | None = None) -> dict:
    """Транскрипт -> {summary, decisions[], action_items[], risks_blockers[], confidence} через OpenAI.

    Та сама сигнатура й форма, що й entities.extract_entities (local), тож взаємозамінні."""
    mdl = model or settings.summary_model_cloud
    numbered = number_transcript(segments)
    speakers = sorted({s.get("speaker", "Speaker ?") for s in segments})
    content = call_openai(build_prompt(numbered, date, speakers), mdl)
    result = parse_json(content) or {}
    return {
        "summary": result.get("summary", ""),
        "decisions": result.get("decisions", []) or [],
        "action_items": result.get("action_items", []) or [],
        "risks_blockers": result.get("risks_blockers", []) or [],
        "confidence": result.get("confidence", 0.0),
    }
