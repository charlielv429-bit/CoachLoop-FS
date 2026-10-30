#!/bin/bash
# Mac double-click entry; no install, cloud action or credential input.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Finder may omit Homebrew tools used by the optional local video worker.
export PATH="/opt/homebrew/bin:/usr/local/bin:${PATH}"
if [ -x "${PROJECT_DIR}/.venv/bin/python" ]; then
  CONSOLE_PYTHON="${PROJECT_DIR}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  CONSOLE_PYTHON="$(command -v python3)"
else
  echo "Python unavailable. Use the project's existing Python environment."
  exit 1
fi
exec "${CONSOLE_PYTHON}" "${PROJECT_DIR}/scripts/run_prelesson_console.py" "$@"
