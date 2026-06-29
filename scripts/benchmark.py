"""ЄДИНИЙ бенчмарк: аудіо -> структурований per-speaker JSON. Одна команда — уся матриця.

Порівнює матрицю (Whisper-модель × діаризатор) на озвучених зустрічах і друкує таблицю,
ранжовану за cpWER (головна метрика — «текст по кожному учаснику»). Кожна модель ASR
вантажиться РАЗ, кожен діаризатор РАЗ (а не |models|×|diar| разів) — щадить 4 GB GPU.

Метрики (див. README/JOURNAL):
  cpWER 🏆  текст по спікеру (ASR+діар разом)   ↓   Hungarian-співставлення + jiwer (без meeteval)
  WER       текст загалом (лише ASR)            ↓   jiwer
  DER       хто/коли (лише діаризація)          ↓   pyannote.metrics
  Purity↑/Coverage↑/F1↑  чистота/повнота спікер-кластерів (= precision/recall/F1 з курсу)
  spkΔ      |знайдено − справді| голосів         ↓
  s/mtg·RTF швидкість на GPU                     ↓

  python scripts/benchmark.py                                  # всі озвучені, дефолтна матриця
  python scripts/benchmark.py --voice m05_daily_standup        # спершу озвучити, тоді бенчмарк
  python scripts/benchmark.py --whisper large-v3 medium small  # додати кандидатів ASR
  python scripts/benchmark.py --selftest                       # перевірити математику метрик (без аудіо)
"""
from __future__ import annotations

import argparse
import copy
import glob
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _env import load_env            # noqa: E402  — HF_TOKEN + HF_HUB_DISABLE_SYMLINKS
from transcribe import _cuda, _normalize  # noqa: E402

DEFAULT_WHISPER = ["medium", "small"]            # large-v3 додавай вручну, якщо влізе в 4 GB
DEFAULT_DIAR = [
    "pyannote/speaker-diarization-3.1",
    "pyannote/speaker-diarization-community-1",
]
SR = 16000

# Whisper initial_prompt зміщує словник декодера під ДОМЕН зустрічі. Whisper і так добре
# розпізнає звичайну мову (чистий укр. ~ідеальний) — глосарій лише для СПЕЦ-ТЕРМІНІВ домену.
#
# У ПРОДІ глосарій — PER-PROJECT і конфігурований (НЕ хардкод): тех-проєкт → тех-терміни,
# маркетинг → маркетингові, нетехнічна зустріч → загальний/порожній. Поповнюється авто з памʼяті
# проєкту (часті/OOV-терміни його зустрічей) + ручні правки. Працює для БУДЬ-ЯКОЇ зустрічі.
#
# DEFAULT_GLOSSARY тут — РЕПРЕЗЕНТАТИВНИЙ ЗАГАЛЬНИЙ (не підігнаний під конкретну зустріч):
# нейтральні терміни наради + типові софт/PM-слова домену нашого датасету. Специфічні сутності
# проєкту (назви продуктів/інтеграцій) сюди НЕ кладемо — це per-project шар (--prompt "...").
GENERAL_GLOSSARY = (   # доменно-нейтральні слова будь-якої робочої зустрічі
    "Робоча зустріч. Порядок денний, рішення, дедлайн, відповідальний, наступні кроки, "
    "блокер, ризик, бюджет, пріоритет, статус, результат, домовленість, дія."
)
DOMAIN_GLOSSARY = (    # домен НАШОГО датасету (PM/розробка ПЗ); для іншого домену був би інший
    "Розробка ПЗ: спринт, story point, бэклог, стендап, ретроспектива, демо, реліз, деплой, "
    "Jira, тікет, баг, код-рев'ю, pull request, API, endpoint, бекенд, фронтенд, QA, "
    "вебхук, OAuth, токен, база даних, Docker."
)
DEFAULT_GLOSSARY = GENERAL_GLOSSARY + " " + DOMAIN_GLOSSARY


# ---------------------------------------------------------------- метрики (математика)
def norm(t: str) -> str:
    """Нормалізація для WER: lower, прибрати пунктуацію, стиснути пробіли (UA-safe)."""
    import re
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", str(t).lower())).strip()


def _by_speaker(segments: list[dict]) -> dict[str, str]:
    out: dict[str, list[str]] = {}
    for s in sorted(segments, key=lambda x: x["start"]):
        out.setdefault(s["speaker"], []).append(s["text"])
    return {k: norm(" ".join(v)) for k, v in out.items()}


