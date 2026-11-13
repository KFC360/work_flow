#!/bin/sh
# Ensure OpenSSH/git can resolve the runtime uid (compose used to set user=UID:GID
# with no /etc/passwd row → "No user exists for uid N").
set -eu

UID_NUM="${HOST_UID:-1000}"
GID_NUM="${HOST_GID:-1000}"
HOME_DIR="${HOME:-/home/linuxuser}"

if [ "$(id -u)" = "0" ]; then
  if ! getent group "$GID_NUM" >/dev/null 2>&1; then
    groupadd -g "$GID_NUM" gw 2>/dev/null || true
    if ! getent group "$GID_NUM" >/dev/null 2>&1; then
      echo "gw:x:${GID_NUM}:" >> /etc/group
    fi
  fi
  if ! getent passwd "$UID_NUM" >/dev/null 2>&1; then
    useradd -u "$UID_NUM" -g "$GID_NUM" -d "$HOME_DIR" -M -s /bin/bash gw 2>/dev/null || true
    if ! getent passwd "$UID_NUM" >/dev/null 2>&1; then
      echo "gw:x:${UID_NUM}:${GID_NUM}:github-workflow:${HOME_DIR}:/bin/bash" >> /etc/passwd
    fi
  fi
  exec gosu "${UID_NUM}:${GID_NUM}" "$@"
fi

exec "$@"
