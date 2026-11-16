#!/usr/bin/env bash
# TideClock end-to-end demo — non-interactive, offline, no prompts.
# Every command writes results to stdout; validation failures go to stderr
# with a non-zero exit code (one is shown on purpose at the end).
set -euo pipefail
cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON:-python3}"
TIDE="tideclock.py"

step() {
  printf '\n\033[1m$ %s\033[0m\n' "$*"
}

printf 'TideClock demo — offline tide prediction, moon phase, safe harbor windows\n'
printf 'Station table is embedded in %s; nothing is downloaded.\n' "$TIDE"

step "$PYTHON_BIN $TIDE --version"
"$PYTHON_BIN" "$TIDE" --version

step "$PYTHON_BIN $TIDE tide --station \"Cape May, NJ\" --date 2025-06-01"
"$PYTHON_BIN" "$TIDE" tide --station "Cape May, NJ" --date 2025-06-01

step "$PYTHON_BIN $TIDE moon --date 2025-06-01"
"$PYTHON_BIN" "$TIDE" moon --date 2025-06-01

step "$PYTHON_BIN $TIDE harbor --station \"Bar Harbor, ME\" --date 2025-09-20 --draft 2.6 --margin 0.4"
"$PYTHON_BIN" "$TIDE" harbor --station "Bar Harbor, ME" --date 2025-09-20 --draft 2.6 --margin 0.4

step "$PYTHON_BIN $TIDE harbor --station \"Cape May, NJ\" --date 2025-06-01 --draft 99 --margin 0.5   # all-day message"
"$PYTHON_BIN" "$TIDE" harbor --station "Cape May, NJ" --date 2025-06-01 --draft 99 --margin 0.5

step "$PYTHON_BIN $TIDE moon                                   # --date defaults to today"
"$PYTHON_BIN" "$TIDE" moon

step "$PYTHON_BIN $TIDE tide --station \"San Francisco, CA\" --date 2025-06-01 --json   # machine mode"
"$PYTHON_BIN" "$TIDE" tide --station "San Francisco, CA" --date 2025-06-01 --json

step "$PYTHON_BIN $TIDE harbor --station \"Cape May, NJ\" --date 2025-06-01 --draft 2 --margin 0   # validation error"
set +e
"$PYTHON_BIN" "$TIDE" harbor --station "Cape May, NJ" --date 2025-06-01 --draft 2 --margin 0
status=$?
set -e
printf 'exit code %d (non-zero, message on stderr — the demo stops here on purpose)\n' "$status"

printf '\nDemo complete.\n'
