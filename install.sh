#!/bin/bash
# ══════════════════════════════════════════════════════════════════
# pizero-openclaw 一键安装脚本
# 用法（任选一种）：
#   本地运行（已在克隆目录内）：./install.sh
#   一键安装（任意目录）：
#     curl -fsSL https://raw.githubusercontent.com/hkgood/pizero-openclaw/main/install.sh | bash
#     curl -fsSL https://raw.githubusercontent.com/hkgood/pizero-openclaw/main/install.sh | bash -s -- --non-interactive [选项...]
# ══════════════════════════════════════════════════════════════════
set -e

# ── 检测是否在克隆目录内 ─────────────────────────────────────────
# 如果 setup.sh 存在，说明是从本地克隆目录运行的
if [[ -f "${BASH_SOURCE[0]%/*}/setup.sh" ]] || [[ -f "./setup.sh" ]]; then
  REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  exec "$REPO_DIR/setup.sh" "$@"
fi

# ── 从网络安装：克隆仓库到临时目录 ─────────────────────────────────
GITHUB_REPO="hkgood/pizero-openclaw"
INSTALL_DIR="$HOME/pizero-openclaw"
BRANCH="${INSTALL_BRANCH:-main}"

echo ""
echo "╔════════════════════════════════════════════════════╗"
echo "║   🟢 pizero-openclaw 一键安装                     ║"
echo "╚════════════════════════════════════════════════════╝"
echo ""

# 检测是否已有克隆
if [[ -d "$INSTALL_DIR/.git" ]]; then
  echo "检测到已有安装目录: $INSTALL_DIR"
  echo "更新代码..."
  cd "$INSTALL_DIR"
  if ! git pull origin "$BRANCH" 2>&1; then
    echo "网络问题，更新失败，尝试重新克隆..."
    cd /
    rm -rf "$INSTALL_DIR"
    echo "正在克隆代码仓库..."
    git clone --depth=1 -b "$BRANCH" "https://github.com/$GITHUB_REPO.git" "$INSTALL_DIR"
  else
    echo "代码已是最新。"
  fi
else
  echo "正在克隆代码仓库..."
  git clone --depth=1 -b "$BRANCH" "https://github.com/$GITHUB_REPO.git" "$INSTALL_DIR"
fi

echo ""
echo "安装完成！现在运行配置向导..."
echo ""
sleep 1

cd "$INSTALL_DIR"
exec ./setup.sh "$@"
