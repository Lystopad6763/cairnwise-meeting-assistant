"""Бенчмарк ДІАРИЗАТОРІВ («хто говорить») проти ground-truth.

Порівнює pyannote-пайплайни (3.1 vs community-1) на озвучених зустрічах (<id>.wav +
<id>.ref.json — еталон від synthesize_dialogue.py). Метрики:
  DER       — diarization error rate (нижче = краще), permutation-invariant
  spk-error — |к-сть знайдених спікерів − справжня| (чи вгадав кількість голосів)

Чиста діаризація — ASR не потрібен. Результат -> eval/results/diarizer_benchmark.md.

  python scripts/benchmark_diarizers.py
  python scripts/benchmark_diarizers.py --models pyannote/speaker-diarization-community-1
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _env import load_env       # noqa: E402  — HF_TOKEN + HF_HUB_DISABLE_SYMLINKS
from transcribe import _cuda    # noqa: E402

DEFAULT_DIARIZERS = [
    "pyannote/speaker-diarization-3.1",
    "pyannote/speaker-diarization-community-1",
]


def _annotation(segments):
    """[{speaker,start,end}] -> pyannote Annotation."""
    from pyannote.core import Annotation, Segment
    a = Annotation()
    for i, s in enumerate(segments):
        a[Segment(float(s["start"]), float(s["end"])), i] = s["speaker"]
    return a


def _diar_segments(diarization):
    """pyannote Annotation -> [{speaker,start,end}]."""
    return [{"speaker": spk, "start": turn.start, "end": turn.end}
            for turn, _, spk in diarization.itertracks(yield_label=True)]


def _load_pipeline(model: str, token: str, device: str):
    from pyannote.audio import Pipeline
    try:
        pipe = Pipeline.from_pretrained(model, token=token)          # pyannote-audio 4.x
    except TypeError:
        pipe = Pipeline.from_pretrained(model, use_auth_token=token)  # старіший API
    import torch
    pipe.to(torch.device(device))
    return pipe


def _fmt(x) -> str:
    return f"{x:.3f}" if isinstance(x, (int, float)) else "—"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--models", nargs="+", default=DEFAULT_DIARIZERS)
    ap.add_argument("--root", default="data/projects")
    ap.add_argument("--out", default="eval/results/diarizer_benchmark.md")
    args = ap.parse_args()

    load_env()
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if not token:
        print("ERROR: HF_TOKEN не заданий (.env).", file=sys.stderr)
        return 1

    device = "cuda" if _cuda() else "cpu"
    wavs = sorted(glob.glob(os.path.join(args.root, "*", "meetings", "*.wav")))
    pairs = [(w, os.path.splitext(w)[0] + ".ref.json") for w in wavs]
    pairs = [(w, r) for w, r in pairs if os.path.exists(r)]
    if not pairs:
        print("Немає озвучених зустрічей. Спершу озвуч хоч одну:\n"
              "  python scripts/synthesize_dialogue.py data/projects/nimbus/meetings/sprint_planning01.json",
              file=sys.stderr)
        return 1
    print(f"device={device}  meetings={len(pairs)}  diarizers={args.models}\n")

    from pyannote.metrics.diarization import DiarizationErrorRate

    rows = []
    for model in args.models:
        print(f"=== {model} ===")
        try:
            pipe = _load_pipeline(model, token, device)
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL load: {type(exc).__name__}: {exc}", file=sys.stderr)
            rows.append((model, None, None, None))
            continue
        ders, spk_errs = [], []
        t0 = time.perf_counter()
        for w, r in pairs:
            ref = json.load(open(r, encoding="utf-8"))
            try:
                diar = pipe(w)
            except Exception as exc:  # noqa: BLE001
                print(f"  {os.path.basename(w)}: FAIL {type(exc).__name__}: {exc}", file=sys.stderr)
                continue
            hyp = _diar_segments(diar)
            der = DiarizationErrorRate()(_annotation(ref), _annotation(hyp))
            n_ref = len({s["speaker"] for s in ref})
            n_hyp = len({s["speaker"] for s in hyp})
            ders.append(der)
            spk_errs.append(abs(n_hyp - n_ref))
            print(f"  {os.path.basename(w):28} DER={der:.3f}  speakers {n_hyp}/{n_ref}")
        dur = time.perf_counter() - t0
        mean_der = sum(ders) / len(ders) if ders else None
        mean_spk = sum(spk_errs) / len(spk_errs) if spk_errs else None
        rows.append((model, mean_der, mean_spk, dur / max(1, len(pairs))))
        print(f"  -> mean DER={_fmt(mean_der)}  spk-error={_fmt(mean_spk)}"
              f"  ({dur / max(1, len(pairs)):.1f}s/meeting)\n")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("# Diarizer benchmark («хто говорить») — синтетичні UA-зустрічі\n\n")
        f.write(f"Зустрічей: {len(pairs)} · device: {device}\n\n")
        f.write("| Діаризатор | DER ↓ | spk-error ↓ | сек/зустріч |\n|---|---|---|---|\n")
        for model, der, spk, spm in rows:
            f.write(f"| {model} | {_fmt(der)} | {_fmt(spk)} | {_fmt(spm)} |\n")
        f.write("\n_DER — частка часу з неправильним спікером (нижче краще). "
                "spk-error — наскільки промахнувся в кількості голосів._\n")
    print(f"OK -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
