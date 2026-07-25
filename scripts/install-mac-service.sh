#!/usr/bin/env bash
# Install macOS launch agent — server starts on login and stays alive.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/com.hisense.remote.plist"
chmod +x "$ROOT/scripts/run-server.sh" "$ROOT/start.sh"

cat > "$PLIST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.hisense.remote</string>
  <key>ProgramArguments</key>
  <array>
    <string>${ROOT}/scripts/run-server.sh</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${ROOT}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/tmp/hisense-remote-supervisor.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/hisense-remote-supervisor.log</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/com.hisense.remote" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl enable "gui/$(id -u)/com.hisense.remote"
launchctl kickstart -k "gui/$(id -u)/com.hisense.remote"

echo "Installed. Server runs on login and auto-restarts."
echo "  HTTPS: check ip with: ipconfig getifaddr en0"
echo "  Logs:  /tmp/hisense-remote-supervisor.log"
echo ""
echo "Uninstall: launchctl bootout gui/\$(id -u)/com.hisense.remote"
