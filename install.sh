#!/bin/sh
# Install the watcher for the current Mac user and start it at login.
set -eu

if [ "$(id -u)" -eq 0 ]; then
  echo "Run this as your user, without sudo." >&2
  exit 1
fi

ROOT=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
DEST="${HOME}/.local/share/cursor-attention"
CONFIG_DIR="${HOME}/.config/cursor-attention"
STATE_DIR="${HOME}/.local/state/cursor-attention"
AGENTS="${HOME}/Library/LaunchAgents"
PLIST="${AGENTS}/local.cursor-attention.plist"
LABEL="local.cursor-attention"
DOMAIN="gui/$(id -u)"
PYTHON=$(command -v python3 || true)

if [ -z "$PYTHON" ]; then
  echo "python3 is required." >&2
  exit 1
fi

mkdir -p "$DEST" "$CONFIG_DIR" "$STATE_DIR" "$AGENTS"
cp "$ROOT/cursor_attention.py" "$DEST/cursor_attention.py"
chmod 755 "$DEST/cursor_attention.py"

if [ ! -f "$CONFIG_DIR/config.ini" ]; then
  cp "$ROOT/config.example.ini" "$CONFIG_DIR/config.ini"
  echo "Wrote $CONFIG_DIR/config.ini"
else
  echo "Kept existing $CONFIG_DIR/config.ini"
fi

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON}</string>
    <string>${DEST}/cursor_attention.py</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ThrottleInterval</key>
  <integer>10</integer>
  <key>ProcessType</key>
  <string>Standard</string>
  <key>StandardOutPath</key>
  <string>${STATE_DIR}/launchd.out</string>
  <key>StandardErrorPath</key>
  <string>${STATE_DIR}/launchd.err</string>
</dict>
</plist>
EOF

launchctl bootout "${DOMAIN}/${LABEL}" 2>/dev/null || true
launchctl enable "${DOMAIN}/${LABEL}"
launchctl bootstrap "$DOMAIN" "$PLIST"

echo "Installed. Settings: $CONFIG_DIR/config.ini"
echo "After a settings change, run: launchctl kickstart -k ${DOMAIN}/${LABEL}"
