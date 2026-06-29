"""Бенчмарк STT + diarization проти ground-truth (синтетичні TTS-зустрічі).

Для кожної озвученої зустрічі (`<id>.wav` + `<id>.ref.json` — еталон, що його дав
synthesize_dialogue.py) ганяє конфіги WhisperX (різні whisper-моделі) з pyannote-діаризацією,
рахує три метрики й пише таблицю в `eval/results/asr_diar_benchmark.md`:

  WER   — точність тексту загалом            (jiwer)
  DER   — точність «хто коли говорив»         (pyannote.metrics)
  cpWER — «текст по учаснику» (головна)        (meeteval якщо є, інакше власний
                                               Hungarian+jiwer fallback — однакова формула)

Передумови:
  pip install -r requirements-ingest.txt
  $env:HF_TOKEN = "hf_xxx"                      # pyannote (gated)
  python scripts/synthesize_all.py             # створити .wav + .ref.json
  python scripts/benchmark_asr_diar.py         # за замовч. моделі: large-v3, medium

На <8 GB GPU моделі вантажаться по черзі (один конфіг за раз), тож памʼяті вистачає.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import time

# helpers з transcribe.py (той самий каталог scripts/)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from transcribe import _cuda, _load_diarizer, _normalize  # noqa: E402
from _env import load_env  # noqa: E402  — підхопити HF_TOKEN з .env

DEFAULT_MODELS = ["large-v3", "medium"]


def norm(t: str) -> str:
    """Нормалізація для WER: lowercase, прибрати пунктуацію, стиснути пробіли (UA-safe)."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", t.lower())).strip()


def run_pipeline(wav: str, model_name: str, device: str, token: str | None) -> list[dict]:
    """wav -> діаризований hypothesis [{speaker,start,end,text}] (як transcribe.py)."""
    import whisperx

    model = whisperx.load_model(model_name, device, compute_type="int8")
    audio = whisperx.load_audio(wav)
    result = model.transcribe(audio, batch_size=8)
    lang = result.get("language", "uk")
    try:
        amodel, meta = whisperx.load_align_model(language_code=lang, device=device)
        result = whisperx.align(result["segments"], amodel, meta, audio, device)
    except Exception as exc:  # noqa: BLE001
        print(f"    [align skipped] {exc}", file=sys.stderr)
    if token:
        try:
            diar = _load_diarizer()(use_auth_token=token, device=device)
            result = whisperx.assign_word_speakers(diar(audio), result)
        except Exception as exc:  # noqa: BLE001
            print(f"    [diarize failed] {exc}", file=sys.stderr)
    return _normalize(result["segments"])


def _by_speaker(segments: list[dict]) -> dict[str, str]:
    out: dict[str, list[str]] = {}
    for s in sorted(segments, key=lambda x: x["start"]):
        out.setdefault(s["speaker"], []).append(s["text"])
    return {k: norm(" ".join(v)) for k, v in out.items()}


def _cpwer_fallback(ref: dict[str, str], hyp: dict[str, str]) -> float | None:
    """cpWER без meeteval (на Windows той не ставиться без MSVC).

    cpWER = мінімальна сума word-edit'ів (S+D+I) по найкращому співставленню
    ref↔hyp спікерів, поділена на загальну к-сть слів у ref. Призначення —
    оптимальне (Hungarian, scipy); менший бік доповнюється «порожніми» спікерами,
    тож зайвий/пропущений голос карається як вставки/видалення.
    """
    import jiwer
    import numpy as np
    from scipy.optimize import linear_sum_assignment

    r_spk, h_spk = list(ref), list(hyp)
    total_ref = sum(len(ref[s].split()) for s in r_spk)
    if total_ref == 0:
        return None
    n = max(len(r_spk), len(h_spk)) or 1
    cost = np.zeros((n, n))
    for i in range(n):
        rt = ref[r_spk[i]] if i < len(r_spk) else ""
        for j in range(n):
            ht = hyp[h_spk[j]] if j < len(h_spk) else ""
            if not rt and not ht:
                c = 0.0
            elif not rt:
                c = float(len(ht.split()))            # усе — вставки
            elif not ht:
                c = float(len(rt.split()))            # усе — видалення
            else:
                o = jiwer.process_words(rt, ht)
                c = float(o.substitutions + o.deletions + o.insertions)
            cost[i, j] = c
    r_idx, c_idx = linear_sum_assignment(cost)
    return float(cost[r_idx, c_idx].sum()) / total_ref


