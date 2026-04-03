#!/bin/bash
# ══════════════════════════════════════════════════════════════════
# pizero-openclaw 自动化安装配置脚本
# 支持：硬件检测 → 依赖安装 → API Key 配置 → 测试模式
#
# 用法：
#   ./setup.sh                    # 交互式向导
#   ./setup.sh --non-interactive # 完全非交互（CI/自动化）
#
# 非交互模式下可通过环境变量传入配置：
#   DASHSCOPE_API_KEY=xxx ./setup.sh --non-interactive
#   OPENAI_API_KEY=xxx PROVIDER=openai ./setup.sh --non-interactive
# ══════════════════════════════════════════════════════════════════
set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OC_CFG="$HOME/.openclaw/openclaw.json"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'

# ── CLI 参数解析 ─────────────────────────────────────────────────
NON_INTERACTIVE=false
SKIP_DEPS=false
SKIP_CONFIG=false
AUTO_LAUNCH=false
PROVIDER_OVERRIDE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --non-interactive|-y|-n)
      NON_INTERACTIVE=true
      shift
      ;;
    --skip-deps)
      SKIP_DEPS=true
      shift
      ;;
    --skip-config)
      SKIP_CONFIG=true
      shift
      ;;
    --auto-launch)
      AUTO_LAUNCH=true
      shift
      ;;
    --provider)
      PROVIDER_OVERRIDE="$2"
      shift 2
      ;;
    --help|-h)
      echo "用法: $0 [选项]"
      echo "  --non-interactive   完全非交互（CI/自动化）"
      echo "  --skip-deps          跳过依赖安装"
      echo "  --skip-config        跳过配置步骤"
      echo "  --auto-launch        安装完自动启动"
      echo "  --provider <bailian|openai>  指定 AI 提供商"
      exit 0
      ;;
    --tty)
      # 兼容 install.sh 传入的 --tty 参数，忽略即可
      shift
      ;;
    *)
      echo "未知参数: $1"
      echo "用法: $0 --help"
      exit 1
      ;;
  esac
done

_ask() {
  # 交互模式：弹出提示让用户输入
  # 非交互模式：跳过（用于可选步骤）
  [[ "$NON_INTERACTIVE" == "true" ]] && return 1
  return 0
}

_confirm() {
  # 非交互模式：使用默认值
  [[ "$NON_INTERACTIVE" == "true" ]] && return 0
  local prompt="${1:-继续？} [Y/n]: " default="${2:-y}"
  local ans
  read -p "$prompt" ans
  ans="${ans:-$default}"
  [[ "$ans" =~ ^[Yy]$ ]]
}

banner() {
  echo ""
  echo -e "${CYAN}╔════════════════════════════════════════════════════╗${NC}"
  echo -e "${CYAN}║   🟢 pizero-openclaw 自动化安装向导                 ║${NC}"
  echo -e "${CYAN}╚════════════════════════════════════════════════════╝${NC}"
  echo ""
}

log()   { echo -e "${GREEN}✅ $1${NC}"; }
warn()  { echo -e "${YELLOW}⚠️  $1${NC}"; }
error() { echo -e "${RED}❌ $1${NC}"; }
info()  { echo -e "${BLUE}ℹ️  $1${NC}"; }
step()  { echo -e "${CYAN}▶ $1${NC}"; }

