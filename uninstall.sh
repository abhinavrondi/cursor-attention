#!/bin/sh
# Stop the watcher and remove the login agent. Pass --purge to delete settings and logs.
set -eu

if [ "$(id -u)" -eq 0 ]; then
  echo "Run this as your user, without sudo." >&2
  exit 1
fi

LABEL="local.cursor-attention"
DOMAIN="gui/$(id -u)"
PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
DEST="${HOME}/.local/share/cursor-attention"
CONFIG_DIR="${HOME}/.config/cursor-attention"
STATE_DIR="${HOME}/.local/state/cursor-attention"

launchctl bootout "${DOMAIN}/${LABEL}" 2>/dev/null || true
rm -f "$PLIST"
rm -rf "$DEST"

if [ "${1:-}" = "--purge" ]; then
  rm -rf "$CONFIG_DIR" "$STATE_DIR"
  echo "Removed the watcher, settings, and logs."
else
  echo "Removed the watcher. Settings remain in $CONFIG_DIR"
  echo "Delete those too with: ./uninstall.sh --purge"
fi
