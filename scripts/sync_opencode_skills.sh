#!/usr/bin/env bash
# 将应用仓 agent_skills 挂到 OpenCode 全局 skills 目录，供 Worker 的 opencode 发现。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${ROOT}/agent_skills"
DEST="${OPENCODE_SKILLS_DIR:-${HOME}/.config/opencode/skills}"

if [[ ! -d "$SRC" ]]; then
  echo "missing $SRC" >&2
  exit 1
fi

mkdir -p "$(dirname "$DEST")"
if [[ -e "$DEST" || -L "$DEST" ]]; then
  if [[ -L "$DEST" ]]; then
    rm -f "$DEST"
  else
    echo "refusing to replace non-symlink: $DEST" >&2
    echo "set OPENCODE_SKILLS_DIR or remove/rename it first" >&2
    exit 1
  fi
fi
ln -sfn "$SRC" "$DEST"
echo "linked $DEST -> $SRC"
ls -la "$DEST"
