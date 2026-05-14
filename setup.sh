#!/usr/bin/env bash
# One-shot installer for hue-iss.
#
# Creates a virtualenv, installs dependencies, fetches the vendored
# Alpine.js bundle, and writes a .env with a generated FLASK_SECRET if
# one doesn't already exist.
#
# Usage: ./setup.sh
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
VENV_DIR=".venv"

echo "▶ checking python..."
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "✗ python3 not found in PATH" >&2
  exit 1
fi
PY_VERSION=$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "  using $PYTHON ($PY_VERSION)"
"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' || {
  echo "✗ Python 3.8 or newer required (found $PY_VERSION)" >&2
  exit 1
}

echo "▶ creating virtualenv at $VENV_DIR..."
if [ ! -d "$VENV_DIR" ]; then
  "$PYTHON" -m venv "$VENV_DIR"
fi

# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

echo "▶ installing dependencies..."
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
echo "  done"

echo "▶ fetching vendored Alpine.js bundle..."
bash scripts/vendor.sh

if [ ! -f ".env" ]; then
  echo "▶ generating .env with a fresh FLASK_SECRET..."
  SECRET=$("$PYTHON" -c "import secrets; print(secrets.token_hex(32))")
  cat > .env <<EOF
FLASK_SECRET=${SECRET}
TIMEZONE=Europe/Zurich
IP_GEO_URL=https://ipapi.co/json/
DATA_DIR=./data
PORT=5057
EOF
  echo "  wrote .env"
else
  echo "▶ .env already exists, keeping as is"
fi

mkdir -p data

cat <<'NEXT'

✓ setup complete.

Next steps:
  1. start the app:    ./start.sh
  2. open dashboard:   http://localhost:5057
  3. in the dashboard: search for your city, then pair your Hue bridge.

For server use (Synology, Raspberry Pi, etc.):
  nohup setsid ./start.sh > data/app.log 2>&1 < /dev/null &

NEXT
