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

# ── TTY 检测：管道运行时自动切换非交互模式 ───────────────────────────────
# 如果 stdin 不是终端（curl | bash 场景），自动进入非交互模式
if [[ ! -t 0 ]]; then
  echo "[setup] 检测到非交互环境，自动切换到非交互模式。"
  echo "[setup] 如需交互式安装，请先下载脚本再运行："
  echo "  curl -fsSL <URL> -o install.sh && chmod +x install.sh && ./install.sh"
  echo ""
  NON_INTERACTIVE=true
fi

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OC_CFG="$HOME/.openclaw/openclaw.json"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'

# ── CLI 参数解析 ─────────────────────────────────────────────────
NON_INTERACTIVE=false
SKIP_DEPS=false
SKIP_CONFIG=false
SKIP_AUTOSTART=false
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
    --skip-autostart)
      SKIP_AUTOSTART=true
      shift
      ;;
    --autostart)
      ENABLE_AUTOSTART=true
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
      echo "  --skip-autostart     跳过自启动设置"
      echo "  --autostart          非交互模式下自动设置自启动"
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
  IS_DOCKER=false
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

  # 检测 Docker 环境
  if [[ -f /.dockerenv ]] || grep -q docker /proc/1/cgroup 2>/dev/null; then
    IS_DOCKER=true
    info "检测到 Docker 环境"
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
  echo "  平台:       $([[ "$IS_RPI" == "true" ]] && echo "Raspberry Pi" || [[ "$IS_DOCKER" == "true" ]] && echo "Docker" || echo "Desktop/Linux")"
  echo "  麦克风:     $([[ "$HAS_AUDIO_IN" == "true" ]] && echo "${GREEN}可用${NC}" || echo "${YELLOW}不可用${NC}")"
  echo "  扬声器:     $([[ "$HAS_AUDIO_OUT" == "true" ]] && echo "${GREEN}可用${NC}" || echo "${YELLOW}不可用${NC}")"
  if [[ "$IS_DOCKER" == "true" ]]; then
    echo ""
    warn "Docker 环境：需要配置音频设备映射（--device /dev/snd）或 ALSA 环境变量"
  fi
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

# ── 预检 sudo 权限 ─────────────────────────────────────────────
check_sudo() {
  if [[ "$IS_MAC" == "true" ]]; then
    return  # macOS 不需要 sudo
  fi
  if [[ "$EUID" == "0" ]]; then
    return  # 已以 root 运行
  fi
  if sudo -n true 2>/dev/null; then
    return  # sudo 已缓存
  fi
  echo ""
  info "此步骤需要 sudo 权限，请输入密码（如果没有 sudo 权限可跳过）..."
  if sudo -v; then
    log "sudo 权限验证成功"
  else
    warn "sudo 权限验证失败，部分安装可能受影响"
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
      else
        info "ffmpeg 已安装，跳过"
      fi
    else
      warn "Homebrew 未安装，跳过 ffmpeg"
    fi
    return
  fi

  # Linux / Raspberry Pi
  if command -v apt-get >/dev/null 2>&1; then
    # 预检 sudo
    check_sudo
    
    info "更新软件包列表..."
    if ! sudo apt-get update -qq 2>&1 | tail -3; then
      warn "apt-get update 失败，继续尝试安装..."
    fi
    
    info "安装系统包（python3-numpy, python3-pil, alsa-utils, sox, curl 等）..."
    local pkg_errors=0
    sudo apt-get install -y \
      python3-numpy \
      python3-pil \
      python3-pip \
      alsa-utils \
      sox \
      libsox-fmt-all \
      curl \
      git \
      2>&1 | grep -E "(Setting up|Erasing|Processing|Unable|Error)" || true
    
    if [[ $? -eq 0 ]]; then
      log "系统依赖安装完成"
    else
      warn "部分系统包安装失败，尝试继续..."
    fi
  fi
}

