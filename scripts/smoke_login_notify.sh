#!/usr/bin/env bash
# Post-deploy smoke: Playwright login + email via SMOKE_NOTIFY_TO.
# First-time host setup:
#   uv sync --extra smoke
#   uv run playwright install chromium
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "ERROR: missing .env" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: uv not found in PATH=$PATH" >&2
  exit 1
fi

echo "==> uv sync --extra smoke"
uv sync --extra smoke

if ! uv run --extra smoke python -c "from playwright.sync_api import sync_playwright" >/dev/null 2>&1; then
  echo "ERROR: playwright import failed after uv sync --extra smoke" >&2
  exit 1
fi

# Ensure Chromium is present (no-op if already installed).
uv run --extra smoke playwright install chromium

echo "==> smoke_login_notify.py"
uv run --extra smoke python scripts/smoke_login_notify.py
