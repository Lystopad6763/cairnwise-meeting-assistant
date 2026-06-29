"""Pre-download local model weights for Cairnwise (fully-local, GPU <8 GB).

Pulls the HuggingFace weights (Whisper STT, pyannote diarization, embeddings, reranker)
into the local HF cache. The LLM is served via Ollama, so it is NOT downloaded here —
run `ollama pull qwen2.5:7b-instruct` separately (see MODELS.md).

Usage (PowerShell):
    $env:HF_TOKEN = "hf_xxx"          # needed only for the gated pyannote models
    python scripts/download_models.py
    python scripts/download_models.py --small   # 4 GB GPU: medium Whisper + e5-base

The gated pyannote models additionally require accepting their terms on the model pages:
    https://huggingface.co/pyannote/speaker-diarization-3.1
    https://huggingface.co/pyannote/segmentation-3.0
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _env import load_env  # noqa: E402  — підхопити HF_TOKEN з .env

# (repo_id, gated?) — gated repos need HF_TOKEN *and* accepted terms on the model page.
FULL = [
    ("Systran/faster-whisper-large-v3", False),   # STT  (int8 at load time)
    ("pyannote/speaker-diarization-3.1", True),   # diarization pipeline
    ("pyannote/segmentation-3.0", True),          # its segmentation dependency
    ("BAAI/bge-m3", False),                        # embeddings (multilingual, strong UA)
    ("BAAI/bge-reranker-v2-m3", False),            # reranker
]
# Lighter set for a 4 GB GPU / weak CPU.
SMALL = [
    ("Systran/faster-whisper-medium", False),
    ("pyannote/speaker-diarization-3.1", True),
    ("pyannote/segmentation-3.0", True),
    ("intfloat/multilingual-e5-base", False),
    ("BAAI/bge-reranker-v2-m3", False),
]

# Diarization benchmark candidates ("розрізнити людей за голосом") — порівнюємо DER/cpWER
# у benchmark_asr_diar.py. Усі pyannote — GATED (HF token + прийняти умови на сторінці КОЖНОЇ).
DIAR = [
    ("pyannote/speaker-diarization-3.1", True),          # baseline (інтегрований у WhisperX)
    ("pyannote/segmentation-3.0", True),                 #   його залежність
    ("pyannote/speaker-diarization-community-1", True),  # новіший community-пайплайн (часто кращий)
    ("pyannote/wespeaker-voxceleb-resnet34-LM", True),   # speaker-embedding (спільна залежність)
]
# Важче/опційно (не через snapshot): NVIDIA NeMo Sortformer end-to-end — nvidia/diar_sortformer_4spk-v1

OLLAMA_FULL = "qwen2.5:7b-instruct"
OLLAMA_SMALL = "qwen2.5:3b-instruct"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--small", action="store_true",
                    help="lighter weights for a 4 GB GPU (medium Whisper + e5-base)")
    ap.add_argument("--diar", action="store_true",
                    help="лише моделі ДІАРИЗАЦІЇ під бенчмарк (pyannote 3.1 / community-1 + залежності)")
    args = ap.parse_args()

    try:
        from huggingface_hub import snapshot_download
        from huggingface_hub.utils import GatedRepoError, RepositoryNotFoundError
    except ImportError:
        print("Install the hub client first:  pip install huggingface_hub", file=sys.stderr)
        return 1

    load_env()  # .env -> os.environ (HF_TOKEN)
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    models = DIAR if args.diar else (SMALL if args.small else FULL)
    ollama = OLLAMA_SMALL if args.small else OLLAMA_FULL

    failures: list[str] = []
    for repo_id, gated in models:
        label = f"{repo_id}{'  [gated]' if gated else ''}"
        if gated and not token:
            print(f"SKIP  {label} — set HF_TOKEN to download (see MODELS.md)")
            failures.append(repo_id)
            continue
        print(f"...   {label}")
        try:
            path = snapshot_download(repo_id, token=token if gated else None)
            print(f"OK    {repo_id}  ->  {path}")
        except GatedRepoError:
            print(f"FAIL  {repo_id} — accept the terms on its HF page, then retry")
            failures.append(repo_id)
        except RepositoryNotFoundError:
            print(f"FAIL  {repo_id} — repo not found / no access")
            failures.append(repo_id)
        except Exception as exc:  # noqa: BLE001 — report and continue with the rest
            print(f"FAIL  {repo_id} — {type(exc).__name__}: {exc}")
            failures.append(repo_id)

    print("\n" + "-" * 60)
    if not args.diar:
        print(f"Next: install Ollama (ollama.com), then:\n    ollama pull {ollama}")
    if failures:
        print(f"\n{len(failures)} model(s) not downloaded: {', '.join(failures)}")
        return 1
    print("\nAll HF weights downloaded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