def _cpwer(ref_spk: dict[str, str], hyp_spk: dict[str, str]) -> float | None:
    """cpWER без meeteval: мін. сума word-edit'ів (S+D+I) по ОПТИМАЛЬНОМУ співставленню
    ref↔hyp спікерів / усі слова ref. Менший бік доповнюється «порожніми» спікерами, тож
    зайвий/пропущений голос карається як вставки/видалення (Hungarian, scipy)."""
    import jiwer
    import numpy as np
    from scipy.optimize import linear_sum_assignment

    r, h = list(ref_spk), list(hyp_spk)
    total_ref = sum(len(ref_spk[s].split()) for s in r)
    if total_ref == 0:
        return None
    n = max(len(r), len(h)) or 1
    cost = np.zeros((n, n))
    for i in range(n):
        rt = ref_spk[r[i]] if i < len(r) else ""
        for j in range(n):
            ht = hyp_spk[h[j]] if j < len(h) else ""
            if not rt and not ht:
                c = 0.0
            elif not rt:
                c = float(len(ht.split()))
            elif not ht:
                c = float(len(rt.split()))
            else:
                o = jiwer.process_words(rt, ht)
                c = float(o.substitutions + o.deletions + o.insertions)
            cost[i, j] = c
    ri, ci = linear_sum_assignment(cost)
    return float(cost[ri, ci].sum()) / total_ref


def _annotation(segments: list[dict]):
    from pyannote.core import Annotation, Segment
    a = Annotation()
    for i, s in enumerate(segments):
        st, en = float(s["start"]), float(s["end"])
        if en > st:
            a[Segment(st, en), i] = s["speaker"]
    return a


def diar_metrics(ref: list[dict], hyp: list[dict]) -> dict:
    """DER + Purity/Coverage/F1 (= precision/recall/F1 з курсу для кластеризації)."""
    from pyannote.metrics.diarization import (
        DiarizationCoverage,
        DiarizationErrorRate,
        DiarizationPurity,
    )
    R, H = _annotation(ref), _annotation(hyp)
    p = float(DiarizationPurity()(R, H))
    c = float(DiarizationCoverage()(R, H))
    f1 = (2 * p * c / (p + c)) if (p + c) else 0.0
    return {
        "der": float(DiarizationErrorRate()(R, H)),
        "purity": p,
        "coverage": c,
        "pc_f1": f1,
    }


def score(ref: list[dict], hyp: list[dict]) -> dict:
    """Усі метрики для однієї зустрічі."""
    import jiwer

    ref_text = norm(" ".join(s["text"] for s in sorted(ref, key=lambda x: x["start"])))
    hyp_text = norm(" ".join(s["text"] for s in sorted(hyp, key=lambda x: x["start"])))
    m = {"wer": jiwer.wer(ref_text, hyp_text) if ref_text else None,
         "cpwer": _cpwer(_by_speaker(ref), _by_speaker(hyp)),
         "der": None, "purity": None, "coverage": None, "pc_f1": None}
    try:
        m.update(diar_metrics(ref, hyp))
    except Exception as exc:  # noqa: BLE001
        print(f"    [diar-metrics skipped] {type(exc).__name__}: {exc}", file=sys.stderr)
    n_ref = len({s["speaker"] for s in ref})
    n_hyp = len({s["speaker"] for s in hyp})
    m["spk_err"] = abs(n_hyp - n_ref)
    return m


# ---------------------------------------------------------------- GPU-конвеєр
def _free_gpu():
    import gc
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def transcribe(wav: str, model_name: str, device: str, lang: str,
               batch_size: int = 8, prompt: str | None = None) -> tuple[dict, float]:
    """wav -> (aligned segments, compute_secs). compute_secs = ЧИСТИЙ inference
    (декод аудіо + транскрипція), БЕЗ завантаження/скачування моделі — бо в проді модель
    вантажиться раз на старті, а не на кожну зустріч. Модель звільняється одразу (щадимо VRAM).
    prompt -> Whisper initial_prompt (зміщує словник під домен, зменшує калічення термінів)."""
    import whisperx
    asr_options = {"initial_prompt": prompt} if prompt else None
    model = whisperx.load_model(model_name, device, compute_type="int8", language=lang,
                                asr_options=asr_options)  # load/download — ПОЗА таймером
    t0 = time.perf_counter()
    audio = whisperx.load_audio(wav)
    result = model.transcribe(audio, batch_size=batch_size)
    compute = time.perf_counter() - t0          # чистий ASR-inference
    rlang = result.get("language", lang)
    del model            # звільнити Whisper ПЕРЕД align (щоб не тримати дві моделі у 4 GB)
    _free_gpu()
    try:
        amodel, meta = whisperx.load_align_model(language_code=rlang, device=device)
        result = whisperx.align(result["segments"], amodel, meta, audio, device)  # align — уточнення, поза таймером
        del amodel
    except Exception as exc:  # noqa: BLE001 — alignment не критичний
        print(f"    [align skipped] {exc}", file=sys.stderr)
    del audio
    _free_gpu()
    return result, compute


