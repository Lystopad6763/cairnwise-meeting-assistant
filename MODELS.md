# Cairnwise — моделі та їх обґрунтування (fully-local, privacy-first)

> Рішення-документ: які моделі реально працюють у MVP, **чому саме ці**, як вони влазять у
> малий GPU, і **числа з бенчмарку** (cpWER / DER / WER), на яких ґрунтується вибір STT-стека.
> Сюди ж зводитимуться всі подальші заміри моделей (retrieval-eval, RAGAS).
>
> **Приватність — ядро вибору.** STT, діаризація та embeddings — локальні (аудіо й памʼять не
> покидають машину). LLM за замовчуванням теж локальна (Ollama); хмара (OpenAI) — лише опційно
> і лише для тексту резюме «непублічних» зустрічей.

---

## 1. Що реально стоїть у MVP

| Роль | Модель (repo / тег) | Розмір | Де крутиться | Стан |
|---|---|---|---|---|
| **STT** | WhisperX `small` (faster-whisper, int8) | ~0.5 GB VRAM | GPU (offline) | ✅ у потоці |
| **Діаризація** | `pyannote/speaker-diarization-3.1` + `pyannote/segmentation-3.0` | ~60 MB | GPU/CPU (offline) | ✅ у потоці |
| **Embeddings** | `BAAI/bge-m3` (dense 1024 + sparse) | ~2.3 GB | GPU/CPU (`auto`) | ✅ у потоці (ingest) |
| **LLM — резюме/сутності** | Ollama `neural-chat` (7B, Q4_0) | ~4.1 GB | GPU | ✅ прототип (Агент-2) |
| **LLM — хмара (опц.)** | OpenAI `gpt-4o-mini` | — | хмара | ✅ опц. (резюме непублічних) |
| **Reranker** | `BAAI/bge-reranker-v2-m3` | ~2.3 GB | CPU | 🗺️ ваги в кеші; підключення — Phase 5 |

Конфіг — у [app/config.py](app/config.py) (`whisper_model="small"`, `embed_model="BAAI/bge-m3"`,
`entity_model="neural-chat"`, `diarizer="pyannote/speaker-diarization-3.1"`); вибір — через `.env`, не код.

---

## 2. Бюджет заліза

Ціль — споживчий **NVIDIA GPU 4–8 GB**. Ключова ідея — **не тримати STT і LLM на GPU одночасно**:

- **Ingestion (offline, batch):** WhisperX `small` (int8) + pyannote проганяються один раз, ваги
  вивантажуються — онлайн-LLM тут не потрібна.
- **Online (serving):** Ollama тримає LLM на GPU; embeddings/reranker можна винести на CPU
  (на query-time це один embed + rerank top-k — CPU встигає). Так і **4 GB** вистачає.

> **Реальне обмеження, знайдене бенчмарком (не аспірація):** на 4 GB GPU `medium`/`large-v3`
> падають з OOM на стадії VAD — **влазить лише `small`**. Тому стек зафіксовано на `small`, а
> числа нижче — саме для нього.

---

## 3. Бенчмарк STT × діаризація — числа, на яких ґрунтується вибір

**Методика.** Згенеровано синтетичні україномовні «зустрічі» з ground-truth (текст + RTTM-розмітка
спікерів). Прогін по матриці `Whisper × діаризатор` на CUDA. Метрики:

- **cpWER ↓** — *concatenated minimum-permutation WER*: помилка тексту **в розрізі спікера**
  (хто-що-сказав). **Головна метрика** — карає і за ASR-помилки, і за плутанину спікерів.
- **WER ↓** — помилка лише ASR (текст без привʼязки до спікера).
- **DER ↓** — *Diarization Error Rate*: помилка лише діаризації (хто говорив, без тексту).
- **Purity / Coverage / F1 ↑** — precision / recall / F1 кластеризації спікерів.
- **spkΔ ↓** — помилка кількості визначених голосів. **RTF** — real-time factor (s_inference / s_audio).

> `s/mtg` та `RTF` — **чистий inference** (завантаження моделі виключено: у проді модель
> вантажиться раз на старті воркера, а не на кожну зустріч).

### 3.1. База (без глосарію)

| # | Whisper | Diarizer | cpWER ↓ | WER ↓ | DER ↓ | Purity ↑ | Cover ↑ | F1 ↑ | spkΔ ↓ | RTF |
|---|---|---|---|---|---|---|---|---|---|---|
| 🏆 | small | pa-3.1 | **0.252** | 0.252 | 0.084 | 0.993 | 0.922 | 0.956 | 0.0 | 0.157 |
|   | small | pa-community-1 | 0.252 | 0.252 | 0.084 | 0.993 | 0.922 | 0.956 | 0.0 | 0.157 |

### 3.2. + глосарій-prompt (тех-терміни, `use_glossary=True`)

| # | Whisper | Diarizer | cpWER ↓ | WER ↓ | DER ↓ | Purity ↑ | Cover ↑ | F1 ↑ | spkΔ ↓ | RTF |
|---|---|---|---|---|---|---|---|---|---|---|
| 🏆 | small | pa-3.1 | **0.246** | 0.245 | 0.077 | 0.994 | 0.928 | 0.960 | 0.0 | 0.180 |

