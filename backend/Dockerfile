# One image: the built frontend, the FastAPI backend, and the ontology feature (compiler + gates +
# declarations). The ontology COMPILER is not a separate service and not a second virtualenv — that is
# the point of the M1/M2 work: `rdflib` is in this image's dependencies, and the profiles live inside
# `backend/features/ontology/profiles/`.
#
# Build:   docker build -t langconfig -f backend/Dockerfile .
# Run:     docker run -p 8765:8765 --env-file deploy/.env langconfig

# ── stage 1: the frontend ────────────────────────────────────────────────────
FROM node:20-slim AS web
WORKDIR /app
# dependency-only layer first: a source edit does not re-install node_modules
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# ── stage 2: the backend ─────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    LANG=C.UTF-8

# graphviz powers the generated graph page (`dot -Tplain`); the rest is Python
RUN apt-get update && apt-get install -y --no-install-recommends \
        graphviz curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
# psycopg[binary] ships the driver; rdflib/psycopg2 in requirements are what the ontology compiler needs
RUN pip install --upgrade pip && pip install -r backend/requirements.txt \
    && pip install rdflib>=7.6.0

COPY backend backend
# the frontend the backend serves: `main.py` mounts `dist/` when it exists
COPY --from=web /app/dist /app/dist

# The ontology mirror (learning copy) is NOT needed at runtime: `ONTOLOGY_REPO` may point anywhere.
# The feature's declarations ship inside `backend/features/ontology/profiles/`.
ENV ONTOLOGY_REPO=/app/backend/features/ontology/profiles-mirror-not-required

EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8765/api/chat/health || exit 1

# One worker: the ontology compiler's state is process-wide and serialised by a lock inside the
# process; more workers would multiply that state, not share it (the same reason uvicorn's --reload
# and --workers are mutually exclusive here).
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8765", "--workers", "1"]
