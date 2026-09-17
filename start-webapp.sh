#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

PYTHON="python3"
if [ -x ".venv/bin/python" ]; then
  PYTHON="$DIR/.venv/bin/python"
elif [ -x ".venv/Scripts/python.exe" ]; then
  PYTHON="$DIR/.venv/Scripts/python.exe"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON="python"
fi

if ! "$PYTHON" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null; then
  echo "Python 3.10+ is required."
  exit 1
fi

if ! "$PYTHON" -c "import fastapi, uvicorn, sqlalchemy, jwt" 2>/dev/null; then
  echo "Install dependencies first: $PYTHON -m pip install -r Backend/requirements.txt"
  exit 1
fi

export DATABASE_URL="sqlite:///./local_demo.db"
export ENFORCE_AUTH="true"
echo "Open http://127.0.0.1:8000 in separate teacher and student tabs."
echo "SIMULATION ONLY. Press Ctrl+C to stop. Data persists in local_demo.db."
exec "$PYTHON" -m uvicorn Backend.main:app --host 127.0.0.1 --port 8000 --workers 1
