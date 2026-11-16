#!/usr/bin/env bash
# TideClock setup: install the test runner, register the `tideclock` console
# script, and self-check the module. Installs project-level dependencies only,
# is safe to re-run, and EXITS (it never starts anything long-running).
set -euo pipefail
cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "error: $PYTHON_BIN not found. See INSTALL.md for prerequisites (Python 3.9+)." >&2
  exit 1
fi

echo "TideClock setup"
echo "  interpreter: $("$PYTHON_BIN" --version 2>&1)"
echo "  runtime:     Python standard library only (no runtime dependencies)"

# Fall back to a per-user install when the interpreter's site-packages is not
# writable (the sandbox runs unprivileged in that case).
pip_install() {
  if ! "$PYTHON_BIN" -m pip install --quiet "$@" 2>/dev/null; then
    "$PYTHON_BIN" -m pip install --quiet --user "$@"
  fi
}

# 1. Refresh packaging tooling first; a stale pip silently fails editable installs.
if ! "$PYTHON_BIN" -m pip install --quiet --upgrade pip setuptools wheel 2>/dev/null; then
  echo "  note: could not refresh pip/setuptools/wheel (offline?) — continuing with installed versions"
fi

# 2. Declared dependencies (the pytest test runner).
pip_install -r requirements.txt
echo "  dependencies: ok"

# 3. Register the `tideclock` console entry point at the project root.
if ! pip_install -e . 2>/dev/null; then
  echo "  note: console script not installed — run the tool as: $PYTHON_BIN tideclock.py"
fi

# 4. Self-check: import the module and render one prediction, so a broken
#    environment fails here instead of at first use.
"$PYTHON_BIN" -c 'import tideclock; assert callable(tideclock.main)'
"$PYTHON_BIN" tideclock.py tide --station "Cape May, NJ" --date 2025-06-01 > /dev/null
echo "  self-check: ok"

if command -v tideclock >/dev/null 2>&1; then
  echo "  console script: $(command -v tideclock)"
fi

echo
echo "Setup complete. Try:"
echo "  tideclock moon --date 2025-06-01"
echo "  $PYTHON_BIN tideclock.py harbor --station \"Bar Harbor, ME\" --date 2025-09-20 --draft 2.6 --margin 0.4"
echo "Tests: $PYTHON_BIN -m pytest"
