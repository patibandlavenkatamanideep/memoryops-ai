# MemoryOps AI — Worker image.
# Build context is the repo root so the worker can install the API distribution.
#   docker build -f services/worker/Dockerfile .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/worker

COPY services/api /srv/api
COPY services/worker /srv/worker

# Install the API as a real distribution rather than dropping it on PYTHONPATH.
# The worker package then depends on it normally — no sys.path.insert(), no
# repository-layout coupling, and the same generated-from-pyproject dependency set
# as the API image (requirements-production.txt = postgres + provider SDKs).
RUN pip install --no-cache-dir \
      -r /srv/api/requirements.txt -r /srv/api/requirements-production.txt \
 && pip install --no-cache-dir --no-deps /srv/api \
 && pip install --no-cache-dir --no-deps /srv/worker

RUN useradd --create-home --uid 10002 worker
USER worker

# SIGTERM is handled cooperatively (app/workers/shutdown.py): the worker finishes
# the scope in flight, releases its lease, and exits 0. Exec form (no shell) so the
# signal reaches the process rather than a wrapping /bin/sh.
STOPSIGNAL SIGTERM

CMD ["memoryops-worker"]
