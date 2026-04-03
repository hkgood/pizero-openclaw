#!/bin/bash
# ══════════════════════════════════════════════════════════════════
# pizero-openclaw 一键安装脚本
#
# 用法：
#   本地运行：./install.sh
#   一键安装（下载到文件再运行，有 TTY 支持）：
#     curl -fsSL https://raw.githubusercontent.com/hkgood/pizero-openclaw/main/install.sh -o /tmp/install.sh && chmod +x /tmp/install.sh && /tmp/install.sh
#
# ══════════════════════════════════════════════════════════════════
set -e

INSTALL_DIR="$HOME/pizero-openclaw"
GITHUB_REPO="hkgood/pizero-openclaw"
BRANCH="${INSTALL_BRANCH:-main}"

echo ""
echo "╔════════════════════════════════════════════════════╗"
echo "║   🟢 pizero-openclaw 一键安装                     ║"
echo "╚════════════════════════════════════════════════════╝"
echo ""

# ── 检测是否已在克隆目录内 ─────────────────────────────────────────
# 如果 main.py 存在，说明是从完整克隆目录运行的
if [[ -f "${BASH_SOURCE[0]%/*}/main.py" ]] || [[ -f "./main.py" ]]; then
  REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  exec "$REPO_DIR/setup.sh" "$@"
fi

# ── 下载安装脚本到临时文件 ─────────────────────────────────────────
echo "正在下载安装脚本..."
SCRIPT_TMP="/tmp/pizero-openclaw-install-$$.sh"

if ! curl -fsSL "https://raw.githubusercontent.com/$GITHUB_REPO/$BRANCH/install.sh" -o "$SCRIPT_TMP" 2>/dev/null; then
  echo "下载失败，尝试备用方式..."
else
  chmod +x "$SCRIPT_TMP"

  # ── 克隆或更新仓库 ───────────────────────────────────────────────
  if [[ -d "$INSTALL_DIR/.git" ]]; then
    echo "检测到已有安装目录: $INSTALL_DIR"
    cd "$INSTALL_DIR"
    # 检查目录是否完整
    if [[ ! -f "main.py" ]]; then
      echo "目录不完整，重新克隆..."
      cd /
      rm -rf "$INSTALL_DIR"
      echo "正在克隆代码仓库..."
      git clone --depth=1 -b "$BRANCH" "https://github.com/$GITHUB_REPO.git" "$INSTALL_DIR"
    else
      echo "更新代码..."
      if ! git pull origin "$BRANCH" 2>/dev/null; then
        echo "网络问题，更新失败，尝试重新克隆..."
        cd /
        rm -rf "$INSTALL_DIR"
        echo "正在克隆代码仓库..."
        git clone --depth=1 -b "$BRANCH" "https://github.com/$GITHUB_REPO.git" "$INSTALL_DIR"
      else
        echo "代码已是最新。"
      fi
    fi
  else
    echo "正在克隆代码仓库..."
    git clone --depth=1 -b "$BRANCH" "https://github.com/$GITHUB_REPO.git" "$INSTALL_DIR"
  fi

  # 把 setup.sh 放到仓库目录
  cp "$SCRIPT_TMP" "$INSTALL_DIR/install.sh"
  chmod +x "$INSTALL_DIR/install.sh"
  rm -f "$SCRIPT_TMP"

  echo ""
  echo "安装完成！现在运行配置向导..."
  echo ""
  sleep 1

  cd "$INSTALL_DIR"
  exec ./setup.sh "$@"
fi

# ── 备用：直接 clone 仓库（网络下载失败时）─────────────────────────
echo "下载失败，尝试直接克隆仓库..."
if [[ -d "$INSTALL_DIR/.git" ]]; then
  cd "$INSTALL_DIR"
  if [[ -f "setup.sh" ]]; then
    exec ./setup.sh "$@"
  fi
fi
echo "正在克隆代码仓库..."
git clone --depth=1 -b "$BRANCH" "https://github.com/$GITHUB_REPO.git" "$INSTALL_DIR"
cd "$INSTALL_DIR"
exec ./setup.sh "$@"