# ── 安装 Python 依赖 ───────────────────────────────────────────
install_python_deps() {
  step "安装 Python 依赖..."
  
  info "升级 pip..."
  $PYTHON_CMD -m pip install --upgrade pip 2>&1 | tail -2
  
  # 基础依赖
  info "安装基础依赖 (requirements.txt)..."
  local base_errors=0
  $PYTHON_CMD -m pip install -r "$REPO_DIR/requirements.txt" 2>&1 | tail -5 || base_errors=$?
  
  # 硬件依赖（如果检测到 Pi）
  if [[ "$IS_RPI" == "true" ]]; then
    info "Raspberry Pi 环境，安装硬件依赖 (requirements-pi.txt)..."
    if [[ -f "$REPO_DIR/requirements-pi.txt" ]]; then
      $PYTHON_CMD -m pip install -r "$REPO_DIR/requirements-pi.txt" 2>&1 | tail -5
    else
      warn "requirements-pi.txt 不存在，跳过硬件依赖"
    fi
  fi
  
  # 可选依赖
  if command -v sox >/dev/null 2>&1; then
    info "安装 sox Python 包..."
    $PYTHON_CMD -m pip install sox 2>&1 | tail -2 || true
  fi
  
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
      read token
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
    read api_key
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
    read api_key
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
  local warnings=0
  
  echo ""
  info "检查 Python 包..."
  
  # 验证核心 Python 依赖
  for pkg in numpy PIL dotenv requests; do
    if [[ "$pkg" == "PIL" ]]; then
      if ! $PYTHON_CMD -c "from PIL import Image; print('OK')" 2>/dev/null | grep -q OK; then
        error "Pillow 未安装或安装失败"
        ((errors++))
      else
        log "  Pillow ✓"
      fi
    else
      if ! $PYTHON_CMD -c "import $pkg; print('OK')" 2>/dev/null | grep -q OK; then
        error "  $pkg 未安装"
        ((errors++))
      else
        log "  $pkg ✓"
      fi
    fi
  done
  
  # 检查可选依赖
  echo ""
  info "检查可选依赖..."
  
  if [[ "$IS_RPI" == "true" ]]; then
    if ! $PYTHON_CMD -c "import RPi.GPIO" 2>/dev/null; then
      warn "  RPi.GPIO 未安装（硬件模式需要）"
      ((warnings++))
    else
      log "  RPi.GPIO ✓"
    fi
    
    if ! $PYTHON_CMD -c "import spidev" 2>/dev/null; then
      warn "  spidev 未安装（硬件模式需要）"
      ((warnings++))
    else
      log "  spidev ✓"
    fi
  fi
  
  # 检查 API Key
  echo ""
  if grep -q "DASHSCOPE_API_KEY\|OPENAI_API_KEY" "$REPO_DIR/.env" 2>/dev/null; then
    if grep -E "DASHSCOPE_API_KEY=\"\"|OPENAI_API_KEY=\"\"" "$REPO_DIR/.env" >/dev/null 2>&1; then
      warn ".env 中 API Key 为空，请填写"
      ((warnings++))
    else
      log "API Key 已配置 ✓"
    fi
  else
    warn ".env 中未配置 API Key"
    ((warnings++))
  fi
  
  # 汇总
  echo ""
  if [[ "$errors" -gt 0 ]]; then
    error "有 $errors 个错误，建议修复后再运行"
    info "手动修复依赖: pip install -r requirements.txt -r requirements-pi.txt"
  fi
  if [[ "$warnings" -gt 0 ]]; then
    warn "有 $warnings 个警告，不影响测试模式运行"
  fi
  if [[ "$errors" -eq 0 && "$warnings" -eq 0 ]]; then
    log "所有检查通过！"
  fi
  
  echo ""
}

# ── 启动应用 ───────────────────────────────────────────────────
launch_app() {
  step "启动应用..."
  local script="$REPO_DIR/run-openclaw.sh"
  if [[ ! -f "$script" ]]; then
    echo "run-openclaw.sh 未找到，请手动运行："
    echo "  cd ~/pizero-openclaw && ./run-openclaw.sh"
    return
  fi
  chmod +x "$script" 2>/dev/null
  if [[ "$IS_RPI" == "true" && "$HAS_WHISPLAY" == "true" ]]; then
    info "启动硬件模式..."
  else
    info "启动测试模式..."
  fi
  echo ""
  echo "提示：按 Ctrl+Z 可后台运行，Ctrl+C 退出。"
  echo ""
  # exec 替换当前进程（成功=保持在app，失败=返回后打印手动运行提示）
  # 注意：set -e 下 exec 失败会导致脚本退出，所以先检查文件存在
  exec "$script" && exit 0 || {
    echo ""
    echo "启动失败。请手动运行："
    echo "  cd ~/pizero-openclaw && ./run-openclaw.sh"
  }
}

