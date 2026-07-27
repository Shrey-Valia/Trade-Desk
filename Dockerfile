# syntax=docker/dockerfile:1
# Trade Desk — single-container image: the FastAPI backend serves both the
# API and the built React SPA (SERVE_FRONTEND_DIR). See docs/DEPLOYMENT.md.
#
# IMPORTANT: run exactly ONE container per database. APScheduler runs
# IN-PROCESS; a second replica double-fires billing/settlement/backup jobs.
# For the same reason the CMD must stay a single uvicorn worker (no
# --workers, no --reload).

########################################################################
# Stage 1 — frontend build (Vite → static dist/)
########################################################################
FROM node:20-alpine AS frontend-build
WORKDIR /build/frontend

# Dependency layer first so source edits don't bust the npm ci cache.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

########################################################################
# Stage 2 — backend runtime (python 3.11 per backend/pyproject.toml)
########################################################################
FROM python:3.11-slim AS runtime

# uv from the official distroless image (pinned minor; the repo's uv.lock
# was produced by uv 0.11.x).
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /usr/local/bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app/backend

# Dependency layer: locked resolve WITHOUT the project itself, so the
# (pandas/numpy/scipy) install is cached until uv.lock changes.
# --extra pg bakes in the psycopg driver so pointing DATABASE_URL at
# Postgres is pure configuration (see docs/DEPLOYMENT.md).
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --extra pg

# Backend source, then install the project into the same venv.
COPY backend/ ./
RUN uv sync --frozen --no-dev --extra pg

# Built SPA from stage 1. config.py resolves PROJECT_ROOT to /app, so the
# default data paths (DB, uploads, backups) all land under /app/data.
COPY --from=frontend-build /build/frontend/dist /app/frontend/dist

ENV PATH="/app/backend/.venv/bin:$PATH" \
    SERVE_FRONTEND_DIR=/app/frontend/dist \
    DATABASE_URL=sqlite:////app/data/dashboard.db \
    APP_ENV=production

# DB + journal-screenshot uploads + nightly backups. Mount a named volume
# here (docker-compose.yml does) or the data dies with the container.
VOLUME /app/data

EXPOSE 8000

# /health returns 200 only when the DB answers (503 otherwise). python is
# the venv's 3.11; urllib keeps the image curl-free.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

# Single process, single worker — the APScheduler constraint (see header).
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
