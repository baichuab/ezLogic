#!/usr/bin/env bash
# Deploy the ezLogic demo to Google Cloud Run. See deploy/README.md.
#
#   deploy/cloudrun.sh setup     # once: APIs, image registry, Postgres (Cloud SQL), permissions
#   deploy/cloudrun.sh build     # build the image on Cloud Build (~20-40 min the first time)
#   deploy/cloudrun.sh deploy    # create/update the Cloud Run service from the last build
#   deploy/cloudrun.sh all       # setup + build + deploy
#   deploy/cloudrun.sh url       # print the site's URL
#   deploy/cloudrun.sh pause     # after the pitch: no instance kept running (stops most billing)
#   deploy/cloudrun.sh resume    # before the pitch: keep one warm instance again
#
# Every step is safe to re-run. Settings (override with environment variables):
#   PROJECT_ID  (default: gcloud's current project)   REGION   (australia-southeast1)
#   SERVICE     (ezlogic)                              OPENROUTER_MODEL (anthropic/claude-haiku-5.5)
#   OPENROUTER_API_KEY: taken from the environment, else backend/.env, else asked for.
set -euo pipefail
# Never stop to ask (e.g. "enable this API?"): the script enables what it needs itself.
export CLOUDSDK_CORE_DISABLE_PROMPTS=1

cd "$(dirname "$0")/.."

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-australia-southeast1}"
SERVICE="${SERVICE:-ezlogic}"
REPO="${REPO:-ezlogic}"
SQL_INSTANCE="${SQL_INSTANCE:-ezlogic-db}"
DB_NAME="${DB_NAME:-ezlogic}"
DB_USER="${DB_USER:-ezlogic}"
OPENROUTER_MODEL="${OPENROUTER_MODEL:-anthropic/claude-haiku-5.5}"

if [[ -z "$PROJECT_ID" ]]; then
  echo "No Google Cloud project. Run: gcloud config set project <PROJECT_ID>" >&2
  exit 1
fi
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${SERVICE}:latest"
SQL_CONN="${PROJECT_ID}:${REGION}:${SQL_INSTANCE}"
SITE_URL="https://${SERVICE}-${PROJECT_NUMBER}.${REGION}.run.app"
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

# Newly enabled APIs can take a few minutes to start answering: retry until they do.
retry() {
  local tries=0
  until "$@"; do
    tries=$((tries + 1))
    if (( tries >= 20 )); then
      echo "Still failing after $tries tries: $*" >&2
      return 1
    fi
    echo "  (not ready yet; retrying in 15 s)" >&2
    sleep 15
  done
}

service_exists() {
  gcloud run services describe "$SERVICE" --region "$REGION" --format='value(metadata.name)' >/dev/null 2>&1
}

openrouter_key() {
  if [[ -n "${OPENROUTER_API_KEY:-}" ]]; then
    printf '%s' "$OPENROUTER_API_KEY"
  elif [[ -f backend/.env ]] && grep -q '^OPENROUTER_API_KEY=.' backend/.env; then
    grep '^OPENROUTER_API_KEY=' backend/.env | head -1 | cut -d= -f2- | tr -d '"'"'"
  else
    local key
    read -rsp "OpenRouter API key: " key </dev/tty
    echo >&2
    printf '%s' "$key"
  fi
}

setup() {
  say "Project ${PROJECT_ID} (${PROJECT_NUMBER}), region ${REGION}"
  gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
    artifactregistry.googleapis.com sqladmin.googleapis.com --project "$PROJECT_ID"

  say "Image registry ${REPO}"
  ensure_repo() {
    gcloud artifacts repositories describe "$REPO" --location "$REGION" >/dev/null 2>&1 ||
      gcloud artifacts repositories create "$REPO" --repository-format docker --location "$REGION"
  }
  retry ensure_repo

  say "Permissions for the default service account (builds and the running service)"
  for role in roles/cloudsql.client roles/artifactregistry.writer roles/logging.logWriter roles/storage.objectViewer; do
    gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:${RUNTIME_SA}" \
      --role "$role" --condition None --quiet >/dev/null
  done

  say "Postgres: Cloud SQL instance ${SQL_INSTANCE} (smallest tier; creating takes ~10 min)"
  ensure_sql() {
    gcloud sql instances describe "$SQL_INSTANCE" >/dev/null 2>&1 ||
      gcloud sql instances create "$SQL_INSTANCE" --database-version POSTGRES_16 \
        --edition enterprise --tier db-f1-micro --region "$REGION" --storage-size 10
  }
  retry ensure_sql
  if ! gcloud sql databases describe "$DB_NAME" --instance "$SQL_INSTANCE" >/dev/null 2>&1; then
    gcloud sql databases create "$DB_NAME" --instance "$SQL_INSTANCE"
  fi
}

build() {
  say "Building ${IMAGE} on Cloud Build (Mathlib makes this ~10 GB; first build ~20-40 min)"
  gcloud builds submit . --tag "$IMAGE" \
    --timeout 3600s --machine-type e2-highcpu-8 --disk-size 100
}

deploy() {
  local flags=(
    --image "$IMAGE" --region "$REGION"
    --execution-environment gen2 --cpu 2 --memory 8Gi --cpu-boost
    --no-cpu-throttling --min-instances 1 --max-instances 1
    --concurrency 80 --timeout 3600 --allow-unauthenticated
    --add-cloudsql-instances "$SQL_CONN"
  )
  # A new instance reads Mathlib from the image for the first time, which takes a few
  # minutes on Cloud Run (78 s once read); the default 180 s limit is too short.
  local env="OPENROUTER_MODEL=${OPENROUTER_MODEL},FRONTEND_URL=${SITE_URL},GUEST_COOKIE_SECURE=true"
  env+=",LEAN_STARTUP_TIMEOUT=900"
  env+=",OPENROUTER_API_KEY=$(openrouter_key)"

  if service_exists; then
    say "Updating ${SERVICE} (database password and session secret are kept)"
    gcloud run deploy "$SERVICE" "${flags[@]}" --update-env-vars "$env" --quiet
  else
    say "Creating ${SERVICE}"
    # A fresh database password (the user is created or reset to match) and a
    # session secret that stays the same across later deploys.
    local db_password session_secret
    db_password="$(openssl rand -hex 24)"
    session_secret="$(openssl rand -hex 32)"
    if gcloud sql users list --instance "$SQL_INSTANCE" --format='value(name)' | grep -qx "$DB_USER"; then
      gcloud sql users set-password "$DB_USER" --instance "$SQL_INSTANCE" --password "$db_password"
    else
      gcloud sql users create "$DB_USER" --instance "$SQL_INSTANCE" --password "$db_password"
    fi
    env+=",DATABASE_URL=postgresql://${DB_USER}:${db_password}@/${DB_NAME}?host=/cloudsql/${SQL_CONN}"
    env+=",GUEST_JWT_SECRET=${session_secret}"
    gcloud run deploy "$SERVICE" "${flags[@]}" --set-env-vars "$env" --quiet
  fi
  url
}

url() {
  gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)'
}

case "${1:-}" in
  setup) setup ;;
  build) build ;;
  deploy) deploy ;;
  all) setup; build; deploy ;;
  url) url ;;
  pause) gcloud run services update "$SERVICE" --region "$REGION" --min-instances 0 --cpu-throttling ;;
  resume) gcloud run services update "$SERVICE" --region "$REGION" --min-instances 1 --no-cpu-throttling ;;
  *) sed -n '2,15p' "$0"; exit 1 ;;
esac
