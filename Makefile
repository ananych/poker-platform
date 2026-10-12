.PHONY: up down api-install test lint migrate web

up:            ## start Postgres + API in Docker
	docker compose -f infra/docker-compose.yml up -d --build

down:
	docker compose -f infra/docker-compose.yml down

api-install:   ## local venv for the API
	cd services/api && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"

migrate:
	cd services/api && .venv/bin/alembic upgrade head

test:          ## unit + property (+ integration if POKER_TEST_DATABASE_URL set)
	cd services/api && .venv/bin/pytest -q

lint:
	cd services/api && .venv/bin/ruff check app tests migrations && .venv/bin/ruff format --check app tests migrations

web:
	cd apps/web && npm install && npm run dev
