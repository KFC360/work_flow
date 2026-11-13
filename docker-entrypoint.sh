#!/bin/sh
# Ensure OpenSSH/git can resolve the runtime uid.
# Compose sets PATH without /usr/sbin, so call gosu by absolute path.
set -eu

UID_NUM="${HOST_UID:-1000}"
GID_NUM="${HOST_GID:-1000}"
HOME_DIR="${HOME:-/home/linuxuser}"
GOSU_BIN="/usr/sbin/gosu"

ensure_identity() {
  if ! getent group "$GID_NUM" >/dev/null 2>&1; then
    echo "gw:x:${GID_NUM}:" >> /etc/group
  fi
  if ! getent passwd "$UID_NUM" >/dev/null 2>&1; then
    echo "gw:x:${UID_NUM}:${GID_NUM}:github-workflow:${HOME_DIR}:/bin/bash" >> /etc/passwd
  fi
}

if [ "$(id -u)" = "0" ]; then
  ensure_identity
  if [ ! -x "$GOSU_BIN" ]; then
    echo "docker-entrypoint: missing $GOSU_BIN" >&2
    exit 1
  fi
  exec "$GOSU_BIN" "${UID_NUM}:${GID_NUM}" "$@"
fi

# Already non-root (e.g. compose user:); cannot write passwd — hope image baked it.
exec "$@"
