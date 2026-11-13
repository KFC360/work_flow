#!/usr/bin/env bash
# Build and (re)start production stack: db + web + worker.
# Run from the app root (or any cwd; script cds to repo root).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "ERROR: missing .env (copy from .env.example and fill production values)" >&2
  exit 1
fi
if [[ ! -f config.yaml ]]; then
  echo "ERROR: missing config.yaml (copy from config.yaml.example)" >&2
  exit 1
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker not found" >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "ERROR: docker compose plugin not found" >&2
  exit 1
fi

# shellcheck disable=SC1091
set -a
# Compose interpolates HOST_* / WORKTREE_ROOT / REPOS_ROOT from .env
source .env
set +a

HOST_HOME="${HOST_HOME:-${HOME}}"
WORKTREE_ROOT="${WORKTREE_ROOT:-/var/lib/github-workflow/worktrees}"
REPOS_ROOT="${REPOS_ROOT:-${HOST_HOME}/repos}"

echo "==> ensure host bind-mount sources exist"
mkdir -p \
  "$WORKTREE_ROOT" \
  "$REPOS_ROOT" \
  logs \
  "${HOST_HOME}/.opencode" \
  "${HOST_HOME}/.config/opencode" \
  "${HOST_HOME}/.local" \
  "${HOST_HOME}/.ssh" \
  "${HOST_HOME}/.claude" \
  "${HOST_HOME}/.config/claude"

if [[ -x ./scripts/sync_opencode_skills.sh ]]; then
  echo "==> sync_opencode_skills (host OpenCode discovery path)"
  ./scripts/sync_opencode_skills.sh || true
fi

echo "==> docker compose build"
docker compose build

echo "==> ensure db is up"
docker compose up -d db
echo "==> wait for db health"
for _ in $(seq 1 30); do
  if docker compose exec -T db pg_isready -U github_workflow -d github_workflow >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker compose exec -T db pg_isready -U github_workflow -d github_workflow

echo "==> alembic upgrade head"
docker compose run --rm --no-deps web alembic upgrade head

echo "==> docker compose up -d --force-recreate"
docker compose up -d --force-recreate web worker
docker compose up -d db

echo "==> healthz"
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:8095/healthz" >/dev/null 2>&1; then
    curl -fsS "http://127.0.0.1:8095/healthz"
    echo
    docker compose ps
    echo "==> deploy ok"
    exit 0
  fi
  sleep 1
done

echo "ERROR: healthz did not become ready on 127.0.0.1:8095" >&2
docker compose ps >&2 || true
docker compose logs --tail=80 web >&2 || true
exit 1
