# Cairnwise — Локальні моделі (fully-local, privacy-first)

> Рішення-документ: які ваги тягнемо з HuggingFace / Ollama, чому саме ці, і як вони
> влазять у **GPU <8 GB**.
> **Зміна проти спеки:** LLM тепер **локальна (Ollama)**, не OpenRouter — бо приватність є
> ядром наративу (запис зустрічі не покидає машину). Embeddings + STT і так були локальні.

## Бюджет заліза

Ціль — **NVIDIA GPU <8 GB** (типово 6 GB: RTX 2060 / 3050 / 3060-laptop; або 4 GB: GTX 1650).
Ключова ідея — **не тримати STT і LLM на GPU одночасно**:

- **Ingestion (offline, batch):** WhisperX (int8) + pyannote — проганяємо один раз, ваги
  вивантажуємо. Тут не потрібна онлайн-LLM.
- **Online (serving):** Ollama тримає LLM на GPU; **embeddings + reranker — на CPU**
  (на query-time це один запит + rerank top-k, CPU встигає). Так 6 GB вистачає.

## Список моделей

| Роль | Модель (repo) | Розмір (диск) | Де крутиться | Чому |
|---|---|---|---|---|
| **STT** (Агент 1) | `Systran/faster-whisper-large-v3` | ~3 GB | GPU int8 (offline) | UA + 50 мов, $0; int8 ≈ 1.5–3 GB VRAM. На 4 GB → `medium`. |
| **Diarization** (різниця по голосу) | `pyannote/speaker-diarization-3.1` + `pyannote/segmentation-3.0` | ~60 MB | GPU/CPU (offline) | **gated** — прийняти умови на HF + токен. Meeting-grade ~0.12 DER. |
| **Embeddings** | `BAAI/bge-m3` | ~2.3 GB | **CPU** | Мультимовна, сильна на UA; dense+sparse в одній моделі. На 4 GB / слабкому CPU → `intfloat/multilingual-e5-base` (~1.1 GB). |
| **Reranker** | `BAAI/bge-reranker-v2-m3` | ~2.3 GB | **CPU** | Headline retrieval-fix (per MEMORY); мультимовний, парний UA/EN. |
| **LLM** (Агент 2 + агент) | Ollama `qwen2.5:7b-instruct` (q4_K_M) | ~4.7 GB | GPU | Гарний tool-calling (потрібен для ReAct) + пристойна UA. На 4 GB → `qwen2.5:3b-instruct` (~1.9 GB). |

**Чому Qwen2.5, а не Llama-3.1:** на цьому розмірі Qwen2.5-7B стабільніший у **function-calling**
(критично для propose-tools агента) і трохи краще тримає українську. Llama-3.1-8B — запасний варіант.

## Як завантажити

```powershell
# 1. HF-токен для gated pyannote: створи на huggingface.co/settings/tokens,
#    і ОБОВ'ЯЗКОВО прийми умови на сторінках обох моделей (інакше 401):
#      huggingface.co/pyannote/speaker-diarization-3.1
#      huggingface.co/pyannote/segmentation-3.0
$env:HF_TOKEN = "hf_xxx"

# 2. HF-ваги (Whisper, pyannote, embeddings, reranker)
python scripts/download_models.py

# 3. локальна LLM через Ollama (постав Ollama окремо: ollama.com)
ollama pull qwen2.5:7b-instruct      # або qwen2.5:3b-instruct на 4 GB GPU
```

## Корпус для датасетів / golden-set (YouTube)

Публічне відео = **без consent/PII-проблем** + реальні кілька спікерів для тесту діаризації.

1. Підбираємо 3–5 «зустріче-подібних» відео (стендапи, панелі, подкасти про проєкти),
   **UA за наявності**, інакше EN; ≥2 спікери; 10–40 хв.
2. `yt-dlp -x --audio-format wav <url>` → аудіо.
3. **WhisperX → транскрипт + діаризація → JSON** — це водночас перший реальний тест Агента 1.
4. Транскрипти = seed-корпус по «проєктах» (Qdrant namespace = project_id).
5. **Golden set вручну** (формат RAGAS `question / contexts / answer / ground_truth`):
   - 15–30 grounded Q&A (питання → відповідь + цитата timestamp/спікер);
   - 5–10 **abstention**-кейсів («не обговорювалось у цій зустрічі»).

> UA-WER на шумному аудіо реалістично 2–3× від clean-benchmark — **тестуємо на власних
> UA-семплах** перед фіксацією розміру Whisper (розд. 6 спеки).
