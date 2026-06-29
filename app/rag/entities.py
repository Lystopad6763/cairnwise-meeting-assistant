"""Грунтоване витягання сутностей (Агент-2 core). TORCH-FREE.

Рефакторено з scripts/summarize.py — ОДНЕ джерело правди для extraction-промпта. summarize.py
тепер тонкий CLI, що імпортує ці хелпери; ingest (app.rag.service) кличе extract_entities().

Ядро довіри (з ДЗ-6): кожен рядок транскрипту пронумеровано [#N]; модель мусить цитувати [#N] для
кожного рішення/завдання -> перевірка, що це НЕ галюцинація. ABSTENTION (нема в тексті — не вигадуй).
Інжект ДАТИ зустрічі. CONFIDENCE -> HITL-гейт. Output українською; локальна LLM через Ollama.
"""
from __future__ import annotations

import json
import urllib.request

from app.config import settings

# Хост Ollama: settings.ollama_host (env OLLAMA_HOST підхоплює pydantic-settings, як і раніше).
OLLAMA_HOST = settings.ollama_host

# Поріг HITL (з findings ДЗ-6: confidence -> гейт апруву; нічого не виконується автоматично)
AUTO_OK = 0.85       # >= -> можна авто-апрувити (усе ґрунтовно підтверджено)
NEEDS_HUMAN = 0.60   # [0.60, 0.85) -> на ревʼю людині; < -> відхилити/перегенерувати

# ВАЖЛИВО: опис полів і приклад РОЗДІЛЕНІ. Інакше локальна модель «відлунює» текст-опис у самі
# значення (баг: summary вертався як «2-4 речення...», confidence=0.0 — скопійовані з шаблону).
FIELD_SPEC = (
    "ФОРМАТ — поверни JSON-обʼєкт РІВНО з цими полями (опис нижче = ІНСТРУКЦІЯ, НЕ копіюй його у відповідь):\n"
    "- summary: рядок, 2-4 речення українською — стисло головне зі зустрічі;\n"
    "- decisions: масив {\"decision\": текст, \"citations\": [N,...]} — ухвалені рішення;\n"
    "- action_items: масив {\"owner\": хто, \"task\": що зробити, \"deadline\": \"YYYY-MM-DD\" або null, \"citations\": [N,...]};\n"
    "- risks_blockers: масив {\"item\": текст, \"citations\": [N,...]} — названі ризики/блокери;\n"
    "- confidence: число 0..1 — ТВОЯ оцінка впевненості (НЕ став 0, якщо все підтверджено транскриптом).\n"
    "citations = номери рядків [#N], з яких факт випливає; чого нема в тексті -> порожній масив / null."
)
EXAMPLE = (
    "Приклад ФОРМАТУ (вигадана ІНША зустріч — бери лише СТРУКТУРУ, не зміст):\n"
    '{"summary":"Команда узгодила перенос релізу й розподілила інтеграційні задачі.",'
    '"decisions":[{"decision":"Перенести реліз на тиждень","citations":[12]}],'
    '"action_items":[{"owner":"Speaker 2","task":"Підготувати міграцію БД","deadline":"2026-07-03","citations":[18,21]}],'
    '"risks_blockers":[{"item":"Нестабільний вебхук платіжки","citations":[30]}],'
    '"confidence":0.82}'
)


def speaker_display(label: dict | None, fallback: str) -> str:
    """{"name","role"} -> «Іван (PM)» / «Іван» / fallback (якщо не підписано)."""
    if not label:
        return fallback
    name = str(label.get("name") or "").strip()
    role = str(label.get("role") or "").strip()
    if not name:
        return fallback
    return f"{name} ({role})" if role else name


def relabel_segments(segments: list[dict], labels: dict | None) -> list[dict]:
    """Застосувати підписи спікерів поверх сегментів (недеструктивно -> НОВИЙ список).

    labels: {"Speaker 1": {"name": "Іван", "role": "PM"}}. Сегменти без підпису лишаються як є.
    Використовується summary-воркером, щоб резюме говорило іменами, а не «Speaker N»."""
    if not labels:
        return segments
    out = []
    for s in segments:
        spk = s.get("speaker", "Speaker ?")
        disp = speaker_display(labels.get(spk), spk)
        out.append({**s, "speaker": disp} if disp != spk else s)
    return out


def number_transcript(segments: list[dict]) -> str:
    """Кожна репліка -> '[#N] Speaker X (12.3s): текст'. Номер N = якір для цитат."""
    lines = []
    for i, s in enumerate(segments, 1):
        spk = s.get("speaker", "Speaker ?")
        ts = float(s.get("start", 0.0))
        lines.append(f"[#{i}] {spk} ({ts:.1f}s): {str(s.get('text', '')).strip()}")
    return "\n".join(lines)


