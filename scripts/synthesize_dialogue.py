"""Скриптований діалог -> багатоголосе аудіо зустрічі + GROUND-TRUTH лейбли.

Бере скрипт `{engine, turns:[{speaker, voice, text}]}` і озвучує кожну репліку окремим
голосом. Склеює в один wav із паузами. Оскільки ми знаємо точну тривалість кожної репліки —
отримуємо БЕЗКОШТОВНУ ground-truth діаризацію (RTTM) + еталонний транскрипт. Це еталон для
бенчмарку ASR+diarization (WER / DER / cpWER).

Двигуни (`engine` у скрипті або --engine):
  edge    — edge-tts (cloud, безкоштовно, 2 укр. голоси uk-UA-Ostap/Polina); потребує ffmpeg.
  uk-tts  — robinhad/ukrainian-tts (ЛОКАЛЬНО, 5 укр. голосів: Tetiana/Mykyta/Lada/Dmytro/Oleksa).
            XTTS-v2 НЕ вміє українську — для UA багатоспікерності беремо саме ukrainian-tts.

  pip install -r requirements-ingest.txt        # edge-tts, pydub, ukrainian-tts
  python scripts/synthesize_dialogue.py data/projects/nimbus/meetings/sprint_planning01.json

Видає поряд зі скриптом:  <id>.wav,  <id>.rttm,  <id>.ref.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _env import load_env  # noqa: E402 — додає .venv\Scripts (ffmpeg) у PATH для pydub

SR = 16000
GAP_MS = 350  # пауза між репліками


def _cuda() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


def _edge_engine():
    """(synth_fn, tmp_ext) для edge-tts. synth_fn(text, voice, out_path)."""
    import asyncio

    import edge_tts

    def synth(text: str, voice: str, out_path: str) -> None:
        asyncio.run(edge_tts.Communicate(text, voice).save(out_path))

    return synth, ".mp3"


def _uktts_engine():
    """(synth_fn, tmp_ext) для robinhad/ukrainian-tts (локально). NB: сигнатура tts.tts()
    може дрібно різнитись між версіями пакета — підправ за потреби (edge — перевірений fallback)."""
    from ukrainian_tts.tts import TTS, Stress, Voices

    tts = TTS(device="cuda" if _cuda() else "cpu")
    stress = Stress.Dictionary.value

    def synth(text: str, voice: str, out_path: str) -> None:
        v = getattr(Voices, voice.capitalize()).value   # "Dmytro"/"dmytro" -> канонічне
        with open(out_path, "wb") as f:
            tts.tts(text, v, stress, f)

    return synth, ".wav"


ENGINES = {"edge": _edge_engine, "uk-tts": _uktts_engine}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("script")
    ap.add_argument("--engine", default=None, help="edge | uk-tts (інакше беремо зі скрипту)")
    ap.add_argument("--gap", type=int, default=GAP_MS, help="пауза між репліками, мс")
    args = ap.parse_args()

    from pydub import AudioSegment

    with open(args.script, encoding="utf-8") as f:
        spec = json.load(f)
    turns = spec["turns"]
    engine_name = args.engine or spec.get("engine", "edge")
    synth, tmp_ext = ENGINES[engine_name]()

    base = os.path.splitext(args.script)[0]
    fileid = os.path.basename(base)
    tmp = base + ".__seg" + tmp_ext

    track = AudioSegment.silent(duration=0, frame_rate=SR)
    gap = AudioSegment.silent(duration=args.gap, frame_rate=SR)
    rttm: list[str] = []
    ref: list[dict] = []

    print(f"engine={engine_name}  turns={len(turns)}")
    for i, t in enumerate(turns, 1):
        synth(t["text"], t["voice"], tmp)
        seg = AudioSegment.from_file(tmp).set_frame_rate(SR).set_channels(1)
        start = len(track) / 1000.0
        dur = len(seg) / 1000.0
        track += seg + gap
        spk = t["speaker"]
        rttm.append(
            f"SPEAKER {fileid} 1 {start:.3f} {dur:.3f} <NA> <NA> "
            f"{spk.replace(' ', '_')} <NA> <NA>"
        )
        ref.append({"speaker": spk, "start": round(start, 2),
                    "end": round(start + dur, 2), "text": t["text"]})
        print(f"  [{i}/{len(turns)}] {spk} ({t['voice']}) {dur:.1f}s")

    if os.path.exists(tmp):
        os.remove(tmp)
    track.export(base + ".wav", format="wav")
    with open(base + ".rttm", "w", encoding="utf-8") as f:
        f.write("\n".join(rttm) + "\n")
    with open(base + ".ref.json", "w", encoding="utf-8") as f:
        json.dump(ref, f, ensure_ascii=False, indent=2)
    print(f"OK  {len(track) / 1000.0:.1f}s -> {base}.wav  (+ .rttm, .ref.json)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