def score(ref: list[dict], hyp: list[dict]) -> dict:
    import jiwer

    ref_text = norm(" ".join(s["text"] for s in sorted(ref, key=lambda x: x["start"])))
    hyp_text = norm(" ".join(s["text"] for s in sorted(hyp, key=lambda x: x["start"])))
    m = {"wer": jiwer.wer(ref_text, hyp_text) if ref_text else None, "der": None, "cpwer": None}

    try:
        from pyannote.core import Annotation, Segment
        from pyannote.metrics.diarization import DiarizationErrorRate

        def ann(segs):
            a = Annotation()
            for s in segs:
                a[Segment(s["start"], s["end"])] = s["speaker"]
            return a

        m["der"] = DiarizationErrorRate()(ann(ref), ann(hyp))
    except Exception as exc:  # noqa: BLE001
        print(f"    [DER skipped] {exc}", file=sys.stderr)

    try:
        from meeteval.wer import cp_word_error_rate

        res = cp_word_error_rate(_by_speaker(ref), _by_speaker(hyp))
        m["cpwer"] = res.error_rate
    except Exception:  # noqa: BLE001  — meeteval нема (Windows) -> власний cpWER
        try:
            m["cpwer"] = _cpwer_fallback(_by_speaker(ref), _by_speaker(hyp))
        except Exception as exc:  # noqa: BLE001
            print(f"    [cpWER skipped] {exc}", file=sys.stderr)

    return m


def _fmt(x) -> str:
    return f"{x:.3f}" if isinstance(x, (int, float)) else "—"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    ap.add_argument("--root", default="data/projects")
    ap.add_argument("--out", default="eval/results/asr_diar_benchmark.md")
    args = ap.parse_args()

    device = "cuda" if _cuda() else "cpu"
    load_env()  # .env -> os.environ (HF_TOKEN)
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if not token:
        print("WARN: HF_TOKEN не заданий — діаризація вимкнена, DER/cpWER будуть неінформативні.",
              file=sys.stderr)

    wavs = sorted(glob.glob(os.path.join(args.root, "*", "meetings", "*.wav")))
    pairs = [(w, os.path.splitext(w)[0] + ".ref.json") for w in wavs]
    pairs = [(w, r) for w, r in pairs if os.path.exists(r)]
    if not pairs:
        print("Немає озвучених зустрічей. Спершу: python scripts/synthesize_all.py", file=sys.stderr)
        return 1
    print(f"device={device}  meetings={len(pairs)}  models={args.models}\n")

    rows = []
    for model_name in args.models:
        print(f"=== {model_name} ===")
        agg = {"wer": [], "der": [], "cpwer": []}
        t0 = time.perf_counter()
        for w, r in pairs:
            ref = json.load(open(r, encoding="utf-8"))
            hyp = run_pipeline(w, model_name, device, token)
            sc = score(ref, hyp)
            for k in agg:
                if sc[k] is not None:
                    agg[k].append(sc[k])
            print(f"  {os.path.basename(w):26} WER={_fmt(sc['wer'])} DER={_fmt(sc['der'])} cpWER={_fmt(sc['cpwer'])}")
        dur = time.perf_counter() - t0
        mean = {k: (sum(v) / len(v) if v else None) for k, v in agg.items()}
        rows.append((model_name, mean, dur / max(1, len(pairs))))
        print(f"  -> mean WER={_fmt(mean['wer'])} DER={_fmt(mean['der'])} cpWER={_fmt(mean['cpwer'])}"
              f"  ({dur / max(1, len(pairs)):.1f}s/meeting)\n")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("# ASR + Diarization benchmark (синтетичні UA-зустрічі)\n\n")
        f.write(f"Зустрічей: {len(pairs)} · device: {device} · diarization: pyannote-3.1\n\n")
        f.write("| Модель | WER ↓ | DER ↓ | cpWER ↓ | сек/зустріч |\n|---|---|---|---|---|\n")
        for name, mean, spm in rows:
            f.write(f"| {name} | {_fmt(mean['wer'])} | {_fmt(mean['der'])} | {_fmt(mean['cpwer'])} | {spm:.1f} |\n")
        f.write("\n_WER — текст загалом; DER — хто/коли; **cpWER — текст по учаснику (головна)**._\n")
    print(f"OK -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
