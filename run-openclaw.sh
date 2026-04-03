#!/bin/bash
# Wrapper script: loads .env, then runs main.py.
#
# Supports both formats in .env:
#   export KEY=value    ← bash-style (from .env.example)
#   KEY=value           ← systemd-style
#
# .env values with surrounding quotes ("value" or 'value') are handled correctly.
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
    IS_RPI=false
    if [[ -f /proc/device-tree/model ]] && grep -qi "raspberry" /proc/device-tree/model 2>/dev/null; then
        IS_RPI=true
    fi
    HAS_WHISPLAY=false
    if [[ -d "$HOME/Whisplay/Driver" ]] || [[ -d "/opt/WhisPlay" ]]; then
        HAS_WHISPLAY=true
    fi
    if [[ "$(uname)" == "Darwin" ]] || [[ "$IS_RPI" == "false" ]] || [[ "$HAS_WHISPLAY" == "false" ]]; then
        echo "[run-openclaw] 自动进入测试模式（未检测到 WhisPlay 硬件）"
        TEST_MODE=true
    else
        TEST_MODE=false
    fi
fi
export TEST_MODE

# ── 用 Python 生成安全的 shell 导出脚本，再 source ─────────────────────
# 写入临时文件，用 Python 正确解析 .env 的引号问题
EXPORT_SCRIPT="/tmp/pizero-openclaw-env-$$.sh"

python3 - "$ENVFILE" > "$EXPORT_SCRIPT" << 'PYEOF'
import sys, os, shlex
with open(sys.argv[1]) as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:]
        if "=" not in line:
            continue
        key, raw = line.split("=", 1)
        key = key.strip()
        value = raw.strip()
        # Remove surrounding double or single quotes
        if len(value) >= 2:
            if (value[0] == '"' and value[-1] == '"') or \
               (value[0] == "'" and value[-1] == "'"):
                value = value[1:-1]
        # Escape for safe shell output
        safe_val = shlex.quote(value)
        print(f"export {key}={safe_val}")
PYEOF

# Source the generated script (all values are safely quoted)
source "$EXPORT_SCRIPT"
rm -f "$EXPORT_SCRIPT"

# Prefer venv python if .venv exists, otherwise fall back to system python
if [[ -x "$REPO_DIR/.venv/bin/python" ]]; then
    exec "$REPO_DIR/.venv/bin/python" "$REPO_DIR/main.py" "$@"
else
    exec python3 "$REPO_DIR/main.py" "$@"
fi