# ── 检测硬件平台 ───────────────────────────────────────────────
detect_platform() {
  info "检测硬件平台..."
  
  IS_RPI=false
  IS_MAC=false
  IS_LINUX=false
  HAS_WHISPLAY=false
  HAS_AUDIO_IN=false
  HAS_AUDIO_OUT=false

  # 检测操作系统
  if [[ "$(uname)" == "Darwin" ]]; then
    IS_MAC=true
    info "平台: macOS"
  elif [[ -f /proc/device-tree/model ]] && grep -qi "raspberry" /proc/device-tree/model 2>/dev/null; then
    IS_RPI=true
    info "平台: Raspberry Pi"
  elif [[ -f /proc/device-tree/model ]]; then
    IS_LINUX=true
    info "平台: Linux (非 Pi)"
  else
    IS_LINUX=true
    info "平台: Linux"
  fi

  # 检测音频设备
  if [[ "$IS_MAC" == "true" ]]; then
    if (command -v parec >/dev/null 2>&1 || command -v ffmpeg >/dev/null 2>&1); then
      HAS_AUDIO_IN=true
    fi
    if command -v aplay >/dev/null 2>&1 || command -v ffplay >/dev/null 2>&1; then
      HAS_AUDIO_OUT=true
    fi
  else
    if [[ -d /proc/asound ]] || command -v arecord >/dev/null 2>&1; then
      if [[ -f /proc/asound/cards ]]; then
        HAS_AUDIO_IN=true
        HAS_AUDIO_OUT=true
      fi
    fi
  fi

  # 汇总
  echo ""
  echo "硬件检测结果:"
  echo "  平台:       $([[ "$IS_RPI" == "true" ]] && echo "Raspberry Pi" || echo "Desktop")"
  echo "  麦克风:     $([[ "$HAS_AUDIO_IN" == "true" ]] && echo "${GREEN}可用${NC}" || echo "${YELLOW}不可用${NC}")"
  echo "  扬声器:     $([[ "$HAS_AUDIO_OUT" == "true" ]] && echo "${GREEN}可用${NC}" || echo "${YELLOW}不可用${NC}")"
  echo ""
}

# ── 检测 WhisPlay（安装依赖后）──────────────────────────────────────────────
detect_whisplay() {
  step "检测 WhisPlay 硬件..."
  
  HAS_WHISPLAY=false
  if [[ -d "$HOME/Whisplay/Driver" ]] || [[ -d "/opt/WhisPlay" ]] || find /usr/local/lib /usr/lib -name "WhisPlay*" -type d 2>/dev/null | grep -q .; then
    HAS_WHISPLAY=true
    log "检测到 WhisPlay 硬件"
  else
    warn "未检测到 WhisPlay 硬件，将以测试模式运行"
  fi
  
  echo "  WhisPlay:   $([[ "$HAS_WHISPLAY" == "true" ]] && echo "${GREEN}已安装${NC}" || echo "${YELLOW}未检测到${NC}")"
  echo ""
}

