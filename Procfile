web: gunicorn --chdir server --workers 1 --threads 4 --bind 0.0.0.0:${PORT:-8080} --timeout 120 --graceful-timeout 30 --access-logfile - --error-logfile - --capture-output app:app
