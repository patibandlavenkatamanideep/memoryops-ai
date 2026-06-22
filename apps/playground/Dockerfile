# MemoryOps AI — Playground (v0.12). Optional public demo surface.
#
# IMPORTANT: build from the REPOSITORY ROOT, because the playground drives the
# real governed pipeline from services/api in-process:
#
#     docker build -f apps/playground/Dockerfile -t memoryops-playground .
#     docker run -p 8501:8501 memoryops-playground
#
# No database, no secrets: MEMORYOPS_STORAGE defaults to the in-memory store and
# the LLM/embeddings default to deterministic offline stubs.
FROM python:3.12-slim

WORKDIR /app

# Backend (real governed pipeline) + the playground UI.
COPY services/api /app/services/api
COPY apps/playground /app/apps/playground

RUN pip install --no-cache-dir -r /app/apps/playground/requirements.txt

ENV MEMORYOPS_STORAGE=memory \
    PYTHONUNBUFFERED=1

EXPOSE 8501
WORKDIR /app/apps/playground

# $PORT is honored when set (e.g. Railway); defaults to 8501 locally.
CMD ["sh", "-c", "streamlit run streamlit_app.py --server.port ${PORT:-8501} --server.address 0.0.0.0 --server.headless true"]
