"""Захоплення системного звуку (WASAPI loopback) у 16 kHz mono wav.

Це «апка чує голос»: коли грає YouTube або йде зустріч через колонки/гарнітуру, loopback
віддає той самий звук у файл -> далі transcribe.py. Опційно домішує мікрофон (твій голос
на реальній зустрічі — loopback ловить тільки те, що йде у динаміки/гарнітуру).

  python scripts/capture_loopback.py --seconds 120 -o data/raw/meet01.wav
  python scripts/capture_loopback.py --mic            # без --seconds: Ctrl+C щоб спинити
"""
from __future__ import annotations

import argparse

import numpy as np

SR = 16000          # Whisper хоче 16 kHz
BLOCK = SR // 10    # 100 ms


def _mono(x) -> np.ndarray:
    x = np.asarray(x, dtype="float32")
    return x.mean(axis=1) if x.ndim == 2 else x


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-o", "--out", default="capture.wav")
    ap.add_argument("--seconds", type=float, default=None, help="тривалість; без неї — до Ctrl+C")
    ap.add_argument("--mic", action="store_true", help="домішати мікрофон (твій голос)")
    args = ap.parse_args()

    import soundcard as sc
    import soundfile as sf

    spk = sc.default_speaker()
    loop = sc.get_microphone(str(spk.name), include_loopback=True)
    mic = sc.default_microphone() if args.mic else None

    n_blocks = int(args.seconds * 10) if args.seconds else None
    tail = f" for {args.seconds}s" if args.seconds else " (Ctrl+C to stop)"
    print(f"Recording loopback of '{spk.name}'" + (" + mic" if mic else "") + tail + " ...")

    chunks: list[np.ndarray] = []
    try:
        if mic:
            with loop.recorder(samplerate=SR, channels=1) as lr, \
                 mic.recorder(samplerate=SR, channels=1) as mr:
                i = 0
                while n_blocks is None or i < n_blocks:
                    chunks.append(_mono(lr.record(BLOCK)) + _mono(mr.record(BLOCK)))
                    i += 1
        else:
            with loop.recorder(samplerate=SR, channels=1) as lr:
                i = 0
                while n_blocks is None or i < n_blocks:
                    chunks.append(_mono(lr.record(BLOCK)))
                    i += 1
    except KeyboardInterrupt:
        print("\nstopped")

    audio = np.clip(np.concatenate(chunks), -1.0, 1.0) if chunks else np.zeros(1, "float32")
    sf.write(args.out, audio, SR)
    print(f"OK  {len(audio) / SR:.1f}s -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
