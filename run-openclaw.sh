#!/bin/bash
# Wrapper script: loads .env (strips 'export ' prefix for systemd compat),
# then runs main.py.
#
# Supports both formats in .env:
#   export KEY=value    ← bash-style (from .env.example)
#   KEY=value           ← systemd-style
#
# Usage:
#   ./run-openclaw.sh          # uses system python
#   .venv/bin/python main.py   # if using a virtual environment

ENVFILE="$(dirname "$0")/.env"
if [[ ! -f "$ENVFILE" ]]; then
    echo "ERROR: .env not found at $ENVFILE"
    exit 1
fi

# Load .env: strip "export " prefix so each line becomes KEY=value,
# then export so child processes (python, aplay, etc.) see the vars.
while IFS= read -r line || [[ -n "$line" ]]; do
    # Skip comments and empty lines
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ -z "${line// }" ]] && continue
    # Strip "export " prefix if present
    line="${line#export }"
    # Skip if now empty or just a comment
    [[ -z "$line" ]] && continue
    [[ "$line" =~ ^# ]] && continue
    export "$line"
done < "$ENVFILE"

# Prefer venv python if .venv exists, otherwise fall back to system python
if [[ -x "$(dirname "$0")/.venv/bin/python" ]]; then
    exec "$(dirname "$0")/.venv/bin/python" "$(dirname "$0")/main.py" "$@"
else
    exec python3 "$(dirname "$0")/main.py" "$@"
fi
