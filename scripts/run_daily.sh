#!/bin/zsh
# Entry point for the scheduled run (launchd). Safe to run by hand too.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONUNBUFFERED=1
exec .venv/bin/python -m earnings_scanner run "$@"
