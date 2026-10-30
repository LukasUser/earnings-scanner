#!/bin/zsh
# Install (or remove with --uninstall) a launchd agent that runs the scanner Monday-Friday
# at the time set in config.toml [schedule]. If the Mac is asleep at that time, launchd
# runs the job once when it wakes.
set -euo pipefail

LABEL="com.earnings-scanner.daily"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
DOMAIN="gui/$(id -u)"

if [[ "${1:-}" == "--uninstall" ]]; then
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Removed $LABEL"
  exit 0
fi

read -r HOUR MINUTE < <("$PROJECT/.venv/bin/python" -c "
import tomllib
s = tomllib.load(open('$PROJECT/config.toml', 'rb')).get('schedule', {})
print(int(s.get('hour', 7)), int(s.get('minute', 0)))
")

INTERVALS=""
for day in 1 2 3 4 5; do
  INTERVALS+="    <dict><key>Weekday</key><integer>$day</integer><key>Hour</key><integer>$HOUR</integer><key>Minute</key><integer>$MINUTE</integer></dict>
"
done

mkdir -p "$HOME/Library/LaunchAgents" "$PROJECT/logs"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>$PROJECT/scripts/run_daily.sh</string>
  </array>
  <key>WorkingDirectory</key><string>$PROJECT</string>
  <key>StartCalendarInterval</key>
  <array>
$INTERVALS  </array>
  <key>StandardOutPath</key><string>$PROJECT/logs/launchd.out.log</string>
  <key>StandardErrorPath</key><string>$PROJECT/logs/launchd.err.log</string>
</dict>
</plist>
EOF

plutil -lint "$PLIST" >/dev/null
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
printf "Installed %s: weekdays at %02d:%02d\n" "$LABEL" "$HOUR" "$MINUTE"
echo "Run now:   launchctl kickstart $DOMAIN/$LABEL"
echo "Remove:    $0 --uninstall"
