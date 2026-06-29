# Phase 4 — наскрізний e2e-прогін інжесту (acme / m05)

Доказ, що конвеєр **Transcript → per-project RAG-памʼять** працює наскрізь на реальній зустрічі.

## Вхід
- Зустріч: `7b94f1a5-da33-4161-babb-ff77b58aa5cb` — "Daily Standup (m05)", проєкт **acme** (`project_id=f8ffed98…`).
- Транскрипт: **493 діаризованих сегменти**, 4 спікери, мова uk.

## Команда
```powershell
.\.venv\Scripts\python scripts\ingest.py --meeting 7b94f1a5-da33-4161-babb-ff77b58aa5cb
```

## Результат — ✅ OK (474 с)
| Крок | Вихід |
|---|---|
| Chunking (speaker/gap-aware) | 493 сегменти → **48 чанків** (~1093 chars/chunk) |
| Embedding (bge-m3, dense+sparse, GPU) | 48 чанків, ~7 с inference |
| Qdrant upsert (namespace=`project_id`) | **48 точок** у `cairnwise_memory` (count(acme)=48) |
| Витягання сутностей (neural-chat) | **3 action-items + 10 decisions**, confidence **0.82** |
| Postgres | `meetings.status = ingested`; рядки в `action_items` / `decisions` з `citations [#N]` |

Ідемпотентність перевірено: повторний запуск перезаписує ті самі 48 точок (детермінований `uuid5`-id), не дублює.

## Знайдене обмеження (задокументовано)
- **VRAM co-residency на 4 GB:** перший прогін упав з `HTTPError 500` — bge-m3 (резидентний на GPU) + neural-chat не вміщалися разом. Фікс: стартувати з чистого GPU або embed на CPU. Деталі — [docs/CHALLENGES.md](../../docs/CHALLENGES.md) п.9.

## Чесний борг по якості витягання
Конвеєр коректний, але **якість сутностей neural-chat на довгому UA-транскрипті слабка**: частина значень відлунює few-shot приклад промпта (напр. «Перенести реліз на тиждень» [12]), є галюцинації («бюктріади»). Напрями: ширший `num_ctx` / стиснення транскрипту до релевантних вікон перед extraction / сильніша локальна модель / few-shot без доменних слів. Це окремий трек якості (RAGAS-eval), не блокер конвеєра.
