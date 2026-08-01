.DEFAULT_GOAL := help
SHELL := /bin/bash

VENV    := .venv
PY      := $(VENV)/bin/python
PIP     := $(VENV)/bin/pip
MYSQL_CONTAINER ?= agentlog-mysql
MYSQL_ROOT_PASSWORD ?= devroot
MYSQL_DATABASE ?= agentlog
SEED_RUNS ?= 200
SEED_DAYS ?= 7
SEED ?= 42

.PHONY: help up down migrate seed dev api ui test shell reset logs install nuke

help: ## Show this help
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Create the venv and install backend + frontend deps
	@test -d $(VENV) || python3 -m venv $(VENV)
	@$(PIP) install -q --upgrade pip
	@$(PIP) install -q -r backend/requirements.txt
	@cd frontend && npm install --silent
	@echo "dependencies installed"

up: ## Start MySQL in podman (starts the podman machine if needed)
	@podman machine inspect --format '{{.State}}' 2>/dev/null | grep -q running \
	  || podman machine start
	@./infra/podman/run-mysql.sh

down: ## Stop the MySQL container
	@podman stop $(MYSQL_CONTAINER) 2>/dev/null || true

migrate: ## Apply db/migrations/*.sql
	@./db/migrate.sh

seed: ## Load demo runs through the API (needs `make api` running)
	@cd backend && ../$(PY) -m app.seed.generate \
	  --seed $(SEED) --runs $(SEED_RUNS) --days $(SEED_DAYS)

api: ## Run the FastAPI backend on :8000
	@cd backend && ../$(PY) -m uvicorn app.main:app --reload --port 8000

ui: ## Run the Vite dev server on :5173
	@cd frontend && npm run dev

dev: ## Run backend and frontend together
	@trap 'kill 0' EXIT; \
	( cd backend && ../$(PY) -m uvicorn app.main:app --reload --port 8000 ) & \
	( cd frontend && npm run dev ) & \
	wait

test: ## Run the backend test suite (uses a scratch agentlog_test database)
	@cd backend && ../$(PY) -m pytest tests/ -q

smoke: ## Render every dashboard page in Chrome and fail on console errors
	@cd frontend && node smoke.mjs

shell: ## Open a mysql shell in the container
	@podman exec -it $(MYSQL_CONTAINER) \
	  mysql -uroot -p$(MYSQL_ROOT_PASSWORD) $(MYSQL_DATABASE)

logs: ## Tail the MySQL container logs
	@podman logs -f $(MYSQL_CONTAINER)

reset: ## Empty every table (keeps the schema)
	@podman exec -i $(MYSQL_CONTAINER) mysql -uroot -p$(MYSQL_ROOT_PASSWORD) \
	  $(MYSQL_DATABASE) -e "SET FOREIGN_KEY_CHECKS=0; \
	    TRUNCATE tracked_fields; TRUNCATE logs; TRUNCATE runs; TRUNCATE field_defs; \
	    SET FOREIGN_KEY_CHECKS=1;" 2>/dev/null
	@echo "all tables emptied"

nuke: ## Remove the container and its data volume
	@podman rm -f $(MYSQL_CONTAINER) 2>/dev/null || true
	@podman volume rm agentlog-data 2>/dev/null || true
	@echo "container and volume removed"