def diarize(wav: str, model_name: str, token: str, device: str,
            num_speakers: int | None) -> tuple[object, float]:
    """wav -> (diarize DataFrame, compute_secs). compute_secs = чистий inference діаризації,
    БЕЗ завантаження пайплайна. Пайплайн звільняється одразу."""
    from whisperx.diarize import DiarizationPipeline
    pipe = DiarizationPipeline(model_name=model_name, token=token, device=device)  # load — ПОЗА таймером
    t0 = time.perf_counter()
    df = pipe(wav, num_speakers=num_speakers)
    compute = time.perf_counter() - t0
    if isinstance(df, tuple):          # return_embeddings=True -> (df, emb)
        df = df[0]
    del pipe
    _free_gpu()
    return df, compute


# ---------------------------------------------------------------- допоміжне
def _fmt(x, nd=3) -> str:
    return f"{x:.{nd}f}" if isinstance(x, (int, float)) else "—"


def _short_diar(name: str) -> str:
    return name.replace("pyannote/speaker-diarization-", "pa-")


def _resolve_meeting(arg: str, root: str) -> str | None:
    if os.path.exists(arg):
        return arg
    name = arg if arg.endswith(".json") else arg + ".json"
    hits = glob.glob(os.path.join(root, "*", "meetings", name))
    if not hits:
        hits = [p for p in glob.glob(os.path.join(root, "*", "meetings", "*.json"))
                if arg in os.path.basename(p)]
    return hits[0] if hits else None


def _voice(meeting_ids: list[str], root: str, engine: str) -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    for mid in meeting_ids:
        path = _resolve_meeting(mid, root)
        if not path:
            print(f"  [voice] не знайшов зустріч '{mid}' під {root}", file=sys.stderr)
            continue
        wav = os.path.splitext(path)[0] + ".wav"
        if os.path.exists(wav):
            print(f"  [voice] вже озвучено: {os.path.basename(wav)} — пропускаю")
            continue
        print(f"  [voice] {os.path.basename(path)} (engine={engine}) ...")
        subprocess.run([sys.executable, os.path.join(here, "synthesize_dialogue.py"),
                        path, "--engine", engine], check=True)


