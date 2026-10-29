#!/bin/bash
# Optional approved Coze deploy command; never run by this development task.
set -euo pipefail
WORK_DIR="${COZE_WORKSPACE_PATH:-.}"
if [ -f "${WORK_DIR}/.venv/bin/activate" ]; then
  source "${WORK_DIR}/.venv/bin/activate"
fi
if [ -n "${PIP_TARGET:-}" ]; then
  export PYTHONPATH="${PIP_TARGET}${PYTHONPATH:+:${PYTHONPATH}}"
fi
# Fail closed on profile/authentication errors before binding. The restricted
# profile needs no PGDATABASE_URL/DATABASE_URL and never resolves a database URL.
# Do not map platform database variables or copy development credentials here.
python "${WORK_DIR}/scripts/check_coze_deployment.py" --preflight
exec python "${WORK_DIR}/src/main.py" -m http -p "${DEPLOY_RUN_PORT:-5000}"
