"""Прототип Агента-2 (summary) — діаризований транскрипт -> структуроване резюме (локально).

Адаптація ДЗ-6 (extraction-eval) під Cairnwise, з ядром довіри:
  • вхід = ДІАРИЗОВАНИЙ транскрипт (з Postgres за --meeting, або JSON-файл за --file);
  • GROUNDING+CITATIONS: кожен рядок транскрипту пронумеровано [#N]; модель мусить цитувати [#N]
    для кожного рішення/завдання -> можна перевірити, що це НЕ галюцинація;
  • ABSTENTION: чого немає в транскрипті — НЕ вигадуй (порожні масиви / deadline=null);
  • ІНЖЕКТ ДАТИ зустрічі (моделі вигадують роки) -> дедлайни рахуються відносно неї;
  • CONFIDENCE (0..1) -> HITL-гейт (≥0.85 авто-апрув / 0.6-0.85 ревʼю людиною / <0.6 відхилити);
  • output УКРАЇНСЬКОЮ; локальна LLM через Ollama (ключ не потрібен).

Це ПРОТОТИП (доказ, що Агент-2 працює на реальному транскрипті). Формалізація (підписка summary,
черга approvals, regression-eval) — Фази 7-8.

  python scripts/summarize.py --meeting <id>                  # транскрипт із БД
  python scripts/summarize.py --file eval/dumps/m05_daily_standup.small.pa-3.1.json
  python scripts/summarize.py --file ... --dry-run            # лише показати промпт (без Ollama)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, ROOT)

from _env import load_env  # noqa: E402
load_env()

DEFAULT_MODEL = os.environ.get("SUMMARY_MODEL", "neural-chat")  # №1 локальна за ДЗ-6 (12/12, 0 галюц.)
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

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


def load_segments_from_file(path: str) -> tuple[list[dict], str | None]:
    """JSON-масив [{speaker,start,end,text}] (eval/dumps або *.ref.json)."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    segs = data["segments"] if isinstance(data, dict) and "segments" in data else data
    return segs, None


def load_segments_from_db(meeting_id: str) -> tuple[list[dict], str | None]:
    """Transcript.segments із Postgres + дата зустрічі (для інжекту)."""
    from app.db import SessionLocal
    from app.models import Meeting, Transcript
    db = SessionLocal()
    try:
        tr = db.query(Transcript).filter(Transcript.meeting_id == meeting_id).one_or_none()
        if tr is None:
            raise SystemExit(f"транскрипту для meeting={meeting_id} нема (status transcribed?)")
        m = db.get(Meeting, meeting_id)
        date = m.created_at.date().isoformat() if m and m.created_at else None
        return list(tr.segments), date
    finally:
        db.close()


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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--meeting", help="meeting_id — взяти транскрипт із Postgres")
    src.add_argument("--file", help="JSON-файл сегментів [{speaker,start,end,text}]")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--date", default=None, help="дата зустрічі YYYY-MM-DD (інакше з БД / сьогодні)")
    ap.add_argument("--max-chars", type=int, default=0,
                    help="обрізати транскрипт до N символів (0=без обрізки; для швидкого тесту на 4GB)")
    ap.add_argument("--num-ctx", type=int, default=8192,
                    help="вікно контексту Ollama (дефолт самої Ollama лише 4096 -> обрізає довгу зустріч)")
    ap.add_argument("--out", default=None, help="зберегти результат JSON")
    ap.add_argument("--dry-run", action="store_true", help="лише показати промпт, без виклику Ollama")
    args = ap.parse_args()

    if args.meeting:
        segments, db_date = load_segments_from_db(args.meeting)
    else:
        segments, db_date = load_segments_from_file(args.file)
    if not segments:
        raise SystemExit("порожній транскрипт")

    date = args.date or db_date or time.strftime("%Y-%m-%d")
    speakers = sorted({s.get("speaker", "Speaker ?") for s in segments})
    numbered = number_transcript(segments)
    if args.max_chars and len(numbered) > args.max_chars:
        numbered = numbered[:args.max_chars] + "\n[...обрізано...]"
    prompt = build_prompt(numbered, date, speakers)

    print(f"транскрипт: {len(segments)} реплік · {len(speakers)} спікер(и) · дата={date} · "
          f"модель={args.model} · ~{len(prompt)} символів промпту")

    if args.dry_run:
        print("\n========== PROMPT (dry-run) ==========\n")
        print(prompt)
        return 0

    print(f"\nвиклик Ollama {args.model} (локально; на 4GB може бути повільно) ...")
    t0 = time.perf_counter()
    try:
        resp = call_ollama(prompt, args.model, num_ctx=args.num_ctx)
    except urllib.error.URLError as exc:
        raise SystemExit(f"Ollama недоступна на {OLLAMA_HOST}: {exc}. Запусти `ollama serve` "
                         f"і `ollama pull {args.model}`.")
    dt = time.perf_counter() - t0
    raw = resp.get("response", "")
    print(f"  {speed_report(resp)}")

    result = parse_json(raw)
    if result is None:
        print(f"[невалідний JSON за {dt:.1f}s] перші 400 символів:\n{raw[:400]}", file=sys.stderr)
        return 1

    conf = float(result.get("confidence", 0.0) or 0.0)
    print(f"\n=== РЕЗЮМЕ (за {dt:.1f}s) ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n=== HITL-ГЕЙТ ===\n  {verdict(conf)}")
    n_act = len(result.get("action_items", []))
    n_dec = len(result.get("decisions", []))
    uncited = [a for a in result.get("action_items", []) if not a.get("citations")]
    total_cites, bad_cites = citation_audit(result, len(segments))
    print(f"  рішень={n_dec} · action-items={n_act} · без цитат={len(uncited)} "
          f"(чим більше без цитат — тим підозріліше на галюцинацію)")
    print(f"  цитат усього={total_cites} · поза діапазоном [1..{len(segments)}]={bad_cites or '—'} "
          f"(будь-яка поза діапазоном = галюциноване посилання)")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"meeting": args.meeting, "file": args.file, "date": date,
                       "model": args.model, "latency_s": round(dt, 1), "result": result}, f,
                      ensure_ascii=False, indent=2)
        print(f"\n-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
