# Cairnwise — зручні команди. На Windows без `make` запускай праву колонку вручну.
.PHONY: build up down logs health dev worker front front-install

build:         ## зібрати образ API (multi-stage)
	docker compose build

up:            ## підняти весь стек (API + Postgres + Redis + Qdrant), зібравши образ
	docker compose up --build -d

down:          ## зупинити стек (дані лишаються у volumes)
	docker compose down

logs:          ## логи API
	docker compose logs -f api

health:        ## перевірити /health
	curl -s http://localhost:8000/health

dev:           ## локальний запуск API без контейнера (інфра має бути піднята: make up)
	uvicorn app.main:app --reload --port 8000

worker:        ## STT-воркер на хості (GPU): Redis-черга -> транскрипт у БД (Фаза 2-3)
	.venv/Scripts/python scripts/worker.py

front-install: ## встановити залежності фронтенду (один раз)
	cd frontend && npm install

front:         ## фронтенд dev-сервер (Vite, :5173); API має бути піднятий (make up)
	cd frontend && npm run dev
