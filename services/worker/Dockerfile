# MemoryOps AI — Worker image.
# Build context is the repo root so the worker can include the API package.
#   docker build -f services/worker/Dockerfile .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/srv/api

WORKDIR /srv/worker

COPY services/api /srv/api
COPY services/worker /srv/worker

# Worker shares the API's dependency set (+ postgres extras).
RUN pip install --no-cache-dir \
    -r /srv/api/requirements.txt -r /srv/api/requirements-postgres.txt

RUN useradd --create-home --uid 10002 worker
USER worker

CMD ["python", "main.py"]
