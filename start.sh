#!/usr/bin/env bash
# Start the Lokamania 10 site on Railway (or any container host).
#
# Kept as a script rather than putting the whole command in the Procfile so that
# the port number is expanded by a real shell.
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-8080}"

# Fail early with a clear message rather than letting the app start and then
# lose data: the database must live on the persistent volume, not in the
# container, which is wiped on every deploy.
: "${DATABASE_PATH:?DATABASE_PATH is not set. Add it under Settings -> Variables (e.g. /data/lokamania10.db).}"
: "${ADMIN_PASSWORD:?ADMIN_PASSWORD is not set. Add it under Settings -> Variables.}"

if [ ! -f server/app.py ]; then
  echo "ERROR: server/app.py is missing from the deployed files."
  ls -la
  exit 1
fi

echo "Starting Lokamania 10 on port ${PORT}"
echo "  database: ${DATABASE_PATH}"
if [ -n "${SHEET_WEBAPP_URL:-}" ] && [ -n "${SHEET_SECRET:-}" ]; then
  echo "  google sheet: sync on"
else
  echo "  google sheet: NOT configured (set SHEET_WEBAPP_URL and SHEET_SECRET)"
fi
if [ "${MAINTENANCE_MODE:-}" = "1" ]; then
  echo "  maintenance mode: ON (home page shows the hold page)"
fi

PYTHON="${PYTHON:-python3}"

# --workers 1 is required: one process owns the database writes and the
# Google Sheet sync thread.
exec "${PYTHON}" -m gunicorn \
  --chdir server \
  --workers 1 \
  --threads 8 \
  --bind "0.0.0.0:${PORT}" \
  --timeout 120 \
  --graceful-timeout 30 \
  --access-logfile - \
  --error-logfile - \
  --capture-output \
  app:app
