#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

ALPINE_VERSION="3.14.1"
TARGET="app/static/alpine.min.js"

if [ -s "$TARGET" ]; then
  echo "Alpine.js already present at $TARGET"
  exit 0
fi

mkdir -p app/static
echo "Downloading Alpine.js $ALPINE_VERSION..."
curl -fsSL -o "$TARGET" \
  "https://cdn.jsdelivr.net/npm/alpinejs@${ALPINE_VERSION}/dist/cdn.min.js"
echo "Wrote $TARGET ($(wc -c < "$TARGET") bytes)"
