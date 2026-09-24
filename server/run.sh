#!/usr/bin/env bash
# Start the Lokamania 09 server (creates a virtualenv on first run).
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "Creating virtual environment..."
  /usr/bin/python3 -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements.txt
fi
exec .venv/bin/python app.py
