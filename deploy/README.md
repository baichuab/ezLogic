# Hosting the demo on Google Cloud Run

One Cloud Run service in Sydney (`australia-southeast1`) runs the whole app:

```
https://ezlogic-<project number>.australia-southeast1.run.app
   ├─ /api/*  FastAPI backend (agents, Lean, history)
   └─ /*      the built frontend, served by the same backend
Postgres: Cloud SQL (smallest Postgres 16 instance)
```

The site and the API share one address, so the guest-session cookie is first-party.
Browsers that block cross-site cookies (Safari on iPhones) work, and no CORS or proxy is
needed.

The image (root `Dockerfile`) contains:
- Lean 4.35.0;
- Mathlib v4.35.0, the versions tested locally;
- the lean-interact REPL, already built;
- the frontend build.

A new instance only has to load Mathlib into memory. The first time, Cloud Run reads the
files from the image, which takes about 3 minutes; after that a load takes about 78 s.

Measured on the first deployment:
- the image build took 23 minutes;
- the first Mathlib load took 180 s;
- a Lean check takes 0.3 s once Mathlib is loaded;
- a full proof (writer, explainer, dependency graph, saved to Cloud SQL) took 22 s.

## Cost
These are estimates; check [Cloud Run pricing](https://cloud.google.com/run/pricing).

| Part | Size | About |
| --- | --- | --- |
| Cloud Run, kept warm | 2 vCPU, 8 GiB, 1 instance | $4.5–6 a day while running |
| Cloud SQL | db-f1-micro, 10 GB | ~$0.30 a day |
| Image storage | ~10 GB in Artifact Registry | ~$1 a month |
| LLM (OpenRouter, Haiku 5.5) | ~1¢ per proof | a few dollars |

A new Google Cloud account's $300 trial credit (90 days) covers the Google part. After the
pitch, run `deploy/cloudrun.sh pause`, or delete everything (see [Clean up](#clean-up)).

## One-time setup (your accounts)
1. **Create a Google Cloud account and project** at <https://console.cloud.google.com>, and start the
   free trial. It needs a card, but the card isn't charged during the trial.
2. **Install the gcloud CLI and log in:**
   ```bash
   brew install --cask google-cloud-sdk
   gcloud auth login
   gcloud config set project <PROJECT_ID>
   ```
3. **The OpenRouter key:** the script takes `OPENROUTER_API_KEY` from the environment, else from
   `backend/.env`, else asks for it. It is stored as an environment variable of the Cloud Run
   service, so anyone with access to the project can see it.

## Deploy
```bash
deploy/cloudrun.sh all        # = setup + build + deploy
```
- **`setup`** turns on the APIs and creates the image registry and the Cloud SQL instance (about 10
  minutes the first time). It also grants the default service account what builds and the service
  need.
- **`build`** builds the image on Cloud Build: 20–40 minutes the first time, mostly downloading
  Mathlib. Your Mac uploads only the source, a few MB, not Mathlib (see `.gcloudignore`).
- **`deploy`** creates or updates the service:
  - one warm instance, never more, since each instance loads its own Mathlib;
  - CPU always on, so the Mathlib warm-up runs before the first visitor;
  - a 60-minute request limit for long proofs.

  On the first deploy it also creates the database user and the session secret. Later deploys keep
  both.

  Settings on the service:
  - `OPENROUTER_API_KEY` and `OPENROUTER_MODEL`;
  - `DATABASE_URL`, over the Cloud SQL socket;
  - `GUEST_JWT_SECRET` and `GUEST_COOKIE_SECURE=true`;
  - `FRONTEND_URL`;
  - `LEAN_STARTUP_TIMEOUT=900`, since the default of 180 s is too short for the first Mathlib load.

  Anyone with access to the project can read these in the console.

After changing the code, run `deploy/cloudrun.sh build && deploy/cloudrun.sh deploy`.

## Pitch day
1. `deploy/cloudrun.sh resume`, if you paused it, at least 10 minutes before you start. A new
   instance needs a few minutes to load Mathlib the first time.
2. Open the URL (`deploy/cloudrun.sh url`) and run one example proof. This confirms Mathlib is
   loaded and the AI key works.
3. If something looks wrong, read the logs:
   ```bash
   gcloud run services logs read ezlogic --region australia-southeast1 --limit 100
   ```
   - **"Mathlib loaded in …"** means it is ready.
   - **An out-of-memory restart** means the instance needs more memory: redeploy with `--memory 16Gi`
     in `cloudrun.sh`.

## Clean up
```bash
deploy/cloudrun.sh pause                                         # stop paying for the warm instance
gcloud run services delete ezlogic --region australia-southeast1   # remove the service
gcloud sql instances delete ezlogic-db                             # remove the database (and chat history)
```
