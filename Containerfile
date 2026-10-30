# Optional: runs the HTTP API (app/api.py) in a container — Alpine + ffmpeg +
# uvicorn. Not needed for the CLI. See README.md "Running in a container".
FROM python:3.14-alpine

RUN apk add --no-cache ffmpeg curl

WORKDIR /app

COPY Pipfile Pipfile.lock ./
RUN pip install --no-cache-dir pipenv && \
    pipenv requirements > requirements.txt && \
    pip install --no-cache-dir -r requirements.txt && \
    pip uninstall -y pipenv

COPY app ./app

EXPOSE 8000

# GET /healthz is unauthenticated — handy as a liveness check.
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
