# Архітектура Cairnwise — як це працює

## Наскрізний потік (від запису до памʼяті)

```
1. CAPTURE     Користувач завантажує/записує зустріч → API (consent-гейт) → файл у сховище
                  → status=uploaded → LPUSH cairnwise:transcribe
2. STT+DIAR    STT-воркер (host, GPU): BRPOP → whisperX (small, int8) транскрибує
                  → pyannote-3.1 діаризує («хто що сказав») → align timestamps
                  → Transcript [{speaker,start,end,text}] у Postgres → status=transcribed
                  → LPUSH cairnwise:ingest
3. INGEST      Ingest (host, scripts/ingest.py): chunker (speaker/gap-aware) → bge-m3 embed
                  → Qdrant (namespace=project_id) + entities (action items/рішення) → Postgres
                  → status=ingested
3b. RELABEL    POST /meetings/{id}/relabel → «Speaker N» → {імʼя, роль} у transcripts.speaker_labels
                  (недеструктивно; застосовується і в показі, і в резюме)
3c. SUMMARIZE  POST /meetings/{id}/summarize → LPUSH cairnwise:summarize → Summary-воркер (host):
                  relabel-імена → grounded summary + дії/рішення/ризики з [#N] + confidence→HITL
                  → summaries (status ready/failed). Рушій: local (Ollama) / cloud (OpenAI) за приватністю
4. RETRIEVE    /ask → hybrid (BM25+dense) → reranker → LLM з grounding+citations+abstention  [🚧]
5. ACT         Агент пропонує дії (Jira/Slack) → черга апрувів → людина апрувить → executor  [🚧]
```

## Компоненти й межі відповідальності

### API (FastAPI, контейнер, CPU-only)
Тонкий оркестратор. **Не містить torch.** Уміє: CRUD проєктів/зустрічей, приймати upload (з consent-гейтом), віддавати транскрипт, рахувати статистику памʼяті, і **ставити задачі в Redis-черги**. Важку ML-роботу не виконує сам — делегує воркерам. Образ ~250 МБ (multi-stage Dockerfile, non-root).

### Host-воркери (`.venv`, GPU)
Довгоживучі процеси, що споживають Redis-черги (запускаються в окремих терміналах):
- **STT-воркер** (`scripts/worker.py`) — whisperX + pyannote, черга `cairnwise:transcribe`. Завантажує моделі раз на старті.
- **Summary-воркер** (`scripts/summary_worker.py`) — черга `cairnwise:summarize`; relabel-імена → grounded summary через Ollama (local) або OpenAI (cloud).
- **Ingest** (`scripts/ingest.py`) — bge-m3 embedder + chunker + запис у Qdrant/Postgres. Наразі CLI/one-shot (`--meeting/--project/--all`), не довгоживуча черга.

Чому host, а не контейнер: GPU живе на хості; torch/whisperX/bge-m3 надто важкі для образу API; локальна LLM ходить у host-Ollama (:11434), якого CPU-only контейнер не дістає; ці кроки довгі — їх не можна тримати в HTTP-запиті. **Якщо воркер не запущено — задача лишається у черзі без дій.**

### Сховища
- **Postgres** — структуровані сутності: `projects`, `meetings`, `transcripts` (JSONB-сегменти), `action_items`, `decisions`. Майбутнє: `approvals`, Text-to-SQL.
- **Qdrant** — векторна памʼять. Один колекшн `cairnwise_memory` з **payload-фільтром `project_id`** → ізоляція проєктів («namespace»). Named vectors: dense (bge-m3, 1024) + sparse (bge-m3 lexical) для гібриду.
- **Redis** — черги задач (`cairnwise:transcribe`, `cairnwise:ingest`). Простий список (LPUSH/BRPOP) — переживає рестарт API, не блокує запит.

## Per-project памʼять (диференціатор)

Кожна зустріч інжеститься **в namespace свого проєкту**. Запит у проєкті `acme` ніколи не бачить дані `nimbus` — ізоляція форсується payload-фільтром `project_id` на КОЖНОМУ upsert і search. Метадані чанка `{project_id, meeting_id, speaker, start, end, date, seg_start, seg_end}` дають **зворотнє посилання на span транскрипту** для цитат.

**Chunking** — speaker/gap-aware: суміжні репліки одного спікера зливаються в turn; turns пакуються у вікно за бюджетом символів; пауза > N секунд = межа теми (новий чанк); сусідні вікна перекриваються, щоб факт на межі був знайдений з обох боків.

## Torch-free шов (ключове рішення для масштабу)

```
app/rag/
├── schema.py        torch-FREE  (константи, dataclasses)
├── chunker.py       torch-FREE  (чистий python, юніт-тестований)
├── vector_store.py  torch-FREE  (qdrant-client; query-вектор передається ЗВНІ)
├── entities.py      torch-FREE  (Ollama через HTTP)
├── embedder.py      HOST ONLY   (torch + FlagEmbedding; імпортується ЛИШЕ ліниво)
└── service.py       оркестрація (embedder будує ліниво)
```
Завдяки цьому read-path Фази 5/6 (retrieval/agent) зможе жити в контейнері API, а embed query-вектора робить host-воркер і передає всередину.

## Наскрізні принципи

1. **Local-first (приватність).** STT/діаризація/embeddings локальні; аудіо не покидає машину. Хмара (OpenAI) — лише опційний текст резюме «непублічних» зустрічей; вибір — за прапором приватності зустрічі.
2. **Pluggable.** STT-модель, діаризатор, embedder, LLM — за конфігом (`.env`), не за кодом.
3. **Propose-then-commit (HITL).** Агент НІКОЛИ не виконує side-effect напряму. Дія персиститься як `proposed`; ідемпотентний executor виконує лише після апруву людини.
4. **Ідемпотентність.** Інжестія re-runnable: delete-then-write в обох сховищах + детермінований `uuid5` id точок → mid-crash self-heal.
5. **Граданий артефакт рано.** `docker compose up` піднімає робочий стек з першої фази.

## Модель даних (Postgres)

```
projects (id, slug, name, description, created_at)
  └─ meetings (id, project_id→, title, stored_path, consent, status, error, created_at)
       ├─ transcripts (meeting_id→ unique, segments JSONB, speaker_labels JSONB, model, diarizer, num_speakers, duration_s)
       ├─ action_items (project_id→, meeting_id→, owner, task, deadline, citations JSONB, confidence)
       ├─ decisions (project_id→, meeting_id→, decision, citations JSONB, confidence)
       └─ summaries (meeting_id→ unique, project_id→, summary, action_items/decisions/risks JSONB, confidence, engine, status, error)
```
`status`: `uploaded → transcribing → transcribed → ingesting → ingested` (або `failed` із `error`).
