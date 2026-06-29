"""Чанкер діаризованого транскрипту -> список Chunk. TORCH-FREE, чистий Python, unit-testable.

Алгоритм (резолв із CONTRACT §3): speaker-turn-aware + gap-aware sliding window на CHAR-бюджеті.
CHAR-бюджет (а не token-бюджет) — НАВМИСНО: чанкер не імпортує жодного tokenizer/transformers,
тож CPU-only API-контейнер може його імпортувати (Phase 5/6). Ціль ~250-350 токенів/чанк.

Кроки:
  1. Злити підряд однакового-спікера сегменти в TURN (текст через " ", min start / max end,
     запамʼятати 1-based діапазон джерельних індексів сегментів).
  2. Жадібно пакувати turn-и у вікно, поки додавання наступного turn НЕ перевищить max_chars
     АБО пауза тиші до наступного turn (next.start - current.end) > max_gap_s (межа теми) -> flush.
  3. OVERLAP: кожне нове вікно стартує з повторного включення останніх overlap_turns turn-ів
     попереднього (факт на межі дістається з обох боків).
  4. LONG MONOLOGUE: один turn, чий текст > max_chars, мʼяко ріжеться по межах речень
     (regex на . ! ? … та новий рядок), кожен шматок — окремий Chunk з 1 реченням перекриття;
     seg_start/seg_end лишаються індексами джерельного turn-у.
  5. Chunk.text = speaker-prefixed рядки, по одному на джерельний сегмент у вікні.
"""
from __future__ import annotations

import re

from app.rag.schema import Chunk

# Межі речень: . ! ? … (можливо повторені) + закриваючі лапки/дужки, далі пробіл; АБО новий рядок.
_SENT_SPLIT = re.compile(r'(?<=[.!?…])["»”\')\]]*\s+|\n+')

_DOMINANT_RATIO = 0.60   # спікер «домінує», якщо тримає >= 60% символів вікна


def _merge_turns(segments: list[dict]) -> list[dict]:
    """Злити підряд однакового-спікера сегменти в turn-и.

    Кожен turn: {speaker, start, end, text, seg_start, seg_end, segs:[{speaker,text}...]}.
    seg_start/seg_end — 1-based індекси джерельних сегментів (включно). `segs` зберігає
    посегментні (speaker, text) пари для speaker-prefixed рендеру Chunk.text.
    """
    turns: list[dict] = []
    for idx, seg in enumerate(segments, 1):              # 1-based -> вирівняно з [#N]
        speaker = str(seg.get("speaker") or "Speaker ?")
        text = str(seg.get("text") or "").strip()
        start = float(seg.get("start") or 0.0)
        end = float(seg.get("end") or start)
        unit = {"speaker": speaker, "text": text}
        if turns and turns[-1]["speaker"] == speaker:
            t = turns[-1]
            t["text"] = (t["text"] + " " + text).strip() if text else t["text"]
            t["end"] = max(t["end"], end)
            t["seg_end"] = idx
            t["segs"].append(unit)
        else:
            turns.append({
                "speaker": speaker, "text": text, "start": start, "end": end,
                "seg_start": idx, "seg_end": idx, "segs": [unit],
            })
    return turns


def _split_long_text(text: str, max_chars: int) -> list[str]:
    """Мʼяко порізати задовгий монолог по межах речень, 1 речення перекриття між шматками."""
    sentences = [s for s in _SENT_SPLIT.split(text) if s and s.strip()]
    if not sentences:
        return [text]
    pieces: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for sent in sentences:
        add = len(sent) + (1 if cur else 0)
        if cur and cur_len + add > max_chars:
            pieces.append(" ".join(cur))
            cur = [cur[-1]] if cur else []          # 1 речення overlap у наступний шматок
            cur_len = len(cur[0]) if cur else 0
        cur.append(sent)
        cur_len += len(sent) + (1 if len(cur) > 1 else 0)
    if cur:
        pieces.append(" ".join(cur))
    return pieces or [text]


def _render(units: list[dict]) -> str:
    """Speaker-prefixed текст: по рядку на джерельний сегмент вікна."""
    return "\n".join(f'{u["speaker"]}: {u["text"]}'.rstrip() for u in units if u.get("text"))


