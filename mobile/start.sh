#!/data/data/com.termux/files/usr/bin/bash
# Start the YT Navigator server on http://127.0.0.1:8000 (run inside Termux).
set -euo pipefail

cd "$(dirname "$0")/.."
PORT="${PORT:-8000}"

if curl -s -o /dev/null "http://127.0.0.1:$PORT/login/"; then
    echo "YT Navigator is already running on http://127.0.0.1:$PORT"
    exit 0
fi

# shellcheck disable=SC1091
source .venv/bin/activate

# Pick up model changes after a `git pull`
python manage.py makemigrations app --noinput > /dev/null
python manage.py migrate --noinput > /dev/null
python manage.py collectstatic --noinput > /dev/null

# Keep Android from suspending the server while the screen is off
termux-wake-lock 2>/dev/null || true

echo "YT Navigator running on http://127.0.0.1:$PORT (Ctrl+C to stop)"
exec uvicorn yt_navigator.asgi:application --host 127.0.0.1 --port "$PORT"
