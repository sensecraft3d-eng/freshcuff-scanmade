#!/usr/bin/env bash
# FreshCuff Fit - offline launcher for Linux.
# Starts a small web server on this computer only (127.0.0.1) and opens the app in your browser.
# Your scan never leaves this computer. Needs Python 3.8+; nothing is downloaded or installed.
# Run:  ./launchers/freshcuff-fit-linux.sh      (or: bash launchers/freshcuff-fit-linux.sh)
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ONLINE="https://sensecraft3d-eng.github.io/freshcuff-fit/"

PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1; then
    PY="$c"; break
  fi
done

if [ -z "$PY" ]; then
  echo
  echo "  Python 3.8 or newer was not found on this computer."
  echo "  Install it with your package manager (for example: sudo apt install python3),"
  echo "  or simply use the online version, which is the same app and also keeps your scan on your computer:"
  echo "    $ONLINE"
  echo
  exit 1
fi

exec "$PY" "$HERE/start_local.py" "$@"