def _dominant(units: list[dict]) -> tuple[str, list[str]]:
    """(домінантний спікер за к-стю символів | "multi"; відсортовані різні спікери)."""
    by_speaker: dict[str, int] = {}
    for u in units:
        by_speaker[u["speaker"]] = by_speaker.get(u["speaker"], 0) + len(u.get("text") or "")
    speakers = sorted(by_speaker)
    if not by_speaker:
        return "multi", speakers
    total = sum(by_speaker.values()) or 1
    top = max(by_speaker, key=lambda k: by_speaker[k])
    if len(by_speaker) == 1 or by_speaker[top] / total >= _DOMINANT_RATIO:
        return top, speakers
    return "multi", speakers


def _make_chunk(chunk_index: int, window_turns: list[dict]) -> Chunk:
    """Зібрати Chunk із набору turn-ів вікна (метадані агрегуються по сегментах)."""
    units: list[dict] = []
    for t in window_turns:
        units.extend(t["segs"])
    speaker, speakers = _dominant(units)
    return Chunk(
        chunk_index=chunk_index,
        text=_render(units),
        speaker=speaker,
        speakers=speakers,
        start=min(t["start"] for t in window_turns),
        end=max(t["end"] for t in window_turns),
        seg_start=min(t["seg_start"] for t in window_turns),
        seg_end=max(t["seg_end"] for t in window_turns),
    )


def chunk_segments(
    segments: list[dict],            # [{speaker,start,end,text}] із Transcript.segments
    *,
    max_chars: int = 1100,           # <- settings.chunk_max_chars
    overlap_turns: int = 1,          # <- settings.chunk_overlap_turns
    max_gap_s: float = 45.0,         # <- settings.chunk_max_gap_s
) -> list[Chunk]:
    """Діаризовані сегменти -> список Chunk (стабільний 0-based chunk_index)."""
    turns = _merge_turns(segments)
    if not turns:
        return []

    chunks: list[Chunk] = []
    window: list[dict] = []
    window_chars = 0
    emitted_seg_end = 0          # найбільший джерельний seg_end, що вже потрапив у якийсь чанк

    def flush() -> None:
        """Зафіксувати поточне вікно як Chunk; новий старт = overlap-перенесення turn-ів.

        Пропускаємо вікно, що НЕ додає жодного НОВОГО сегмента (чистий overlap-хвіст наприкінці) —
        інакше після останнього flush() лишався б дубль уже покритих реплік.
        """
        nonlocal window, window_chars, emitted_seg_end
        if not window:
            return
        win_seg_end = max(t["seg_end"] for t in window)
        if win_seg_end > emitted_seg_end:                     # вікно несе щось нове
            chunks.append(_make_chunk(len(chunks), window))
            emitted_seg_end = win_seg_end
        # OVERLAP: новий старт = останні overlap_turns turn-и попереднього вікна
        carry = window[-overlap_turns:] if overlap_turns > 0 else []
        window = list(carry)
        window_chars = sum(len(t["text"]) for t in window)

    i = 0
    while i < len(turns):
        turn = turns[i]
        tlen = len(turn["text"])

        # (4) Довгий монолог: turn сам по собі більший за бюджет -> мʼякий спліт по реченнях.
        # Спершу зливаємо поточне вікно (щоб монолог не «розмазав» його за межу бюджету), потім
        # ріжемо turn на під-чанки. Скидаємо overlap-перенесення: монолог стартує чисте вікно.
        if tlen > max_chars:
            flush()
            window, window_chars = [], 0          # монолог не несе overlap у/з сусідів
            for piece in _split_long_text(turn["text"], max_chars):
                sub = dict(turn)
                sub["text"] = piece
                sub["segs"] = [{"speaker": turn["speaker"], "text": piece}]
                chunks.append(_make_chunk(len(chunks), [sub]))
            emitted_seg_end = max(emitted_seg_end, turn["seg_end"])
            i += 1
            continue

        # (2) Перевищення CHAR-бюджету -> flush ПЕРЕД додаванням цього turn-а.
        if window and window_chars + tlen > max_chars:
            flush()

        window.append(turn)
        window_chars += tlen

        # (2) Часова пауза до наступного turn-а > max_gap_s -> межа теми -> flush ПІСЛЯ цього turn-а.
        if i + 1 < len(turns):
            gap = turns[i + 1]["start"] - turn["end"]
            if gap > max_gap_s:
                flush()
        i += 1

    flush()
    return chunks
