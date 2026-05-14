#!/usr/bin/env bash
# Launch hue-iss in production mode (gunicorn).
#
# Run ./setup.sh first.
# To survive ssh disconnect on a server:
#   nohup setsid ./start.sh > data/app.log 2>&1 < /dev/null &
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f ".env" ]; then
  echo "✗ .env not found — run ./setup.sh first" >&2
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "✗ .venv not found — run ./setup.sh first" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

mkdir -p "${DATA_DIR:-./data}"

PORT="${PORT:-5057}"
WORKERS="${WORKERS:-1}"
THREADS="${THREADS:-4}"

exec .venv/bin/gunicorn \
  --workers "$WORKERS" \
  --threads "$THREADS" \
  --bind "0.0.0.0:${PORT}" \
  --access-logfile - \
  --error-logfile - \
  "app.app:create_app()"
