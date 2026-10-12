#!/data/data/com.termux/files/usr/bin/bash
# One-time setup of YT Navigator inside Termux (Android).
# Usage (from the repository folder):  bash mobile/termux-setup.sh
set -euo pipefail

cd "$(dirname "$0")/.."
REPO_DIR="$(pwd)"

echo "==> Installing system packages (Python, Rust toolchain for building some Python packages)"
pkg update -y
pkg install -y python python-pip python-numpy rust binutils clang make git curl

# Rust-based Python packages (pydantic-core, orjson, ...) have no Android wheels and are compiled locally.
export ANDROID_API_LEVEL="$(getprop ro.build.version.sdk)"
export CARGO_BUILD_JOBS="${CARGO_BUILD_JOBS:-4}"

echo "==> Creating the Python virtual environment"
# --system-site-packages lets the venv reuse Termux's prebuilt numpy instead of compiling it.
python -m venv --system-site-packages .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip wheel setuptools

echo "==> Installing YT Navigator (the first run compiles a few packages and can take 20-40 minutes)"
pip install -e .

if [ ! -f .env ]; then
    echo "==> Creating .env"
    read -r -p "Groq API key (https://console.groq.com/keys): " GROQ_KEY
    read -r -p "Cohere API key (https://dashboard.cohere.com/api-keys): " COHERE_KEY
    SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(50))')"
    cat > .env <<ENV
DJANGO_SECRET_KEY="$SECRET"
DEBUG=False
GROQ_API_KEY=$GROQ_KEY
COHERE_API_KEY=$COHERE_KEY
LANGSMITH_TRACING=False
LOG_LEVEL=INFO
DJANGO_LOG_LEVEL=WARNING
ENV
fi

echo "==> Preparing the database"
python manage.py makemigrations app --noinput
python manage.py migrate --noinput
python manage.py collectstatic --noinput > /dev/null

echo "==> Allowing the YT Navigator Android app to start the server through Termux"
mkdir -p ~/.termux
touch ~/.termux/termux.properties
if ! grep -q '^allow-external-apps' ~/.termux/termux.properties; then
    echo "allow-external-apps = true" >> ~/.termux/termux.properties
fi
termux-reload-settings 2>/dev/null || true

# `ytnav` command (also what the Android app runs) and a Termux:Widget shortcut
for launcher in "$PREFIX/bin/ytnav" ~/.shortcuts/YT-Navigator; do
    mkdir -p "$(dirname "$launcher")"
    printf '#!/data/data/com.termux/files/usr/bin/bash\nexec bash "%s/mobile/start.sh" "$@"\n' "$REPO_DIR" > "$launcher"
    chmod +x "$launcher"
done

echo
echo "Setup complete."
echo "  Start the server:  ytnav"
echo "  Then open the YT Navigator app, or http://127.0.0.1:8000 in Chrome."