# ── 设置 systemd 自启动 ───────────────────────────────────────────
setup_autostart() {
  # 仅支持 Linux systemd（Raspberry Pi / Debian / Ubuntu 等）
  if [[ "$IS_MAC" == "true" ]] || [[ ! -d /run/systemd/system ]]; then
    return
  fi
  
  step "设置开机自启动..."
  
  # 预检 sudo
  check_sudo
  
  local svc_file="$REPO_DIR/pizero-openclaw.service"
  if [[ ! -f "$svc_file" ]]; then
    warn "未找到 $svc_file，跳过自启动设置"
    return
  fi
  
  # 替换 service 文件中的路径占位符
  local current_user="$(whoami)"
  local current_group="$(id -gn)"
  local svc_tmp="/tmp/pizero-openclaw-auto-$$.service"
  
  info "配置服务：用户=$current_user, 路径=$REPO_DIR"
  
  sed \
    -e "s|^User=.*|User=$current_user|" \
    -e "s|^Group=.*|Group=$current_group|" \
    -e "s|^WorkingDirectory=.*|WorkingDirectory=$REPO_DIR|" \
    -e "s|^ExecStart=.*|ExecStart=/usr/bin/python3 $REPO_DIR/main.py|" \
    -e "s|^EnvironmentFile=.*|EnvironmentFile=$REPO_DIR/.env|" \
    "$svc_file" > "$svc_tmp"
  
  echo ""
  info "安装 systemd 服务..."
  sudo cp "$svc_tmp" /etc/systemd/system/pizero-openclaw.service
  sudo systemctl daemon-reload
  
  echo ""
  info "启用开机自启..."
  if sudo systemctl enable pizero-openclaw 2>&1 | grep -q "Created symlink"; then
    log "自启动已启用"
  else
    warn "启用结果不明确，继续..."
  fi
  
  echo ""
  if _confirm "现在启动服务并查看日志？" "n"; then
    echo ""
    info "启动服务..."
    sudo systemctl restart pizero-openclaw
    sleep 3
    echo ""
    info "最近日志（Ctrl+C 退出）:"
    sudo journalctl -u pizero-openclaw -f --no-pager
  fi
  
  rm -f "$svc_tmp"
  log "自启动设置完成！"
  echo ""
  echo "常用命令："
  echo "  sudo systemctl status pizero-openclaw   # 查看状态"
  echo "  sudo systemctl restart pizero-openclaw   # 重启"
  echo "  sudo journalctl -u pizero-openclaw -f    # 查看日志"
  echo "  sudo systemctl disable pizero-openclaw  # 取消自启"
  echo ""
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

  # ── 自启动设置 ────────────────────────────────────────────────────
  if [[ "$SKIP_AUTOSTART" == "true" ]]; then
    info "跳过自启动设置（--skip-autostart）"
  elif [[ "$IS_RPI" == "true" ]] && [[ -d /run/systemd/system ]]; then
    echo ""
    if [[ "$NON_INTERACTIVE" == "true" ]]; then
      if [[ "$ENABLE_AUTOSTART" == "true" ]]; then
        setup_autostart
      else
        info "跳过自启动设置（非交互模式）"
        info "如需设置自启动: ENABLE_AUTOSTART=true ./setup.sh --non-interactive"
      fi
    else
      if _confirm "是否设置开机自启动（systemd）？" "n"; then
        setup_autostart
      else
        info "跳过自启动设置"
      fi
    fi
  fi

  echo ""
  echo -e "${CYAN}╔════════════════════════════════════════════════════╗${NC}"
  echo -e "${CYAN}║            安装完成！                              ║${NC}"
  echo -e "${CYAN}╚════════════════════════════════════════════════════╝${NC}"
  echo ""
  echo "下一步："
  echo ""
  echo "  cd ~/pizero-openclaw          # 进入项目目录（重要！）"
  echo "  ./run-openclaw.sh              # 运行"
  echo "  cat README.md                  # 查看帮助"
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
