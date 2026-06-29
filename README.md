# Cairnwise — локальний agentic-RAG асистент зустрічей

> **Записує зустріч → розрізняє, хто що сказав → будує памʼять проєкту → готує резюме й пропонує дії (Jira/Slack) за людським підтвердженням.** Приватність за замовчуванням: запис, транскрипція й діаризація — повністю локальні.

Cairnwise перетворює живу зустріч на структуроване знання: діаризований транскрипт («хто що сказав» за голосом), per-project памʼять із семантичним пошуком та цитатами, і **propose-then-commit** агента, який нічого не виконує без апруву людини.

---

## 🎯 Проблема, яку вирішуємо

Після кожної зустрічі команда втрачає до 90% контексту: рішення, домовленості й завдання губляться в памʼяті учасників або в сирому записі, який ніхто не передивляється. Існуючі інструменти (Otter, Fireflies, Fathom) — **хмарні**: ваші внутрішні дзвінки їдуть на чужі сервери. Для приватних/чутливих зустрічей це блокер.

**Cairnwise** закриває обидві проблеми:
1. **Памʼять зустрічей** — кожна зустріч інжеститься в ізольовану памʼять свого проєкту; можна спитати «що вирішили по вебхуках?» і отримати відповідь із цитатами на конкретні репліки.
2. **Приватність** — STT, діаризація, embeddings і (за вибором) LLM працюють **локально**. Аудіо не покидає машину. Хмара (OpenAI) — лише опційно й лише для тексту резюме «непублічних» зустрічей.

---

## ✨ Що вміє (поточний MVP)

| Можливість | Стан |
|---|---|
| Проєкти як first-class сутність (ізоляція памʼяті) | ✅ |
| Завантаження зустрічі (mp4/wav/…) + **consent-гейт** (legal) | ✅ |
| **Запис «живої» зустрічі у браузері**: мікрофон + системний звук (інша сторона дзвінка) → webm, локально | ✅ |
| **STT + діаризація** у потоці (черга → host-GPU воркер) → діаризований JSON `[{speaker,start,end,text}]` | ✅ |
| **Підписи спікерів** (relabel): «Speaker N» → імʼя+роль; застосовуються в транскрипті й резюме | ✅ |
| Веб-інтерфейс (React SPA): проєкти, upload/запис, live-статус, перегляд транскрипту | ✅ |
| **Per-project RAG-памʼять**: чанки → bge-m3 → Qdrant (namespace=project_id) + сутності (action items, рішення) → Postgres | ✅ |
| **Резюме (Агент-2)**: grounded + цитати `[#N]` + confidence → HITL-гейт; рушій **local (Ollama) / cloud (OpenAI)** за приватністю | ✅ |
| Гібридний retrieval (BM25+dense) + reranker + `/ask` з абстенцією | 🚧 наступне |
| Агент (ReAct + tools, LangGraph) + черга апрувів (Jira/Slack) | 🚧 |

Архітектурні деталі — у [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md); інженерні рішення й граблі — у [docs/CHALLENGES.md](docs/CHALLENGES.md); порівняння моделей — у [MODELS.md](MODELS.md); план далі — у [docs/ROADMAP.md](docs/ROADMAP.md).

---

## 🏗️ Архітектура (огляд)

```
            ┌─────────────────────────────────────────────────────────────┐
            │  React SPA (Vite, :5173)  — проєкти, upload, транскрипт      │
            └───────────────────────────────┬─────────────────────────────┘
                                             │ REST (CORS)
            ┌────────────────────────────────▼────────────────────────────┐
            │  FastAPI (контейнер, :8000) — CPU-only, БЕЗ torch            │
            │  /health·projects·meetings·transcript·relabel·summary·memory │
            └──────┬───────────────────────┬──────────────────────┬───────┘
                   │ enqueue (Redis)        │ SQLAlchemy           │ qdrant-client
            ┌──────▼──────┐         ┌───────▼────────┐      ┌──────▼──────┐
            │   Redis     │         │   Postgres     │      │   Qdrant    │
            │ (черги)     │         │ meetings,      │      │ памʼять     │
            └──────┬──────┘         │ transcripts,   │      │ (namespace= │
                   │                │ action_items…  │      │ project_id) │
       ┌───────────┴───────────┐    └────────────────┘      └─────────────┘
       │  HOST .venv (GPU)     │      ▲                          ▲
       │  ── STT-воркер ───────┼──────┘ діаризований транскрипт  │
       │     whisperX + pyannote                                 │
       │  ── Ingest (ingest.py)┼────── чанки + сутності ─────────┘
       │     bge-m3 + Ollama                                      
       │  ── Summary-воркер ───┼────── grounded summary + HITL (Ollama / OpenAI)
       └────────────────────────────────────────────────────────┘
```

