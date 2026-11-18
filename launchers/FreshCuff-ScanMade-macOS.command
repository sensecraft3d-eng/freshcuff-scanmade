#!/bin/bash
# FreshCuff ScanMade - offline launcher for macOS.
# Double-click in Finder (the first time: right-click -> Open, then Open again).
# Starts a small web server on this Mac only (127.0.0.1) and opens the app in your browser.
# Your scan never leaves this Mac. Needs Python 3.8+; nothing is downloaded or installed.
HERE="$(cd "$(dirname "$0")" && pwd)"
ONLINE="https://sensecraft3d-eng.github.io/freshcuff-scanmade/"

PY=""
for c in python3 /usr/local/bin/python3 /opt/homebrew/bin/python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1; then
    PY="$c"; break
  fi
done

if [ -z "$PY" ]; then
  echo
  echo "  Python 3.8 or newer was not found on this Mac."
  echo "  You can install it from https://www.python.org/downloads/macos/"
  echo "  or simply use the online version, which is the same app and also keeps your scan on your Mac:"
  echo "    $ONLINE"
  echo
  read -r -p "  Press Return to open the online version, or close this window... " _
  open "$ONLINE"
  exit 1
fi

"$PY" "$HERE/start_local.py" "$@"
echo
read -r -p "  FreshCuff ScanMade has stopped. Press Return to close this window... " _
