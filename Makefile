.DEFAULT_GOAL := help
PYTHON ?= python3
VENV   ?= .venv
BIN    := $(VENV)/bin

.PHONY: help install install-dev run test lint format check users seed secrets \
        docker-up docker-down docker-logs docker-user clean

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

$(BIN)/python:
	$(PYTHON) -m venv $(VENV)

install: $(BIN)/python  ## Create .venv and install runtime dependencies
	$(BIN)/pip install -r requirements.txt

install-dev: $(BIN)/python  ## Install runtime + development dependencies
	$(BIN)/pip install -r requirements-dev.txt

run:  ## Start the app on http://localhost:8501
	$(BIN)/python -m ai_database_analyst run

test:  ## Run the test suite with coverage
	$(BIN)/python -m pytest --cov=ai_database_analyst --cov-report=term-missing

lint:  ## Lint with ruff
	$(BIN)/ruff check .

format:  ## Auto-fix lint issues
	$(BIN)/ruff check --fix .

check:  ## Verify MySQL and Ollama connectivity
	$(BIN)/python -m ai_database_analyst check

users:  ## List sign-in accounts (add one: make users ARGS="add alice")
	$(BIN)/python -m ai_database_analyst users $(or $(ARGS),list)

seed:  ## Regenerate the demo dataset (docker/mysql-init/02_seed.sql)
	$(PYTHON) scripts/generate_seed_data.py

secrets:  ## Generate ./secrets/*.txt for Docker Compose
	$(PYTHON) scripts/init_secrets.py

docker-up: secrets  ## Build and start the full stack (app + MySQL + Ollama)
	docker compose up -d --build

docker-down:  ## Stop the stack (keeps data volumes)
	docker compose down

docker-logs:  ## Follow application logs
	docker compose logs -f app

docker-user:  ## Create a sign-in account in the container: make docker-user NAME=alice
	docker compose run --rm app python -m ai_database_analyst users add $(NAME)

clean:  ## Remove caches and build output
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov build dist *.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
