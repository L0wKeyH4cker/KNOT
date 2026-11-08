#!/usr/bin/env sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [ -x .venv/bin/python ]; then KNOT_PY=.venv/bin/python
elif command -v python3 >/dev/null 2>&1; then KNOT_PY=python3
elif command -v python >/dev/null 2>&1; then KNOT_PY=python
else echo "Python 3.10+ is required. Activate your Python environment, then try again."; exit 1; fi
"$KNOT_PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' || { echo "Python 3.10+ is required."; exit 1; }
exec "$KNOT_PY" knot.py "$@"