# ── 检查 Python 版本 ───────────────────────────────────────────
check_python() {
  step "检查 Python..."
  PYTHON_CMD=""
  for py in python3 python3.13 python3.12 python3.11 python3.10 python3.9 python; do
    if ! command -v $py >/dev/null 2>&1; then
      continue
    fi
    # 用 Python 自身判断版本，完全避免 bc/awk/dot 数字兼容问题
    # 思路：让 Python 输出一行 "OK" 表示通过，否则输出 "FAIL"
    RESULT=$($py -c "
import sys
major, minor = sys.version_info.major, sys.version_info.minor
if major > 3 or (major == 3 and minor >= 9):
    print('OK')
else:
    print('FAIL')
" 2>/dev/null)
    if [[ "$RESULT" == "OK" ]]; then
      PYTHON_CMD=$py
      PY_VER=$($py -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
      log "Python: $PY_VER"
      break
    fi
  done
  if [[ -z "$PYTHON_CMD" ]]; then
    error "需要 Python 3.9+，请先安装"
    exit 1
  fi
}

# ── 安装系统依赖 ───────────────────────────────────────────────
install_system_deps() {
  step "安装系统依赖..."
  
  if [[ "$IS_MAC" == "true" ]]; then
    if command -v brew >/dev/null 2>&1; then
      # macOS: 用 ffmpeg 替代 arecord/aplay
      if ! command -v ffmpeg >/dev/null 2>&1; then
        log "安装 ffmpeg (用于音频处理)..."
        brew install ffmpeg
      fi
    else
      warn "Homebrew 未安装，跳过 ffmpeg"
    fi
    return
  fi

  # Linux / Raspberry Pi
  if command -v apt-get >/dev/null 2>&1; then
    info "安装系统包 (可能需要 sudo 密码)..."
    sudo apt-get update -qq
    sudo apt-get install -y -qq \
      python3-numpy \
      python3-pil \
      python3-pip \
      alsa-utils \
      sox \
      libsox-fmt-all \
      curl \
      2>/dev/null || true
    log "系统依赖安装完成"
  fi
}

# ── 安装 Python 依赖 ───────────────────────────────────────────
install_python_deps() {
  step "安装 Python 依赖..."
  
  $PYTHON_CMD -m pip install --upgrade pip -q 2>/dev/null || true
  
  # 基础依赖
  $PYTHON_CMD -m pip install -q -r "$REPO_DIR/requirements.txt" 2>/dev/null || true
  
  # 硬件依赖（如果检测到 Pi）
  if [[ "$IS_RPI" == "true" ]]; then
    info "检测到 Raspberry Pi，安装硬件依赖..."
    $PYTHON_CMD -m pip install -q RPi.GPIO spidev 2>/dev/null || true
    log "硬件依赖安装完成"
  fi
  
  # 可选依赖
  $PYTHON_CMD -m pip install -q sox 2>/dev/null || true
  
  log "Python 依赖安装完成"
}

# ── 配置 API Key ───────────────────────────────────────────────
configure_api_keys() {
  step "配置 API Key..."

  # 复制模板
  if [[ ! -f "$REPO_DIR/.env" ]]; then
    if [[ -f "$REPO_DIR/.env.example" ]]; then
      cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
      log "已创建 .env 文件"
    fi
  fi

  # ── 确定 Provider ──────────────────────────────────────────────
  if [[ -n "$PROVIDER_OVERRIDE" ]]; then
    provider_choice="$PROVIDER_OVERRIDE"
  elif [[ "$NON_INTERACTIVE" == "true" ]]; then
    # 非交互模式：从环境变量或默认值决定
    if [[ -n "$DASHSCOPE_API_KEY" ]]; then
      provider_choice="bailian"
    elif [[ -n "$OPENAI_API_KEY" ]]; then
      provider_choice="openai"
    else
      provider_choice="bailian"  # 默认百炼
    fi
  else
    echo ""
    echo -e "${CYAN}请选择 AI 提供商:${NC}"
    echo "  1) 阿里云百炼 (Bailian) — 默认，推荐"
    echo "  2) OpenAI — 备选"
    echo ""
    read -p "请输入选择 [1]: " provider_choice
    provider_choice="${provider_choice:-1}"
  fi

  # ── 写入 .env ──────────────────────────────────────────────────
  if [[ "$provider_choice" == "bailian" ]] || [[ "$provider_choice" == "1" ]]; then
    configure_bailian
  else
    configure_openai
  fi

  # ── OpenClaw Token ─────────────────────────────────────────────
  if [[ "$NON_INTERACTIVE" == "true" && -z "$OPENCLAW_TOKEN" ]]; then
    warn "OPENCLAW_TOKEN 未设置，跳过（稍后手动配置 .env）"
  else
    echo ""
    if [[ "$NON_INTERACTIVE" == "true" ]]; then
      _write_env "OPENCLAW_TOKEN" "$OPENCLAW_TOKEN"
    else
      echo -e "${CYAN}OpenClaw Gateway 配置:${NC}"
      echo -n "OpenClaw Token (可在 http://localhost:18789 配置页获取): "
      read -s token
      echo ""
      if [[ -n "$token" ]]; then
        _write_env "OPENCLAW_TOKEN" "$token"
      fi
    fi
  fi

  # ── OpenClaw Base URL ──────────────────────────────────────────
  local base_url="${OPENCLAW_BASE_URL:-http://localhost:18789}"
  if [[ "$NON_INTERACTIVE" == "false" ]]; then
    echo ""
    echo -e "${CYAN}OpenClaw Gateway 地址:${NC}"
    read -p "OpenClaw Base URL [$base_url]: " input_url
    base_url="${input_url:-$base_url}"
  fi
  _write_env "OPENCLAW_BASE_URL" "$base_url"

  log "API 配置完成"
}

# 辅助函数：安全写入 .env（不暴露 Key 内容）
_write_env() {
  local key="$1" value="$2"
  if [[ -z "$value" ]]; then
    return
  fi
  if grep -q "^export $key=" "$REPO_DIR/.env" 2>/dev/null; then
    sed -i.bak "s|^export $key=.*|export $key=\"$value\"|" "$REPO_DIR/.env"
  elif grep -q "^$key=" "$REPO_DIR/.env" 2>/dev/null; then
    sed -i.bak "s|^$key=.*|$key=\"$value\"|" "$REPO_DIR/.env"
  else
    echo "export $key=\"$value\"" >> "$REPO_DIR/.env"
  fi
}

configure_bailian() {
  if [[ "$NON_INTERACTIVE" == "true" ]]; then
    api_key="${DASHSCOPE_API_KEY:-}"
    if [[ -n "$api_key" ]]; then
      info "使用环境变量 DASHSCOPE_API_KEY"
      _write_env "DASHSCOPE_API_KEY" "$api_key"
    else
      warn "DASHSCOPE_API_KEY 未设置，跳过（稍后手动配置）"
    fi
  else
    echo ""
    echo -e "${CYAN}阿里云百炼配置:${NC}"
    echo "(获取地址: https://bailian.console.aliyun.com/)"
    echo ""
    echo -n "百炼 API Key: "
    read -s api_key
    echo ""
    if [[ -n "$api_key" ]]; then
      _write_env "DASHSCOPE_API_KEY" "$api_key"
    fi
  fi

  _write_env "STT_PROVIDER" "funasr"
  _write_env "TTS_PROVIDER" "bailian"
  log "百炼配置完成"
}

configure_openai() {
  if [[ "$NON_INTERACTIVE" == "true" ]]; then
    api_key="${OPENAI_API_KEY:-}"
    if [[ -n "$api_key" ]]; then
      info "使用环境变量 OPENAI_API_KEY"
      _write_env "OPENAI_API_KEY" "$api_key"
    else
      warn "OPENAI_API_KEY 未设置，跳过（稍后手动配置）"
    fi
  else
    echo ""
    echo -e "${CYAN}OpenAI 配置:${NC}"
    echo ""
    echo -n "OpenAI API Key: "
    read -s api_key
    echo ""
    if [[ -n "$api_key" ]]; then
      _write_env "OPENAI_API_KEY" "$api_key"
    fi
  fi

  _write_env "STT_PROVIDER" "openai"
  _write_env "TTS_PROVIDER" "openai"
  log "OpenAI 配置完成"
}

# ── 启动模式选择 ───────────────────────────────────────────────
choose_mode() {
  echo ""
  step "选择运行模式..."
  echo ""
  
  if [[ "$IS_RPI" == "true" && "$HAS_WHISPLAY" == "true" ]]; then
    info "检测到完整硬件环境，将以【硬件模式】运行"
    echo "export TEST_MODE=\"false\"" >> "$REPO_DIR/.env"
    echo "export ENABLE_TTS=\"true\"" >> "$REPO_DIR/.env"
  else
    echo -e "${YELLOW}⚠️  未检测到完整硬件环境${NC}"
    echo ""
    echo "  1) 测试模式 — 在 Mac/Linux 上模拟 UI，用文本输入测试 LLM"
    echo "  2) 跳过 — 不运行，稍后手动启动"
    echo ""
    read -p "请选择 [1]: " mode_choice
    mode_choice="${mode_choice:-1}"
    
    if [[ "$mode_choice" == "1" ]]; then
      log "进入测试模式"
      echo "export TEST_MODE=\"true\"" >> "$REPO_DIR/.env"
      echo "export ENABLE_TTS=\"false\"" >> "$REPO_DIR/.env"
    else
      info "已跳过"
    fi
  fi
}

# ── 验证安装 ───────────────────────────────────────────────────
verify_install() {
  step "验证安装..."
  
  local errors=0
  
  # 验证 Python 依赖
  if ! $PYTHON_CMD -c "import numpy" 2>/dev/null; then
    error "numpy 未安装"
    ((errors++))
  fi
  if ! $PYTHON_CMD -c "from PIL import Image" 2>/dev/null; then
    error "Pillow 未安装"
    ((errors++))
  fi
  if ! $PYTHON_CMD -c "import dotenv" 2>/dev/null; then
    error "python-dotenv 未安装"
    ((errors++))
  fi
  if ! $PYTHON_CMD -c "import requests" 2>/dev/null; then
    error "requests 未安装"
    ((errors++))
  fi
  
  if [[ "$errors" -eq 0 ]]; then
    log "Python 依赖验证通过"
  else
    warn "有 $errors 个依赖问题，建议运行: pip install -r requirements.txt"
  fi
  
  # 验证 .env
  if [[ -f "$REPO_DIR/.env" ]]; then
    log ".env 配置文件已就绪"
  else
    warn ".env 文件不存在"
  fi
  
  echo ""
}

# ── 启动应用 ───────────────────────────────────────────────────
launch_app() {
  step "启动应用..."
  
  if [[ "$IS_RPI" == "true" && "$HAS_WHISPLAY" == "true" ]]; then
    info "启动硬件模式..."
    cd "$REPO_DIR"
    ./run-openclaw.sh
  else
    # 测试模式
    if grep -q "TEST_MODE=true" "$REPO_DIR/.env" 2>/dev/null; then
      info "启动测试模式..."
      cd "$REPO_DIR"
      ./run-openclaw.sh
    else
      info "安装完成，稍后手动运行: ./run-openclaw.sh"
    fi
  fi
}

# ── 主流程 ─────────────────────────────────────────────────────
main() {
  banner

  detect_platform
  check_python

  # 创建 .env（如果不存在）
  if [[ ! -f "$REPO_DIR/.env" ]]; then
    if [[ -f "$REPO_DIR/.env.example" ]]; then
      cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
      log "已创建 .env 文件"
    fi
  fi

  # ── 依赖安装 ──────────────────────────────────────────────────────
  if [[ "$SKIP_DEPS" == "true" ]]; then
    info "跳过依赖安装（--skip-deps）"
  else
    echo ""
    if _confirm "是否安装依赖？" "y"; then
      install_system_deps
      install_python_deps
      detect_whisplay
    else
      info "跳过依赖安装"
    fi
  fi

  # ── API 配置 ──────────────────────────────────────────────────────
  if [[ "$SKIP_CONFIG" == "true" ]]; then
    info "跳过 API 配置（--skip-config）"
  else
    echo ""
    if _confirm "是否配置 API Key？" "y"; then
      configure_api_keys
    else
      info "跳过 API 配置"
    fi
  fi

  choose_mode
  verify_install

  echo ""
  echo -e "${CYAN}╔════════════════════════════════════════════════════╗${NC}"
  echo -e "${CYAN}║            安装完成！                              ║${NC}"
  echo -e "${CYAN}╚════════════════════════════════════════════════════╝${NC}"
  echo ""
  echo "下一步："
  echo "  1) 直接运行: ./run-openclaw.sh"
  echo "  2) 查看帮助: cat README.md"
  echo "  3) 配置 systemd 服务: sudo cp pizero-openclaw.service /etc/systemd/system/"
  echo ""

  if [[ "$AUTO_LAUNCH" == "true" ]]; then
    launch_app
  else
    if _confirm "现在启动应用？" "n"; then
      launch_app
    fi
  fi
}

main "$@"
