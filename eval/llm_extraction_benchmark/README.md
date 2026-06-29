# LLM-бенчмарк витягання сутностей (вибір рушія резюме Cairnwise)

Це **бенчмарк вибору LLM** для задачі Агента-2 (структуроване витягання зі зустрічі: `summary` +
`tasks` + `decisions` у JSON). Саме він обґрунтовує, чому **локальний рушій Cairnwise — `neural-chat`**
(а cloud-опція — `gpt-4o-mini`/Claude). Перенесено з ДЗ-6 «LLM Engineering (API + Self-hosted)».

## Методика

- **Однаковий промпт** для всіх моделей (`build_prompt` в [extraction_agent.py](extraction_agent.py)) — чесне порівняння.
- **6 моделей:** 4 локальні через Ollama (`neural-chat`, `phi3`, `llama2`, `mistral`) + 2 хмарні (`gpt-4o-mini`, `claude-haiku-4-5`).
- **3 датасети** (UA-транскрипти) у [samples/](samples/): `simple` (структурований протокол, 3 завдання), `chaotic` (перебивання, розмиті дедлайни, 4), `technical` (терміни, мікросервіси, 5).
- **Метрики:** валідність JSON, частка знайдених завдань, галюцинації (вигадані завдання), токени, вартість, латентність. Зведення — [eval_results.csv](eval_results.csv); сирі виводи (18 шт.) — [results/](results/); повний розбір — [ANALYSIS.md](ANALYSIS.md).

## Підсумок — рейтинг

| Місце | Модель | Чим сподобалась | Що не так |
|---|---|---|---|
| 1 | **claude-haiku** | найшвидша (3с), 0 галюцинацій на simple/chaotic | вигадала рік на technical |
| 2 | **neural-chat** (локальна 🏆) | **єдина локальна зі 100% знайдених завдань (12/12), 0 галюцинацій, JSON 3/3** | повільна на technical (65с) |
| 3 | **gpt-4o-mini** | стабільний JSON через `json_object` | вигадує рік, дорожча за Claude |
| 4 | **mistral** | тримає українську | зламала JSON на chaotic |
| 5 | **llama2** | знаходить завдання на простому тексті | перекладає на англійську, ламає JSON на technical |
| 6 | **phi3** | найменша (2.2 GB) | найбільше галюцинацій, найгірша JSON-стабільність |

**Висновок для Cairnwise:** серед локальних `neural-chat` — єдина зі 100% точністю завдань і 0 галюцинацій
при $0/запит → обрана як `summary_model_local` / `entity_model`. Для якіснішого/швидшого хмарного
варіанту — `gpt-4o-mini` (`summary_model_cloud`), що пасує до privacy-тоглу (local/cloud) у застосунку.

> ⚠️ **Чесне обмеження:** бенчмарк — на 3 коротких семплах (демонстрація методики). На довгому
> реальному UA-транскрипті (m05, 493 сегменти) `neural-chat` подеколи відлунює few-shot приклад —
> див. [../results/phase4_e2e.md](../results/phase4_e2e.md). Тобто цей бенчмарк відбирає рушій, але
> повноцінний eval якості на довгих зустрічах — окремий трек (RAGAS).

## Як перезапустити

```bash
cp .env.example .env          # впиши OPENAI_API_KEY / ANTHROPIC_API_KEY для хмарних моделей
ollama pull neural-chat phi3 llama2 mistral
pip install openai anthropic requests python-dotenv
python extraction_agent.py    # шляхи самодостатні (відносно цього файлу) -> samples/ + results/
```
