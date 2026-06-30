"""run_agent() — Phase 6 propose-then-commit агент. ReAct-цикл із tools, грунтований на памʼяті.

Tools:
  • search_memory(query) — семантичний пошук по памʼяті проєкту (reuse ask.retrieve).
  • list_entities()      — записані action_items + рішення проєкту (Postgres, Text-to-SQL-lite).
Агент НІЧОГО не виконує — лише ПРОПОНУЄ дії (ProposedAction, status=proposed) на людський апрув (HITL).

JSON-протокол на кожному кроці (Ollama format=json / OpenAI json_object). Tool-calling надійніший на
cloud (gpt-4o-mini); local (neural-chat) — best-effort. Цитати агрегуються глобально по run -> proposals
посилаються на РЕАЛЬНІ джерела з search_memory (анти-галюцинація). TORCH-FREE (embed/rerank — ззовні).
"""
from __future__ import annotations

import json
import urllib.request

from app.config import settings
from app.rag.ask import retrieve

MAX_STEPS = 5
ALLOWED_KINDS = {"jira", "slack", "email", "note"}


def _gen_json(prompt: str, engine: str, timeout: int = 300) -> str:
    """LLM-крок із форсованим JSON. cloud -> OpenAI json_object; local -> Ollama format=json."""
    kind, _, model = (engine or "").partition(":")
    if kind == "cloud":
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY не задано")
        body = json.dumps({
            "model": model or settings.summary_model_cloud,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {settings.openai_api_key}"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))["choices"][0]["message"]["content"]
    body = json.dumps({
        "model": model or settings.ask_model, "prompt": prompt, "stream": False,
        "format": "json", "options": {"temperature": 0.1, "num_ctx": 8192},
    }).encode("utf-8")
    req = urllib.request.Request(f"{settings.ollama_host}/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8")).get("response", "")


def _parse_json(raw: str) -> dict:
    try:
        return json.loads(raw)
    except Exception:
        try:
            return json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
        except Exception:
            return {}


_SYSTEM = """Ти — асистент проєкту з принципом propose-then-commit: ти ЛИШЕ пропонуєш дії, рішення
ухвалює людина. Мета: {goal}

Доступні інструменти:
- search_memory: семантичний пошук по памʼяті проєкту (репліки зустрічей). args: {{"query":"..."}}
- list_entities: показати записані action_items та рішення проєкту. args: {{}}

На КОЖНОМУ кроці поверни ТІЛЬКИ валідний JSON:
{{"thought":"...", "action":{{"tool":"search_memory|list_entities|finish", "query":"...(лише для search_memory)"}}, "proposals":[...](лише коли tool=finish)}}

Коли зібрав достатньо інформації — action.tool="finish" і заповни proposals (1–5):
[{{"kind":"jira|slack|email|note","title":"...","payload":{{...}},"rationale":"чому ця дія","citations":[N,...]}}]
citations = номери [#N] із результатів search_memory, що підтверджують дію (НЕ вигадуй джерел).
Поля — українською. Поверни ВАЛІДНИЙ JSON без markdown."""


def run_agent(project_id: str, goal: str, *, embedder, store, reranker, db,
              engine: str | None = None, meeting_id: str | None = None) -> dict:
    """Мета -> ReAct із памʼяттю -> ProposedAction(proposed). Повертає {n_proposed, trace}."""
    from app.models import ActionItem, Decision, ProposedAction

    engine = engine or f"local:{settings.ask_model}"
    sources: dict[int, dict] = {}    # глобальний реєстр цитат по run (n -> джерело)
    counter = {"n": 1}

    def tool_search_memory(query: str) -> str:
        cites = retrieve(project_id, query, embedder=embedder, store=store, reranker=reranker)
        lines = []
        for c in cites:
            n = counter["n"]; counter["n"] += 1
            sources[n] = c
            lines.append(f"[#{n}] ({c.get('title')} · {c.get('speaker')}): {(c.get('text') or '')[:300]}")
        return "\n".join(lines) or "(нічого не знайдено у памʼяті)"

    def tool_list_entities() -> str:
        ais = db.query(ActionItem).filter(ActionItem.project_id == project_id).all()
        decs = db.query(Decision).filter(Decision.project_id == project_id).all()
        lines = ["ACTION ITEMS:"]
        lines += [f"- owner={a.owner} · task={a.task} · deadline={a.deadline}" for a in ais] or ["(немає)"]
        lines.append("DECISIONS:")
        lines += [f"- {d.decision}" for d in decs] or ["(немає)"]
        return "\n".join(lines)

    trace: dict = {"goal": goal, "engine": engine, "steps": []}
    scratch = ""
    proposals_raw: list = []

    for _ in range(MAX_STEPS):
        prompt = (_SYSTEM.format(goal=goal)
                  + "\n\nСПОСТЕРЕЖЕННЯ ДОСІ:\n" + (scratch or "(порожньо)")
                  + "\n\nТвій наступний JSON-крок:")
        obj = _parse_json(_gen_json(prompt, engine))
        action = obj.get("action") or {}
        tool = action.get("tool")
        trace["steps"].append({"thought": obj.get("thought"), "tool": tool, "query": action.get("query")})

        if tool == "search_memory":
            obs = tool_search_memory(action.get("query") or goal)
            scratch += f"\n[search_memory({action.get('query')})] ->\n{obs}\n"
        elif tool == "list_entities":
            scratch += f"\n[list_entities] ->\n{tool_list_entities()}\n"
        elif tool == "finish" or obj.get("proposals"):
            proposals_raw = obj.get("proposals") or []
            break
        else:
            scratch += "\n[система] невідомий інструмент — заверши через finish з proposals.\n"

    created = 0
    for p in (proposals_raw or [])[:8]:
        if not isinstance(p, dict):
            continue
        kind = str(p.get("kind") or "note").lower()
        if kind not in ALLOWED_KINDS:
            kind = "note"
        cnums = [n for n in (p.get("citations") or []) if isinstance(n, int)]
        cites = [sources[n] for n in cnums if n in sources]
        db.add(ProposedAction(
            project_id=project_id, meeting_id=meeting_id, kind=kind,
            title=str(p.get("title") or "дія")[:500],
            payload=p.get("payload") if isinstance(p.get("payload"), dict) else {},
            rationale=str(p.get("rationale") or ""), citations=cites, status="proposed",
        ))
        created += 1
    db.commit()

    trace["raw_proposals"] = proposals_raw
    return {"n_proposed": created, "trace": trace}
