#!/bin/bash
# Requests only this project's supervisor to stop; never kills a remembered PID.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -x "${PROJECT_DIR}/.venv/bin/python" ]; then
  CLASSROOM_PYTHON="${PROJECT_DIR}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  CLASSROOM_PYTHON="$(command -v python3)"
else
  echo "Use the project's existing Python environment."
  exit 1
fi
exec "$CLASSROOM_PYTHON" "$PROJECT_DIR/scripts/run_classroom_tunnel.py" --stop "$@"
