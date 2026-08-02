# MemoryOps AI — API image. Runs as a non-root user; deps pinned exactly.
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install runtime + production deps first for layer caching. All requirements files
# are generated from pyproject.toml (scripts/sync_dependencies.py) and drift-checked
# in CI, so this image and `pip install .` resolve the same set.
#
# requirements-production.txt carries Postgres *and* the openai/anthropic/gemini SDKs:
# the provider adapters import their SDK lazily, so an image without them silently
# degraded MEMORYOPS_LLM_PROVIDER=openai to the stub. Under MEMORYOPS_PROFILE=production
# that combination is now a startup error, so the image must be able to honour it.
COPY requirements.txt requirements-production.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-production.txt

COPY . .

# Run as non-root.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
