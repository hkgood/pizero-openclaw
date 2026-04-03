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

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
ENVFILE="$REPO_DIR/.env"
if [[ ! -f "$ENVFILE" ]]; then
    echo "ERROR: .env not found at $ENVFILE"
    echo "Run: cp .env.example .env"
    exit 1
fi

# ── 自动检测平台：没有 WhisPlay 就进入测试模式 ────────────────────────────
# 如果 TEST_MODE 还没设置（不是 true/false），自动检测
if [[ "$TEST_MODE" != "true" && "$TEST_MODE" != "false" ]]; then
    # 检查是否在树莓派上
    IS_RPI=false
    if [[ -f /proc/device-tree/model ]] && grep -qi "raspberry" /proc/device-tree/model 2>/dev/null; then
        IS_RPI=true
    fi

    # 检查 WhisPlay 驱动是否存在
    HAS_WHISPLAY=false
    if [[ -d "$HOME/Whisplay/Driver" ]] || [[ -d "/opt/WhisPlay" ]]; then
        HAS_WHISPLAY=true
    fi

    # macOS 或没有 WhisPlay → 测试模式
    if [[ "$(uname)" == "Darwin" ]] || [[ "$IS_RPI" == "false" ]] || [[ "$HAS_WHISPLAY" == "false" ]]; then
        echo "[run-openclaw] 自动进入测试模式（未检测到 WhisPlay 硬件）"
        TEST_MODE=true
    else
        TEST_MODE=false
    fi
fi
export TEST_MODE

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
if [[ -x "$REPO_DIR/.venv/bin/python" ]]; then
    exec "$REPO_DIR/.venv/bin/python" "$REPO_DIR/main.py" "$@"
else
    exec python3 "$REPO_DIR/main.py" "$@"
fi
