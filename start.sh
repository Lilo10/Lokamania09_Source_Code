#!/usr/bin/env bash
# Start the Lokamania 09 site on a container platform (Railway, Render, Fly...).
#
# Kept as a script rather than putting the whole command in the Procfile so that
# the port number is expanded by a real shell. Some platforms exec the Procfile
# command directly, in which case ${PORT} would reach gunicorn as a literal
# string and it would fail to start.
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-8080}"

# Fail early with a clear message rather than letting the app start and then
# crash on the first request.
: "${EXCEL_PATH:?EXCEL_PATH is not set. Add it under Settings -> Variables.}"
: "${ADMIN_PASSWORD:?ADMIN_PASSWORD is not set. Add it under Settings -> Variables.}"

echo "Starting Lokamania 09 on port ${PORT}"
echo "  workbook: ${EXCEL_PATH}"

# Run gunicorn as a module of this same Python, rather than as a bare "gunicorn"
# command. On a host the two can differ (a venv holds Flask but gunicorn is only
# on the system path, or vice versa), and that mismatch is a common cause of a
# crash on the very first start.
PYTHON="${PYTHON:-python3}"
echo "  python:   $(command -v "${PYTHON}")"

# --workers 1 is required: the workbook is one file, so all writes must be
# serialised inside a single process.
exec "${PYTHON}" -m gunicorn \
  --chdir server \
  --workers 1 \
  --threads 4 \
  --bind "0.0.0.0:${PORT}" \
  --timeout 120 \
  --graceful-timeout 30 \
  --access-logfile - \
  --error-logfile - \
  --capture-output \
  app:app
