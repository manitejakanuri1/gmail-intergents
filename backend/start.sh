#!/usr/bin/env bash
# Render start command. Runs the ARQ worker and the FastAPI web server in one
# service (Render's free tier doesn't include a separate background worker).
set -e

# Background worker (sync + AI enrichment jobs)
arq app.workers.tasks.WorkerSettings &

# Web server — bind to the port Render provides
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
