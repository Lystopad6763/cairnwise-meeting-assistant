"""Аудіо -> діаризований транскрипт JSON. Ядро Агента 1.

Працює на будь-якому wav, незалежно від джерела:
  - живий loopback-захоплення (capture_loopback.py)  -> демо / реальна зустріч
  - yt-dlp-завантаження (чистий датасет)              -> матеріал для golden-set
    (yt-dlp -x --audio-format wav -o data/raw/%(id)s.wav <url>)

Вихід: [{"speaker": "Speaker 1", "start": 0.0, "end": 4.2, "text": "..."}]
Діаризація потребує HF_TOKEN + прийнятих умов pyannote (див. MODELS.md); без токена
повертає транскрипт без спікер-лейблів (усе як Speaker 1).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _env import load_env  # noqa: E402  — підхопити HF_TOKEN з .env


def _cuda() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


def _load_diarizer():
    """API WhisperX міняв розташування DiarizationPipeline між версіями."""
    try:
        from whisperx.diarize import DiarizationPipeline  # 3.2+
    except Exception:
        from whisperx import DiarizationPipeline          # старіші
    return DiarizationPipeline


def _normalize(segments: list[dict]) -> list[dict]:
    """SPEAKER_00/01 -> стабільні «Speaker 1/2/3» у порядку появи (розд. 7 спеки)."""
    mapping: dict[str, str] = {}
    out: list[dict] = []
    for s in segments:
        if s.get("start") is None or not str(s.get("text", "")).strip():
            continue
        spk = s.get("speaker") or "SPEAKER_00"
        if spk not in mapping:
            mapping[spk] = f"Speaker {len(mapping) + 1}"
        out.append({
            "speaker": mapping[spk],
            "start": round(float(s["start"]), 2),
            "end": round(float(s["end"]), 2),
            "text": str(s["text"]).strip(),
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("audio")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--lang", default=None, help="uk / en; без неї — авто-визначення")
    ap.add_argument("--model", default="large-v3", help="на 4 GB GPU -> medium")
    ap.add_argument("--device", default=None)
    ap.add_argument("--no-diarize", action="store_true")
    args = ap.parse_args()

    load_env()  # HF_TOKEN + фікс symlink-кешу HF (до будь-якого завантаження моделі)

    import whisperx

    device = args.device or ("cuda" if _cuda() else "cpu")
    compute = "int8"  # дружньо до <8 GB (і до CPU)
    print(f"device={device} model={args.model} compute={compute}")

    model = whisperx.load_model(args.model, device, compute_type=compute, language=args.lang)
    audio = whisperx.load_audio(args.audio)
    result = model.transcribe(audio, batch_size=8)
    lang = result.get("language", args.lang or "en")

    # word-level alignment — точніші timestamps для цитат у RAG
    try:
        amodel, meta = whisperx.load_align_model(language_code=lang, device=device)
        result = whisperx.align(result["segments"], amodel, meta, audio, device)
    except Exception as exc:  # noqa: BLE001 — alignment не критичний
        print(f"[align skipped] {exc}", file=sys.stderr)

    if not args.no_diarize:
        load_env()  # .env -> os.environ (HF_TOKEN)
        token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
        if not token:
            print("[diarize skipped] set HF_TOKEN (+ accept pyannote terms)", file=sys.stderr)
        else:
            try:
                DiarPipe = _load_diarizer()
                try:
                    diarize = DiarPipe(token=token, device=device)        # whisperx 3.8+
                except TypeError:
                    diarize = DiarPipe(use_auth_token=token, device=device)  # старіший API
                result = whisperx.assign_word_speakers(diarize(audio), result)
            except Exception as exc:  # noqa: BLE001
                print(f"[diarize failed] {exc}", file=sys.stderr)

    segments = _normalize(result["segments"])
    speakers = len({s["speaker"] for s in segments})
    out = args.out or (os.path.splitext(args.audio)[0] + ".json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(segments, f, ensure_ascii=False, indent=2)
    print(f"OK  {len(segments)} segments, {speakers} speaker(s)  ->  {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
