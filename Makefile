.PHONY: setup run test docker-build docker-up docker-down clean \
        synthetic-data db-schema readonly-login ingest-structured search-index ingest-notes ingest-all

setup:
	python3 -m venv .venv
	. .venv/bin/activate && pip install --no-cache-dir -r requirements.txt
	test -f .env || cp .env.example .env
	@echo "Done. Activate with 'source .venv/bin/activate', edit .env, then 'make run'."

run:
	streamlit run app.py

test:
	pytest -v

docker-build:
	docker compose build

docker-up:
	docker compose up

docker-down:
	docker compose down

clean:
	rm -rf .venv .pytest_cache
	find . -name "__pycache__" -type d -not -path "./.venv/*" -exec rm -rf {} +

# --- Data pipeline ---

synthetic-data:
	python scripts/generate_synthetic_data.py --n-patients 500 --out-dir data/synthetic

db-schema:
	python scripts/apply_sql_file.py sql/schema.sql

readonly-login:
	python scripts/create_readonly_login.py

ingest-structured:
	python scripts/ingest_structured.py --source data/synthetic

search-index:
	python scripts/create_search_index.py

ingest-notes:
	python scripts/ingest_notes.py --source data/synthetic

ingest-all: db-schema ingest-structured search-index ingest-notes
