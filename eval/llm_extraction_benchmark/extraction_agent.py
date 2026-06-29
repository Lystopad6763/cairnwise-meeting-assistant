import openai
import anthropic
import requests
import json
import time
import os
from dotenv import load_dotenv


load_dotenv()

OPENAI_KEY = os.getenv("OPENAI_API_KEY")
CLAUDE_KEY = os.getenv("ANTHROPIC_API_KEY")

# ── ПРОМПТ ──
# Це інструкція яку отримує кожна модель
# Однаковий промпт для всіх — щоб порівняння було чесним
def build_prompt(text: str) -> str:
    return f"""Прочитай текст зустрічі та витягни структуровану інформацію.

Текст:
{text}

Поверни ТІЛЬКИ валідний JSON без markdown:
{{
  "summary": "одне речення що відбулось на зустрічі",
  "tasks": [
    {{"owner": "ім'я", "task": "що зробити", "deadline": "дата або null"}}
  ],
  "decisions": ["рішення 1", "рішення 2"]
}}"""

# ── OLLAMA (self-hosted) ──
# Викликає локальну модель через HTTP запит до Ollama сервера
# model — можна передати "llama2", "mistral", або "neural-chat"
def call_ollama(prompt: str, model: str) -> str:
    response = requests.post(
        'http://localhost:11434/api/generate',  # локальний Ollama сервер
        json={
            "model": model,
            "prompt": prompt,
            "stream": False  # чекаємо повну відповідь, не стрімінг
        },
        timeout=120  
    )
    return response.json()['response']

# ── OPENAI (cloud) ──
def call_openai(prompt: str) -> str:
    client = openai.OpenAI(api_key=OPENAI_KEY)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system", 
                "content": "You are a meeting parser. Return only valid JSON, no markdown, no extra text."
            },
            {
                "role": "user", 
                "content": prompt
            }
        ],
        response_format={"type": "json_object"}  
    )
    return response.choices[0].message.content

# ── CLAUDE (cloud) ──
def call_claude(prompt: str) -> str:
    client = anthropic.Anthropic(api_key=CLAUDE_KEY)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",  
        max_tokens=1024, 
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ]
    )
    return response.content[0].text

# ── MAIN ──
def extract_meeting_data(text: str, provider: str, model: str = None) -> dict:
    prompt = build_prompt(text)
    start = time.time()  # починаємо рахувати час

    # Вибираємо провайдера
    if provider == "ollama":
        raw = call_ollama(prompt, model)
    elif provider == "openai":
        raw = call_openai(prompt)
    elif provider == "claude":
        raw = call_claude(prompt)

    latency = round(time.time() - start, 2)  # скільки секунд пройшло

    # Рахуємо токени: слова × 1.3 (приблизна формула)
    input_tokens = round(len(prompt.split()) * 1.3)
    output_tokens = round(len(raw.split()) * 1.3)
    total_tokens = input_tokens + output_tokens

    # Вартість — тільки для хмарних моделей, Ollama безкоштовна
    if provider == "openai":
        cost = round((input_tokens / 1_000_000) * 0.15 + (output_tokens / 1_000_000) * 0.60, 6)
    elif provider == "claude":
        cost = round((input_tokens / 1_000_000) * 0.80 + (output_tokens / 1_000_000) * 4.00, 6)
    else:
        cost = 0  # Ollama — self-hosted, завжди $0

    # Парсимо JSON з відповіді
    # Локальні моделі часто додають текст до/після JSON — тому шукаємо { }
    try:
        start_idx = raw.find('{')   # знаходимо початок JSON
        end_idx = raw.rfind('}') + 1  # знаходимо кінець JSON
        json_str = raw[start_idx:end_idx]
        result = json.loads(json_str)
        result['_latency'] = latency
        result['_valid_json'] = True
        result['_tokens'] = total_tokens  # загальна кількість токенів
        result['_cost'] = cost            # вартість у доларах
        return result
    except:
        return {
            "_valid_json": False,
            "_latency": latency,
            "_tokens": total_tokens,
            "_cost": cost,
            "_raw": raw[:300]
        }

# ── MAIN ──
# Запускає всі 5 моделей на всіх 3 датасетах і зберігає результати
if __name__ == "__main__":

    # Шляхи — відносно цього файлу (працює з будь-якого CWD після перенесення в Cairnwise/eval).
    _HERE = os.path.dirname(os.path.abspath(__file__))
    _SAMPLES = os.path.join(_HERE, "samples")
    _RESULTS = os.path.join(_HERE, "results")
    os.makedirs(_RESULTS, exist_ok=True)

    # 3 датасети — простий, хаотичний, технічний
    datasets = {
        "simple":    os.path.join(_SAMPLES, "simple_meeting.txt"),
        "chaotic":   os.path.join(_SAMPLES, "chaotic_standup.txt"),
        "technical": os.path.join(_SAMPLES, "technical_sync.txt"),
    }

    # 6 моделей для порівняння — 4 локальні + 2 хмарні
    providers = [
        ("ollama", "phi3"),
        ("ollama", "neural-chat"),
        ("ollama", "llama2"),
        ("ollama", "mistral"),
        ("openai", None),
        ("claude", None),
    ]

    # Перебираємо всі датасети
    for dataset_name, filepath in datasets.items():
        with open(filepath, 'r', encoding='utf-8') as f:
            text = f.read()

        # Перебираємо всі моделі
        for provider, model in providers:
            label = f"{provider}/{model}" if model else provider
            print(f"\n{'='*50}")
            print(f"Dataset: {dataset_name} | Model: {label}")

            result = extract_meeting_data(text, provider, model)

            # Зберігаємо результат у results/
            out_path = os.path.join(_RESULTS, f"{dataset_name}_{provider}_{model or provider}.json")
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)

            print(json.dumps(result, indent=2, ensure_ascii=False))