**Ключове архітектурне рішення:** важкі ML-моделі (torch, whisperX, bge-m3) **не їдуть в образ API** (тримаємо його ~250 МБ). Натомість API лише ставить задачі в Redis-черги, а їх виконують **host-воркери** з доступом до GPU. Це той самий патерн, що й у проді: модель вантажиться раз на старті воркера, а не на кожен запит.

Деталі — [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## 🧰 Стек і чому саме він

| Шар | Вибір | Чому |
|---|---|---|
| **STT** | WhisperX (`small`, int8) | faster-whisper + word-alignment; на 4GB GPU влазить лише `small` (бенчмарк треку D) |
| **Діаризація** | pyannote-3.1 | інтегрована у WhisperX; дає «хто що сказав» — ядро продукту |
| **Embeddings** | BAAI/bge-m3 (локально) | мультимовна, сильна **українська**; dense(1024)+sparse в одному forward → гібрид без окремого BM25-стора |
| **Reranker** | bge-reranker-v2-m3 | якість retrieval на тех-домені |
| **Vector DB** | Qdrant | named+sparse vectors, payload-фільтр для namespace-ізоляції |
| **LLM (локальна)** | Ollama (`neural-chat`) | приватність + $0; за бенчмарком ДЗ-6 — найкраща локальна на extraction |
| **LLM (хмарна, опц.)** | OpenAI `gpt-4o-mini` | краще резюме для «непублічних» зустрічей (вибір за приватністю) |
| **Backend** | FastAPI + SQLAlchemy 2.0 + Pydantic | стандарт ринку; async, типобезпека |
| **Черги/воркери** | Redis | проста надійна черга (LPUSH/BRPOP), переживає рестарт API |
| **БД** | Postgres | сутності + майбутні approvals/Text-to-SQL |
| **Фронтенд** | React 18 + Vite + TS + Tailwind + react-query | live-polling статусу, типи 1:1 з API |
| **Деплой** | Docker multi-stage + compose | відтворюваність (заняття 13) |

**Наскрізні принципи:** *local-first* (приватність), *pluggable* (STT/LLM за конфігом), *propose-then-commit* (агент ніколи не діє без апруву).

---

## 🚀 Запуск локально

### Передумови
- **Docker Desktop** (запущений)
- **Python 3.11** + venv (для host-воркерів з GPU; NVIDIA GPU бажано)
- **Node 20+** (фронтенд)
- **HuggingFace токен** (для gated-моделей pyannote) — [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) + прийняти умови на сторінках pyannote-3.1 / segmentation-3.0
- *(опц.)* **Ollama** для локального резюме · *(опц.)* **OpenAI ключ** для хмарного режиму

### 1. Конфіг
```bash
cp .env.example .env
# впиши HF_TOKEN (обовʼязково для діаризації); OPENAI_API_KEY — опційно
```

### 2. Інфраструктура + API (контейнери)
```bash
docker compose up -d --build
curl http://localhost:8000/health        # має бути {"status":"ok", ...}
```
> Порти зміщені, щоб не конфліктувати з іншими сервісами: API `8000`, Postgres `5433`, Redis `6380`, Qdrant `6543`.

### 3. Фронтенд
```bash
cd frontend && npm install && npm run dev   # → http://localhost:5173
```

### 4. Host-воркери (GPU/моделі) — **мають працювати, інакше задачі застрягають у черзі**
```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements-ingest.txt
python scripts/download_models.py --small        # bge-m3, pyannote, whisper
ollama pull neural-chat                           # локальний рушій резюме

# два довгоживучі процеси (кожен у своєму терміналі):
python scripts/worker.py            # STT: черга → діаризований транскрипт
python scripts/summary_worker.py    # резюме: черга → grounded summary + HITL
```
> ⚠️ Транскрипція й резюме виконуються на host-воркерах (API лише ставить у Redis-чергу). Якщо
> воркер не запущено, зустріч лишається «У черзі» без дій.

### 5. (опц.) Інжест у per-project памʼять
```bash
python scripts/ingest.py --meeting <id>     # або --project <slug> / --all
python scripts/check_isolation.py           # довести namespace-ізоляцію (PASS)
```

Зручні скорочення — у [Makefile](Makefile) (`make up`, `make front`, `make worker`).

---

## 📁 Структура проєкту

```
Cairnwise/
├── app/                  # FastAPI (CPU-only, без torch)
│   ├── main.py           #   ендпоінти: health, projects, meetings, transcript, memory
│   ├── models.py         #   ORM: Project, Meeting, Transcript, ActionItem, Decision
│   ├── db.py             #   SQLAlchemy + легкі ідемпотентні міграції
│   ├── jobs.py           #   Redis-черги (transcribe / ingest)
│   ├── config.py         #   pydantic-settings (.env)
│   └── rag/              #   per-project памʼять (torch-free поверхня + host-only embedder)
│       ├── chunker.py    #     діаризовані сегменти → чанки (speaker/gap-aware)
│       ├── embedder.py   #     bge-m3 (HOST ONLY: torch + FlagEmbedding)
│       ├── vector_store.py #   Qdrant: namespace-ізоляція, hybrid upsert/search
│       ├── entities.py   #     action items / рішення (grounded, цитати)
│       └── service.py    #     ingest_meeting() — ідемпотентна оркестрація
├── scripts/              # host-воркери + інструменти
│   ├── worker.py         #   STT-воркер (whisperX + pyannote)
│   ├── ingest_worker.py  #   інжест-воркер (bge-m3 → Qdrant)
│   ├── ingest.py         #   CLI інжестії
│   ├── summarize.py      #   прототип резюме (grounding+citations+HITL)
│   └── benchmark.py      #   STT/diar бенчмарк (cpWER/DER/WER)
├── frontend/             # React + Vite SPA
├── docker-compose.yml    # Postgres + Redis + Qdrant + API
├── Dockerfile            # multi-stage (builder → slim runtime, non-root)
└── docs/                 # ARCHITECTURE.md, CHALLENGES.md
```

---

## 🔬 Дослідження та інженерні рішення

- **Вибір STT-стека — числами.** Згенерували 30 синтетичних україномовних зустрічей з ground-truth і прогнали бенчмарк (cpWER/DER/WER/Purity/Coverage/F1) по матриці `Whisper × діаризатор`. Результат і обмеження заліза (4GB GPU → лише `small`) задокументовано.
- **Проблеми й як вирішували** (ffmpeg на PATH, затінення портів нативними сервісами, OOM на 4GB, named-volume vs bind-mount, нативний enum-міграція, echo-баг у промпті) — окремий розбір у [docs/CHALLENGES.md](docs/CHALLENGES.md). Це найчесніша частина: реальні граблі реальної локальної системи.

---

## 📌 Статус

MVP працює наскрізно: `docker compose up` піднімає стек, фронтенд показує проєкти й транскрипти, STT-конвеєр перетворює завантажену зустріч на діаризований транскрипт, інжест-шар будує per-project памʼять. У роботі — гібридний retrieval + агент + черга апрувів.

Детальний зріз (що перевірено / реалізовано / у дорожній карті) — [docs/STATUS.md](docs/STATUS.md).

> Капстоун-проєкт. Архітектура свідомо закладена під продуктову еволюцію (pluggable STT/LLM, HITL, observability), а не лише під демо.
