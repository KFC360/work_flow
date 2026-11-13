#!/bin/sh
# OpenSSH calls getpwuid(getuid()); without a matching /etc/passwd row it prints
# "No user exists for uid N" and refuses to run. Compose PATH may omit /usr/sbin,
# so gosu is invoked by absolute path. Always start the container as root.
set -eu

UID_NUM="${HOST_UID:-1000}"
GID_NUM="${HOST_GID:-1000}"
HOME_DIR="${HOME:-/home/linuxuser}"
GOSU_BIN="/usr/sbin/gosu"
NAME="gw${UID_NUM}"

ensure_identity() {
  if ! getent group "$GID_NUM" >/dev/null 2>&1; then
    echo "${NAME}:x:${GID_NUM}:" >> /etc/group
  fi
  if ! getent passwd "$UID_NUM" >/dev/null 2>&1; then
    echo "${NAME}:x:${UID_NUM}:${GID_NUM}:github-workflow:${HOME_DIR}:/bin/bash" >> /etc/passwd
  fi
  mkdir -p "$HOME_DIR"
  if ! getent passwd "$UID_NUM" >/dev/null 2>&1; then
    echo "docker-entrypoint: passwd still missing uid ${UID_NUM} after write" >&2
    exit 1
  fi
  echo "docker-entrypoint: uid=${UID_NUM} gid=${GID_NUM} home=${HOME_DIR} -> $(getent passwd "$UID_NUM")" >&2
}

if [ "$(id -u)" != "0" ]; then
  echo "docker-entrypoint: must start as root (got uid=$(id -u)); refuse to continue without passwd fix" >&2
  exit 1
fi

ensure_identity
if [ ! -x "$GOSU_BIN" ]; then
  echo "docker-entrypoint: missing $GOSU_BIN" >&2
  exit 1
fi
exec "$GOSU_BIN" "${UID_NUM}:${GID_NUM}" "$@"
