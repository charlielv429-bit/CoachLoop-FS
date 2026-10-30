#!/bin/bash
# Explicit first-time optional video environment installation; never opens a tunnel.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="/opt/homebrew/bin:/usr/local/bin:${PATH}"
if [ -x "${PROJECT_DIR}/.venv/bin/python" ]; then
  VIDEO_SETUP_PYTHON="${PROJECT_DIR}/.venv/bin/python"
else
  VIDEO_SETUP_PYTHON="$(command -v python3)"
fi
exec "$VIDEO_SETUP_PYTHON" "$PROJECT_DIR/scripts/setup_local_video.py"
