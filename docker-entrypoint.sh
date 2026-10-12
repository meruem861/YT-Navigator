#!/bin/bash
set -e

# Create log directory and file (no ownership changes needed since we set this up in Dockerfile)
echo "Setting up log directory and file..."
LOG_FILE="/app/logs/$(date +%Y-%m-%d).jsonl"
touch $LOG_FILE

# Apply database migrations (SQLite, stored in $DATA_DIR)
echo "Applying database migrations..."
python manage.py makemigrations app --noinput
python manage.py migrate --noinput
python manage.py collectstatic --noinput > /dev/null

# Start the application
echo "Starting application..."
exec "$@"
