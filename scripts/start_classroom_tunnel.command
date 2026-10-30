#!/bin/bash
# Explicit opt-in: double-clicking this script enables the temporary mock classroom.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -x "${PROJECT_DIR}/.venv/bin/python" ]; then
  CLASSROOM_PYTHON="${PROJECT_DIR}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  CLASSROOM_PYTHON="$(command -v python3)"
else
  echo "Use the project's existing Python 3.12+ environment."
  exit 1
fi
# Finder does not always inherit Homebrew's login-shell PATH.
export PATH="/opt/homebrew/bin:/usr/local/bin:${PATH}"
exec "$CLASSROOM_PYTHON" "$PROJECT_DIR/scripts/run_classroom_tunnel.py" --enable-classroom-tunnel "$@"
