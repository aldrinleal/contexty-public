.PHONY: install run api test lint fmt upload-cookies container-build container-run reset

CONTAINER ?= podman
# SELinux hosts (Fedora/RHEL) need VOLUME_OPTS=:Z for the bind mount.
VOLUME_OPTS ?=

install:
	pipenv install --dev

run:
	pipenv run python main.py $(ARGS)

api:
	pipenv run uvicorn app.api:app --reload --host 127.0.0.1 --port 8000

test:
	pipenv run pytest

lint:
	pipenv run black --check app tests main.py
	pipenv run isort --check-only app tests main.py
	pipenv run mypy app main.py

fmt:
	pipenv run black app tests main.py
	pipenv run isort app tests main.py

# Sends a cookies.txt to a running API's PUT /cookies (defaults to
# http://localhost:8000; needs CONTEXTY_API_TOKEN in the environment or --token).
# Usage: make upload-cookies ARGS="cookies.txt"
upload-cookies:
	scripts/upload-cookies.sh $(ARGS)

container-build:
	$(CONTAINER) build -t contexty:latest -f Containerfile .

# API on http://localhost:8000, output + sqlite db under ./data/.
container-run:
	mkdir -p data
	$(CONTAINER) run --rm -p 8000:8000 --env-file .env \
		-e CONTEXTY_OUTPUT_DIR=/data -e CONTEXTY_DB_PATH=/data/contexty.db \
		-v "$(CURDIR)/data:/data$(VOLUME_OPTS)" contexty:latest

# Wipes local state: generated data-*/ folders, the container's ./data/,
# and the sqlite dedup/history db.
reset:
	rm -rf data-*/ data/ contexty.db
