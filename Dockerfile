# Cairnwise API — multi-stage (заняття 13). Builder ставить залежності, slim-runtime лише запускає.
# CPU-only ОРКЕСТРАТОР: моделей у образі НЕМАЄ (STT/embeddings — окремо, §7 «volume/download»).
# Очікуваний розмір ~250 MB. ВАЖЛИВО: коментарі лише на ОКРЕМИХ рядках (Docker не має inline-# для COPY).

# --- Stage 1: builder (повний інструментарій, у фінал не потрапляє) ---
FROM python:3.11-slim AS builder
WORKDIR /app
RUN pip install --no-cache-dir --upgrade pip
COPY requirements.txt .
# депи в /deps; --no-cache-dir щоб не тягнути ~/.cache/pip у layer
RUN pip install --no-cache-dir --target=/deps -r requirements.txt

# --- Stage 2: runtime (чистий slim, без compiler/apt-кешу) ---
FROM python:3.11-slim AS runtime
# non-root (best practice) + тека сховища завантажень із власником app
# (named volume на /data/uploads успадкує цього власника при першому монтуванні)
RUN useradd --create-home --uid 1000 app \
 && mkdir -p /data/uploads \
 && chown -R app:app /data
WORKDIR /app
# лише встановлені пакети
COPY --from=builder /deps /deps
# код ОСТАННІМ — layer cache
COPY --chown=app:app app/ ./app/
ENV PYTHONPATH=/deps \
    PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
# Healthcheck = HTTP 200 від /health (моделі немає -> «слухає порт» = «готовий»; стан Postgres/
# Redis/Qdrant видно в ТІЛІ /health). start-period — grace на старт.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health',timeout=3).status==200 else 1)"
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
