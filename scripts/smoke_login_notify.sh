#!/usr/bin/env bash
# Post-deploy smoke: Playwright login + email via SMOKE_NOTIFY_TO.
#
# Runs inside the official Playwright Docker image so the host does not need
# Chromium system libraries (libatk, etc.). Requires docker (same as deploy).
#
# Override image: PLAYWRIGHT_IMAGE=mcr.microsoft.com/playwright:v1.65.1-jammy
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "ERROR: missing .env" >&2
  exit 1
fi
if [[ ! -f config.yaml ]]; then
  echo "ERROR: missing config.yaml (mail config)" >&2
  exit 1
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker not found (smoke runs in Playwright container)" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

# Keep in sync with playwright version in pyproject optional extra `smoke`
PLAYWRIGHT_IMAGE="${PLAYWRIGHT_IMAGE:-mcr.microsoft.com/playwright:v1.65.1-jammy}"
mkdir -p logs/smoke

echo "==> smoke via ${PLAYWRIGHT_IMAGE}"
docker run --rm --network host \
  -e APP_ADMIN_USER \
  -e APP_ADMIN_PASSWORD \
  -e SMOKE_NOTIFY_TO \
  -e SMOKE_BASE_URL \
  -e SMTP_PASSWORD \
  -e DATABASE_URL \
  -e UV_PROJECT_ENVIRONMENT=/tmp/gw-smoke-venv \
  -e PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
  -e PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
  -v "$ROOT:/work" \
  -w /work \
  "$PLAYWRIGHT_IMAGE" \
  bash -lc '
    set -euo pipefail
    export PATH="${HOME}/.local/bin:/usr/local/bin:${PATH}"
    if ! command -v uv >/dev/null 2>&1; then
      echo "==> install uv in container"
      curl -LsSf https://astral.sh/uv/install.sh | sh
      export PATH="${HOME}/.local/bin:${PATH}"
    fi
    echo "==> uv sync --extra smoke --frozen"
    uv sync --extra smoke --frozen
    echo "==> smoke_login_notify.py"
    uv run --extra smoke python scripts/smoke_login_notify.py
  '
