#!/bin/bash
# Wrapper script: loads .env with 'export' lines, then runs main.py.
# Use this instead of directly invoking 'python main.py' when your .env
# contains 'export KEY=value' lines (python-dotenv handles both, but
# sourcing via this script ensures all child processes see the vars).
#
# Usage:
#   ./run-openclaw.sh          # uses system python
#   .venv/bin/python main.py   # if using a virtual environment

set -a  # export all variables from sourced file
source "$(dirname "$0")/.env"
set +a

# Prefer venv python if .venv exists, otherwise fall back to system python
if [[ -x "$(dirname "$0")/.venv/bin/python" ]]; then
    exec "$(dirname "$0")/.venv/bin/python" "$(dirname "$0")/main.py" "$@"
else
    exec python3 "$(dirname "$0")/main.py" "$@"
fi
