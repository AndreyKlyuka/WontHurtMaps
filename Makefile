.PHONY: help dev up down build logs ps db-only

help:
	@echo "Available targets:"
	@echo "  make dev      — first-time setup: creates .env if missing, then starts all services"
	@echo "  make up       — start all services (requires .env)"
	@echo "  make down     — stop all services"
	@echo "  make build    — rebuild Docker images without cache"
	@echo "  make logs     — follow logs from all services"
	@echo "  make ps       — show running services"
	@echo "  make db-only  — start only the database (for local backend development)"

dev:
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo ""; \
		echo "  .env created from .env.example"; \
		echo "  ACTION REQUIRED: open .env and set real values for:"; \
		echo "    TELEGRAM_API_ID, TELEGRAM_API_HASH, JWT_SECRET"; \
		echo ""; \
		exit 1; \
	fi
	docker compose up

up:
	docker compose up

down:
	docker compose down

build:
	docker compose build --no-cache

logs:
	docker compose logs -f

ps:
	docker compose ps

db-only:
	docker compose up db
