#!/data/data/com.termux/files/usr/bin/bash
# One-time setup of YT Navigator inside Termux (Android) — the alternative to the all-in-one APK, for developers.
# Usage (from the repository folder):  bash mobile/termux-setup.sh
set -euo pipefail

cd "$(dirname "$0")/.."
REPO_DIR="$(pwd)"

echo "==> Installing system packages"
pkg update -y
pkg install -y python python-pip python-numpy git curl

echo "==> Creating the Python virtual environment"
# --system-site-packages lets the venv reuse Termux's prebuilt numpy instead of compiling it.
python -m venv --system-site-packages .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip wheel setuptools

echo "==> Installing YT Navigator"
pip install -e .

if [ ! -f .env ]; then
    echo "==> Creating .env"
    read -r -p "Groq API key (https://console.groq.com/keys): " GROQ_KEY
    read -r -p "Cohere API key (https://dashboard.cohere.com/api-keys): " COHERE_KEY
    cat > .env <<ENV
DEBUG=False
SINGLE_USER_MODE=True
GROQ_API_KEY=$GROQ_KEY
COHERE_API_KEY=$COHERE_KEY
LOG_LEVEL=INFO
DJANGO_LOG_LEVEL=WARNING
ENV
fi

echo "==> Preparing the database"
python manage.py migrate --noinput

# `ytnav` command and a Termux:Widget shortcut
for launcher in "$PREFIX/bin/ytnav" ~/.shortcuts/YT-Navigator; do
    mkdir -p "$(dirname "$launcher")"
    printf '#!/data/data/com.termux/files/usr/bin/bash\nexec bash "%s/mobile/start.sh" "$@"\n' "$REPO_DIR" > "$launcher"
    chmod +x "$launcher"
done

echo
echo "Setup complete."
echo "  Start the server:  ytnav"
echo "  Then open http://127.0.0.1:8000 in Chrome."
