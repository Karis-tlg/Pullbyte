#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required." >&2
  exit 1
fi
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg is required." >&2
  exit 1
fi

VENV="$ROOT/.helper-venv"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
fi

"$VENV/bin/python" -m pip install --disable-pip-version-check -r requirements.txt
exec "$VENV/bin/python" helper/run.py
