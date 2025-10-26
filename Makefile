PYTHON ?= python
PIP ?= pip

.PHONY: dev up down fmt lint type test migrate rev

dev:
$(PIP) install -r requirements-dev.txt

up:
docker compose up --build -d

down:
docker compose down

fmt:
ruff check --fix .
black .

lint:
ruff check .
bandit -r app

type:
mypy app/core app/db app/models

test:
pytest

migrate:
alembic upgrade head

rev:
alembic revision -m "$(message)" --autogenerate
