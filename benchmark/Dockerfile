# Reproducible, offline runner for the public memory-governance benchmark.
#
#   docker compose --profile benchmark run --rm benchmark
#
# Runs `benchmark/run_benchmark.py` against the deterministic in-memory stub stack
# (no DB, no Redis, no API keys). Exits non-zero if a critical suite is not perfect.
FROM python:3.12-slim

WORKDIR /repo

# Only the API runtime deps are needed to score the eval harness.
COPY services/api/requirements.txt services/api/requirements.txt
RUN pip install --no-cache-dir -r services/api/requirements.txt

# The benchmark reuses the eval harness (services/api) and the cases (evals/).
COPY . .

ENV MEMORYOPS_STORAGE=memory \
    PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "benchmark/run_benchmark.py"]
