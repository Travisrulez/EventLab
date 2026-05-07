#!/usr/bin/env bash
set -euo pipefail

if [ "${1:-}" = "" ]; then
  echo "Usage: ./linux_agent.sh <TASK_URL> [--keep-bundle]"
  exit 2
fi

TASK_URL="${1%/}"
KEEP_BUNDLE="${2:-}"
BUNDLE_URL="$TASK_URL/bundle/linux.sh"
BUNDLE_FILE="$(mktemp /tmp/eventlab-bundle-XXXXXX.sh)"

echo "[Diploma EventLab] Downloading execution bundle..."
if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$BUNDLE_URL" -o "$BUNDLE_FILE"
elif command -v wget >/dev/null 2>&1; then
  wget -q "$BUNDLE_URL" -O "$BUNDLE_FILE"
else
  echo "curl or wget is required to download the task bundle"
  exit 3
fi

chmod 700 "$BUNDLE_FILE"
echo "[Diploma EventLab] Running bundle: $BUNDLE_FILE"
bash "$BUNDLE_FILE"

if [ "$KEEP_BUNDLE" != "--keep-bundle" ]; then
  rm -f "$BUNDLE_FILE"
else
  echo "[Diploma EventLab] Bundle kept at: $BUNDLE_FILE"
fi