# ---------------------------------------------------------------- self-test (без аудіо/GPU)
def selftest() -> int:
    """Перевірка математики метрик на синтетичних ref/hyp (без моделей)."""
    ref = [
        {"speaker": "Speaker 1", "start": 0.0, "end": 3.0, "text": "привіт усім почнемо нашу зустріч"},
        {"speaker": "Speaker 2", "start": 3.5, "end": 6.0, "text": "так я готовий доповідати"},
        {"speaker": "Speaker 1", "start": 6.5, "end": 9.0, "text": "чудово розкажи про прогрес"},
    ]
    print("== ідеальний hyp (усе правильно) ==")
    perfect = score(ref, copy.deepcopy(ref))
    for k, v in perfect.items():
        print(f"   {k:9} {_fmt(v)}")
    assert perfect["wer"] == 0 and perfect["cpwer"] == 0, "ідеал має давати 0"
    assert perfect["der"] == 0 and abs(perfect["pc_f1"] - 1.0) < 1e-6, "ідеал: DER=0, F1=1"
    assert perfect["spk_err"] == 0

    print("\n== зіпсований hyp (помилки тексту + переплутані спікери) ==")
    bad = [
        {"speaker": "A", "start": 0.0, "end": 3.0, "text": "привіт усім почнемо зустріч"},   # -1 слово
        {"speaker": "B", "start": 3.5, "end": 6.0, "text": "так я готовий доповісти"},         # 1 заміна
        {"speaker": "A", "start": 6.5, "end": 9.0, "text": "добре розкажи про прогрес команди"},# заміна+вставка
    ]
    bad_m = score(ref, bad)
    for k, v in bad_m.items():
        print(f"   {k:9} {_fmt(v)}")
    assert bad_m["wer"] > 0 and bad_m["cpwer"] > 0, "помилки мають давати >0"
    assert bad_m["spk_err"] == 0, "2 спікери проти 2 -> 0"

    print("\n== зайвий спікер (3 проти 2) ==")
    extra = bad + [{"speaker": "C", "start": 9.5, "end": 10.5, "text": "ще одна репліка"}]
    em = score(ref, extra)
    print(f"   spk_err   {_fmt(em['spk_err'])}  (очікувано 1)")
    assert em["spk_err"] == 1
    print("\nSELFTEST OK — метрики рахуються коректно.")
    return 0


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--whisper", nargs="+", default=DEFAULT_WHISPER)
    ap.add_argument("--diar", nargs="+", default=DEFAULT_DIAR)
    ap.add_argument("--root", default="data/projects")
    ap.add_argument("--out", default="eval/results/benchmark.md")
    ap.add_argument("--lang", default="uk")
    ap.add_argument("--batch-size", type=int, default=8,
                    help="батч транскрипції; на 4 GB GPU зменш до 4 чи 2 проти OOM")
    ap.add_argument("--dump", default=None,
                    help="каталог: зберегти hyp-JSON КОЖНОЇ комбінації (для інспекції/діфу)")
    ap.add_argument("--prompt", nargs="?", const=DEFAULT_GLOSSARY, default=None,
                    help="Whisper initial_prompt (глосарій тех-термінів); без значення = вбудований глосарій")
    ap.add_argument("--voice", nargs="*", default=None,
                    help="ID/шляхи зустрічей озвучити ПЕРЕД бенчмарком (uk-tts)")
    ap.add_argument("--engine", default="uk-tts", help="двигун озвучки для --voice")
    ap.add_argument("--known-speakers", action="store_true",
                    help="підказати діаризатору к-сть спікерів з ref (інакше — авто-оцінка)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    load_env()
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if not token:
        print("ERROR: HF_TOKEN не заданий (.env) — діаризація неможлива.", file=sys.stderr)
        return 1
    device = "cuda" if _cuda() else "cpu"

    if args.voice:
        print("== ОЗВУЧКА ==")
        _voice(args.voice, args.root, args.engine)

    wavs = sorted(glob.glob(os.path.join(args.root, "*", "meetings", "*.wav")))
    pairs = [(w, os.path.splitext(w)[0] + ".ref.json") for w in wavs]
    pairs = [(w, r) for w, r in pairs if os.path.exists(r)]
    if not pairs:
        print("Немає озвучених зустрічей (.wav + .ref.json). Спершу:\n"
              "  python scripts/benchmark.py --voice m05_daily_standup", file=sys.stderr)
        return 1

    refs = {w: json.load(open(r, encoding="utf-8")) for w, r in pairs}
    audio_secs = sum(max((s["end"] for s in refs[w]), default=0.0) for w, _ in pairs)
    print(f"\ndevice={device}  meetings={len(pairs)}  whisper={args.whisper}  "
          f"diar={[_short_diar(d) for d in args.diar]}  glossary={'on' if args.prompt else 'off'}\n")

    # 1) ASR раз на (модель), 2) діаризація раз на (діаризатор) — щадимо VRAM
    transcripts: dict[tuple, dict] = {}
    asr_secs: dict[str, float] = {}
    failed_whisper: set[str] = set()
    for wm in args.whisper:
        print(f"== ASR: {wm} ==")
        asr_secs[wm] = 0.0
        for w, _ in pairs:
            print(f"   transcribe {os.path.basename(w)}")
            try:
                transcripts[(wm, w)], dt = transcribe(w, wm, device, args.lang, args.batch_size, args.prompt)
                asr_secs[wm] += dt           # лише inference, без завантаження моделі
            except Exception as exc:  # noqa: BLE001 — найімовірніше CUDA OOM на 4 GB
                print(f"   FAIL {wm}: {type(exc).__name__}: {exc}", file=sys.stderr)
                print(f"   -> пропускаю модель {wm} (не влізла в GPU?) і йду далі", file=sys.stderr)
                failed_whisper.add(wm)
                _free_gpu()
                break
    whisper_models = [m for m in args.whisper if m not in failed_whisper]
    if not whisper_models:
        print("Жодна Whisper-модель не відпрацювала (OOM?). Спробуй --whisper small.", file=sys.stderr)
        return 1

    diar_dfs: dict[tuple, object] = {}
    diar_secs: dict[str, float] = {}
    for dm in args.diar:
        print(f"== DIAR: {_short_diar(dm)} ==")
        diar_secs[dm] = 0.0
        for w, _ in pairs:
            n_spk = len({s["speaker"] for s in refs[w]}) if args.known_speakers else None
            print(f"   diarize {os.path.basename(w)}")
            try:
                diar_dfs[(dm, w)], dt = diarize(w, dm, token, device, n_spk)
                diar_secs[dm] += dt          # лише inference, без завантаження пайплайна
            except Exception as exc:  # noqa: BLE001
                print(f"   FAIL {type(exc).__name__}: {exc}", file=sys.stderr)
                diar_dfs[(dm, w)] = None

    # 3) злиття всіх комбінацій (CPU) + метрики
    import whisperx
    rows = []
    for wm in whisper_models:
        for dm in args.diar:
            print(f"== EVAL: {wm} × {_short_diar(dm)} ==")
            agg: dict[str, list] = {k: [] for k in
                                    ("wer", "cpwer", "der", "purity", "coverage", "pc_f1", "spk_err")}
            for w, _ in pairs:
                df = diar_dfs.get((dm, w))
                result = copy.deepcopy(transcripts[(wm, w)])
                if df is not None and len(df):
                    result = whisperx.assign_word_speakers(df, result)
                hyp = _normalize(result["segments"])
                if args.dump:
                    os.makedirs(args.dump, exist_ok=True)
                    name = f"{os.path.splitext(os.path.basename(w))[0]}.{wm}.{_short_diar(dm)}.json"
                    with open(os.path.join(args.dump, name), "w", encoding="utf-8") as fh:
                        json.dump(hyp, fh, ensure_ascii=False, indent=2)
                sc = score(refs[w], hyp)
                for k in agg:
                    if sc.get(k) is not None:
                        agg[k].append(sc[k])
                print(f"   {os.path.basename(w):28} cpWER={_fmt(sc['cpwer'])} "
                      f"WER={_fmt(sc['wer'])} DER={_fmt(sc['der'])} F1={_fmt(sc['pc_f1'])}")
            mean = {k: (sum(v) / len(v) if v else None) for k, v in agg.items()}
            proc = (asr_secs.get(wm, 0) + diar_secs.get(dm, 0)) / max(1, len(pairs))
            rtf = ((asr_secs.get(wm, 0) + diar_secs.get(dm, 0)) / audio_secs) if audio_secs else None
            rows.append({"whisper": wm, "diar": _short_diar(dm), "proc": proc, "rtf": rtf, **mean})

    # ранжуємо за cpWER (головна); None -> в кінець
    rows.sort(key=lambda r: (r["cpwer"] is None, r["cpwer"] if r["cpwer"] is not None else 9e9))

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("# Бенчмарк: аудіо → per-speaker JSON (синтетичні UA-зустрічі)\n\n")
        f.write(f"Зустрічей: {len(pairs)} · device: {device} · "
                f"speakers: {'known' if args.known_speakers else 'auto'} · "
                f"glossary-prompt: {'так' if args.prompt else 'ні'}\n\n")
        f.write("| # | Whisper | Diarizer | cpWER ↓ | WER ↓ | DER ↓ | Purity ↑ | Cover ↑ | "
                "F1 ↑ | spkΔ ↓ | s/mtg | RTF |\n")
        f.write("|---|---|---|---|---|---|---|---|---|---|---|---|\n")
        for i, r in enumerate(rows, 1):
            best = " 🏆" if i == 1 else ""
            f.write(f"| {i}{best} | {r['whisper']} | {r['diar']} | {_fmt(r['cpwer'])} | "
                    f"{_fmt(r['wer'])} | {_fmt(r['der'])} | {_fmt(r['purity'])} | "
                    f"{_fmt(r['coverage'])} | {_fmt(r['pc_f1'])} | {_fmt(r['spk_err'],1)} | "
                    f"{_fmt(r['proc'],1)} | {_fmt(r['rtf'])} |\n")
        f.write("\n**Рішення — за найнижчим cpWER** (текст по учаснику). "
                "WER=лише ASR, DER=лише діаризація, Purity/Coverage/F1 = precision/recall/F1 "
                "кластеризації спікерів (тай-ін до курсу), spkΔ=помилка к-сті голосів. "
                "**s/mtg та RTF = ЧИСТИЙ inference** (завантаження/скачування моделі виключено — "
                "у проді модель вантажиться раз на старті, не на кожну зустріч).\n")

    print("\n=== ПІДСУМОК (ранжовано за cpWER) ===")
    for i, r in enumerate(rows, 1):
        print(f"  {i}. {r['whisper']:9} × {r['diar']:14} "
              f"cpWER={_fmt(r['cpwer'])} WER={_fmt(r['wer'])} DER={_fmt(r['der'])} "
              f"F1={_fmt(r['pc_f1'])} spkΔ={_fmt(r['spk_err'],1)} {_fmt(r['proc'],1)}s/mtg")
    print(f"\nOK -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