def build_prompt(numbered: str, date: str, speakers: list[str]) -> str:
    return f"""Ти — асистент-протоколіст ділових зустрічей. Твоє завдання: на основі ВИКЛЮЧНО
наведеного транскрипту скласти структуроване резюме зустрічі.

Дата зустрічі: {date}
Учасники: {', '.join(speakers)}

Транскрипт (кожен рядок: [#N] хто (час): репліка):
{numbered}

ПРАВИЛА (суворо):
1. Спирайся ЛИШЕ на транскрипт. НЕ вигадуй фактів, імен, чисел, дат, домовленостей.
2. Для КОЖНОГО рішення / завдання / ризику вкажи "citations" — номери рядків [#N], з яких це випливає.
3. ABSTENTION: якщо чогось немає в транскрипті — лиши масив порожнім, deadline = null. Не додумуй.
4. Дедлайни — відносно дати зустрічі ({date}), формат YYYY-MM-DD; якщо не названо — null.
5. summary і confidence ЗАПОВНИ РЕАЛЬНО (своїм текстом / числом) — НЕ копіюй опис полів.
6. Відповідай УКРАЇНСЬКОЮ. Поверни ТІЛЬКИ валідний JSON (без markdown, без пояснень).

{FIELD_SPEC}

{EXAMPLE}

Тепер проаналізуй транскрипт ВИЩЕ і поверни ТІЛЬКИ JSON для НЬОГО:"""


def call_ollama(prompt: str, model: str, num_ctx: int = 8192, timeout: int = 900) -> dict:
    """POST /api/generate з format=json (Ollama форсить валідний JSON). stdlib, без залежностей.
    Повертає ПОВНУ відповідь Ollama (з полем 'response' + таймінгами load/prompt_eval/eval — їх
    показуємо як швидкість у токенах/с). num_ctx — вікно контексту: ДЕФОЛТ Ollama лише 4096, що
    ОБРІЗАЛО б довгу зустріч (m05 ~10-12k токенів) -> підіймаємо, інакше модель «не побачить» хвіст."""
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",                 # структурований вивід
        "options": {"temperature": 0.2, "num_ctx": num_ctx},  # детермінованіше + ширший контекст
    }).encode("utf-8")
    req = urllib.request.Request(f"{OLLAMA_HOST}/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def speed_report(resp: dict) -> str:
    """Таймінги Ollama (наносекунди) -> людський звіт зі швидкістю токен/с."""
    def s(ns): return (ns or 0) / 1e9
    load, pe_n, pe_s = s(resp.get("load_duration")), resp.get("prompt_eval_count") or 0, s(resp.get("prompt_eval_duration"))
    ev_n, ev_s, tot = resp.get("eval_count") or 0, s(resp.get("eval_duration")), s(resp.get("total_duration"))
    pe_rate = f"{pe_n / pe_s:.1f} ток/с" if pe_s else "—"
    ev_rate = f"{ev_n / ev_s:.1f} ток/с" if ev_s else "—"
    return (f"швидкість: завантаження моделі {load:.1f}s · промпт {pe_n} ток за {pe_s:.1f}s ({pe_rate}) · "
            f"генерація {ev_n} ток за {ev_s:.1f}s ({ev_rate}) · разом {tot:.1f}s")


def parse_json(raw: str) -> dict | None:
    """Ollama з format=json зазвичай дає чистий JSON; на всяк — вирізаємо { .. }."""
    try:
        return json.loads(raw)
    except Exception:
        try:
            return json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
        except Exception:
            return None


def citation_audit(result: dict, n_segments: int) -> tuple[int, list]:
    """Зібрати всі [#N] з виводу й знайти ті, що поза діапазоном [1..n] -> галюциновані посилання
    (модель послалась на рядок, якого нема). Дешева автоперевірка grounding."""
    cited: list = []
    for key in ("decisions", "action_items", "risks_blockers"):
        for item in (result.get(key) or []):
            cited.extend(item.get("citations") or [])
    invalid = sorted({c for c in cited if not isinstance(c, int) or c < 1 or c > n_segments})
    return len(cited), invalid


def verdict(conf: float) -> str:
    if conf >= AUTO_OK:
        return f"AUTO-APPROVABLE (confidence {conf:.2f} ≥ {AUTO_OK}) — можна показати на апрув"
    if conf >= NEEDS_HUMAN:
        return f"HUMAN REVIEW (confidence {conf:.2f} у [{NEEDS_HUMAN}, {AUTO_OK})) — на ревʼю людині"
    return f"REJECT/REGEN (confidence {conf:.2f} < {NEEDS_HUMAN}) — відхилити або перегенерувати"


def extract_entities(segments: list[dict], date: str, model: str | None = None,
                     num_ctx: int = 8192) -> dict:
    """Транскрипт -> {summary, decisions[], action_items[], risks_blockers[], confidence}.

    Один виклик локальної LLM (Ollama, дефолт settings.entity_model = "neural-chat"). ТА САМА
    логіка, що й summarize.py CLI — Phase 7 переюзає цей самий виклик.
    """
    mdl = model or settings.entity_model
    numbered = number_transcript(segments)
    speakers = sorted({s.get("speaker", "Speaker ?") for s in segments})
    resp = call_ollama(build_prompt(numbered, date, speakers), mdl, num_ctx)
    result = parse_json(resp.get("response", "")) or {}
    return {
        "summary": result.get("summary", ""),
        "decisions": result.get("decisions", []) or [],
        "action_items": result.get("action_items", []) or [],
        "risks_blockers": result.get("risks_blockers", []) or [],
        "confidence": result.get("confidence", 0.0),
    }
