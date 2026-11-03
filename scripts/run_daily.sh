#!/bin/zsh
# Entry point for the scheduled run (launchd). Safe to run by hand too.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONUNBUFFERED=1
# caffeinate keeps the Mac from sleeping until the run finishes: -i blocks idle sleep, -s blocks
# system sleep on AC power (which also lets a plugged-in Mac with the lid closed finish the run).
exec /usr/bin/caffeinate -i -s .venv/bin/python -m earnings_scanner run "$@"
