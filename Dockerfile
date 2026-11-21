# One image for the hosted demo (Google Cloud Run, see deploy/README.md): the built
# frontend and the FastAPI backend in one service, so the site and /api share one
# origin. Lean 4.35.0, Mathlib v4.35.0 (the versions tested locally) and the
# lean-interact REPL are built into the image, so a new instance only has to load
# Mathlib into memory (~1 min), not download or build anything.
#
# The teammates' docker-compose setup (backend/Dockerfile, frontend/Dockerfile)
# is separate and unchanged.

# --- Frontend: static SvelteKit build (adapter-static) -----------------------------
FROM node:22-bookworm AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Backend + Lean ----------------------------------------------------------------
FROM python:3.12-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

ENV ELAN_HOME=/opt/elan
ENV PATH="/opt/elan/bin:${PATH}"
RUN curl -sSf https://elan.lean-lang.org/elan-init.sh \
    | sh -s -- -y --no-modify-path --default-toolchain leanprover/lean4:v4.35.0

# The Lake project the agent works in (same as backend/workspace locally), with
# Mathlib's prebuilt .olean files downloaded by `lake exe cache get`.
WORKDIR /opt/lean-project
RUN printf 'name = "ezlogic_workspace"\n\n[[require]]\nname = "mathlib"\nscope = "leanprover-community"\nrev = "v4.35.0"\n' > lakefile.toml \
    && echo "leanprover/lean4:v4.35.0" > lean-toolchain \
    && lake update \
    && lake exe cache get

WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./

ENV WORKSPACE_DIR=/opt/lean-project \
    LEAN_INTERACT_CACHE=/opt/lean_cache \
    STATIC_DIR=/app/static \
    PYTHONUNBUFFERED=1

# Build the lean-interact REPL now (it is otherwise cloned and compiled on the
# first Lean check). Starting it doesn't load Mathlib, so this is quick and light.
RUN python -c "from agent import lean; lean._get_server(); print('REPL ready')"

COPY --from=web /web/build ./static

# Cloud Run sets PORT (8080). One worker: each worker would load its own Mathlib.
CMD exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8080}" --timeout-keep-alive 620