**Висновок.** Глосарій-prompt (підказка моделі домен-термінів) дає **cpWER 0.252 → 0.246**
і **DER 0.084 → 0.077** — стабільне, хоч і помірне покращення, тож `use_glossary=True` за замовчуванням.
`pa-3.1` обрано як діаризатор (нарівні з community-1 за якістю, але офіційний, meeting-grade).

> **Чесне обмеження вибірки:** числа — на малому синтетичному наборі (демонстрація методики й
> заліза, а не продакшн-eval). UA-WER на реальному шумному аудіо реалістично 2–3× від цих значень;
> розширення набору — у дорожній карті. Сирі результати — у
> [eval/results/benchmark.md](eval/results/benchmark.md) та
> [eval/results/benchmark_glossary.md](eval/results/benchmark_glossary.md).

---

## 4. Чому саме ці моделі

- **WhisperX `small` (а не `large-v3`).** Не вибір якості, а **обмеження заліза**: на 4 GB GPU
  старші моделі падають з OOM. `small` дає cpWER ≈ 0.25 на UA — робочий baseline для MVP, і той
  самий код тривіально підніме розмір на жирнішому GPU (через `.env`).
- **pyannote-3.1** — інтегрована у WhisperX, дає «хто що сказав» (ядро продукту); gated (HF-токен +
  згода на сторінках обох моделей).
- **bge-m3** — мультимовна, **сильна на українській**; dense(1024)+sparse в одній моделі → гібридний
  retrieval (BM25-еквівалент через sparse) без окремого лексичного стора.
- **Ollama `neural-chat` (а не `qwen2.5`).** Для поточної задачі (грунтоване **витягання сутностей +
  резюме** з цитатами `[#N]`) `neural-chat` — **єдина локальна модель зі 100% знайдених завдань
  (12/12), 0 галюцинацій і валідним JSON 3/3** на бенчмарку витягання (розділ 7). Tool-calling-агент
  (ReAct) — окрема, пізніша фаза; під неї вибір LLM перегляне свіжий бенчмарк, і цей файл оновиться.
- **bge-reranker-v2-m3** — headline-фікс для retrieval-якості (мультимовний, парний UA/EN); ваги вже
  в кеші, підключення `/ask` — Phase 5.

---

## 5. Як завантажити

```powershell
# 1. HF-токен для gated pyannote: створи на huggingface.co/settings/tokens
#    і ОБОВ'ЯЗКОВО прийми умови на сторінках ОБОХ моделей (інакше 401):
#      huggingface.co/pyannote/speaker-diarization-3.1
#      huggingface.co/pyannote/segmentation-3.0
$env:HF_TOKEN = "hf_xxx"

# 2. HF-ваги (Whisper small, pyannote, bge-m3, bge-reranker)
python scripts/download_models.py --small

# 3. локальна LLM через Ollama (постав Ollama окремо: ollama.com)
ollama pull neural-chat
```

---

## 6. LLM-бенчмарк вибору рушія резюме (Агент-2)

Окремий **бенчмарк вибору LLM** для задачі витягання (`summary` + `tasks` + `decisions` у JSON):
6 моделей × 3 UA-датасети, однаковий промпт. Повний код + дані + сирі виводи + розбір перенесено в
[eval/llm_extraction_benchmark/](eval/llm_extraction_benchmark/README.md).

| Місце | Модель | JSON | Завдання | Галюц. | Вартість |
|---|---|---|---|---|---|
| 1 | claude-haiku-4-5 (cloud) | ✅ | високо | дрібні | ~$0.0001/запит |
| 2 | **neural-chat (локальна 🏆)** | **✅ 3/3** | **12/12 (100%)** | **0** | **$0** |
| 3 | gpt-4o-mini (cloud) | ✅ | високо | дрібні | ~$0.0001/запит |
| 4 | mistral | частково | добре | 0 | $0 |
| 5 | llama2 | частково | середньо | є | $0 |
| 6 | phi3 | ❌ | низько | найбільше | $0 |

**Чому це визначило вибір:** серед **локальних** `neural-chat` — єдина зі 100% точністю завдань і 0
галюцинацій → `summary_model_local` / `entity_model`. Хмарна опція `gpt-4o-mini` лягає в privacy-тогл
(local/cloud) у застосунку. Сирі метрики (валідність JSON / завдання / галюцинації / токени / латентність)
— [eval/llm_extraction_benchmark/eval_results.csv](eval/llm_extraction_benchmark/eval_results.csv).

## 7. Корпус для датасетів / golden-set

Синтетичні UA-зустрічі з ground-truth (текст + RTTM) дають **відтворюваний** бенчмарк без
consent/PII-проблем. Транскрипти водночас стають seed-корпусом по «проєктах»
(Qdrant namespace = `project_id`). Наступний крок eval — golden-set у форматі RAGAS
(`question / contexts / answer / ground_truth`): grounded Q&A + abstention-кейси
(«не обговорювалось у цій зустрічі»).
