#!/bin/bash
# ══════════════════════════════════════════════════════════════════
# pizero-openclaw 一键安装脚本
#
# 用法（任选一种）：
#   本地运行：./install.sh
#   一键安装：
#     curl -fsSL https://raw.githubusercontent.com/hkgood/pizero-openclaw/main/install.sh -o /tmp/install.sh && chmod +x /tmp/install.sh && /tmp/install.sh
#     bash <(curl -fsSL https://raw.githubusercontent.com/hkgood/pizero-openclaw/main/install.sh)
#
# 关键设计：不使用管道 (curl | bash)，而是下载到文件再执行，
# 这样脚本有真正的 TTY，read 交互可以正常工作。
# ══════════════════════════════════════════════════════════════════
set -e

INSTALL_DIR="$HOME/pizero-openclaw"
GITHUB_REPO="hkgood/pizero-openclaw"
BRANCH="${INSTALL_BRANCH:-main}"
INSTALL_SCRIPT_URL="https://raw.githubusercontent.com/$GITHUB_REPO/$BRANCH/install.sh"
SETUP_SCRIPT_URL="https://raw.githubusercontent.com/$GITHUB_REPO/$BRANCH/setup.sh"

echo ""
echo "╔════════════════════════════════════════════════════╗"
echo "║   🟢 pizero-openclaw 一键安装                     ║"
echo "╚════════════════════════════════════════════════════╝"
echo ""

# ── 检测是否已在克隆目录内 ─────────────────────────────────────────
# 如果 setup.sh 存在，说明是从本地克隆目录运行的
if [[ -f "${BASH_SOURCE[0]%/*}/setup.sh" ]] || [[ -f "./setup.sh" ]]; then
  REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  exec "$REPO_DIR/setup.sh" "$@"
fi

# ── 下载安装脚本到临时文件（关键：不使用管道！）───────────────────────
echo "正在下载安装脚本..."
SCRIPT_TMP="/tmp/pizero-openclaw-install-$$.sh"

if ! curl -fsSL "$INSTALL_SCRIPT_URL" -o "$SCRIPT_TMP" 2>/dev/null; then
  echo "下载失败，尝试备用地址..."
  # 备用：直接 clone 仓库
  if [[ -d "$INSTALL_DIR/.git" ]]; then
    echo "使用已有目录..."
  else
    echo "正在克隆代码仓库..."
    git clone --depth=1 -b "$BRANCH" "https://github.com/$GITHUB_REPO.git" "$INSTALL_DIR"
  fi
  cd "$INSTALL_DIR"
  if [[ -f setup.sh ]]; then
    exec ./setup.sh "$@"
  else
    echo "错误：setup.sh 不存在"
    exit 1
  fi
fi

echo "下载完成。"
chmod +x "$SCRIPT_TMP"

# ── 同样下载 setup.sh ────────────────────────────────────────────────
echo "正在下载 setup.sh..."
SETUP_TMP="/tmp/pizero-openclaw-setup-$$.sh"
if ! curl -fsSL "$SETUP_SCRIPT_URL" -o "$SETUP_TMP" 2>/dev/null; then
  echo "错误：无法下载 setup.sh"
  rm -f "$SCRIPT_TMP"
  exit 1
fi
chmod +x "$SETUP_TMP"

# 把 setup.sh 放到预期位置
mkdir -p "$INSTALL_DIR"
cp "$SETUP_TMP" "$INSTALL_DIR/setup.sh"
chmod +x "$INSTALL_DIR/setup.sh"
rm -f "$SETUP_TMP"

echo "安装完成！现在运行配置向导..."
echo ""
sleep 1

# ── 执行 setup.sh（文件执行，不是管道）─────────────────────────────
cd "$INSTALL_DIR"
exec ./setup.sh "$@"
