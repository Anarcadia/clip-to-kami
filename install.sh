#!/usr/bin/env bash
# clip-to-kami 一键安装脚本（macOS / Linux）
# 用法：bash install.sh

set -e

GREEN='\033[32m'
RED='\033[31m'
YELLOW='\033[33m'
CYAN='\033[36m'
BOLD='\033[1m'
RESET='\033[0m'

log()  { echo -e "${CYAN}[clip-to-kami]${RESET} $*"; }
ok()   { echo -e "  ${GREEN}✅${RESET} $*"; }
warn() { echo -e "  ${YELLOW}⚠️${RESET}  $*"; }
err()  { echo -e "  ${RED}❌${RESET} $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "${BOLD}=== clip-to-kami 安装 ===${RESET}"

# ---- OS 检测 ----
OS="$(uname -s)"
log "检测到系统：$OS"
case "$OS" in
  Darwin) PLATFORM="macos" ;;
  Linux)  PLATFORM="linux" ;;
  MINGW*|MSYS*|CYGWIN*)
    err "Windows 请在 WSL2 内运行此脚本"
    exit 1 ;;
  *)
    err "未知系统：$OS"
    exit 1 ;;
esac

# ---- Python ----
log "检查 Python"
if ! command -v python3 >/dev/null 2>&1; then
  err "Python 3 未安装"
  [[ "$PLATFORM" == "macos" ]] && echo "     → brew install python@3.12"
  [[ "$PLATFORM" == "linux" ]] && echo "     → sudo apt install python3 python3-pip"
  exit 1
fi
PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PY_MAJOR="$(echo "$PY_VER" | cut -d. -f1)"
PY_MINOR="$(echo "$PY_VER" | cut -d. -f2)"
if [[ "$PY_MAJOR" -lt 3 ]] || { [[ "$PY_MAJOR" -eq 3 ]] && [[ "$PY_MINOR" -lt 9 ]]; }; then
  err "Python $PY_VER 过低，需要 ≥ 3.9"
  exit 1
fi
ok "Python $PY_VER"

# ---- 系统库（macOS）----
if [[ "$PLATFORM" == "macos" ]]; then
  log "检查 Homebrew 与系统库"
  if ! command -v brew >/dev/null 2>&1; then
    err "Homebrew 未安装"
    echo "     → 访问 https://brew.sh 安装后重试"
    exit 1
  fi
  ok "Homebrew: $(command -v brew)"

  MISSING=()
  for pkg in pango gdk-pixbuf cairo; do
    if brew list --formula 2>/dev/null | grep -qx "$pkg"; then
      ok "brew 包 $pkg 已安装"
    else
      MISSING+=("$pkg")
    fi
  done
  if [[ ${#MISSING[@]} -gt 0 ]]; then
    log "安装缺失的 brew 包：${MISSING[*]}"
    brew install "${MISSING[@]}"
  fi
fi

# ---- 系统库（Linux）----
if [[ "$PLATFORM" == "linux" ]]; then
  log "提示：Linux 需要 apt/yum 包 libpango-1.0-0、libgdk-pixbuf-2.0-0、libcairo2"
  warn "示例（Debian/Ubuntu）：sudo apt install -y libpango-1.0-0 libpangoft2-1.0-0 libgdk-pixbuf-2.0-0 libcairo2"
  warn "脚本不自动执行 sudo，请确认这些包已装"
fi

# ---- pip 包 ----
log "安装 Python 依赖（pip）"
if [[ ! -f requirements.txt ]]; then
  err "requirements.txt 不存在于 $SCRIPT_DIR"
  exit 1
fi
python3 -m pip install --upgrade pip >/dev/null
python3 -m pip install -r requirements.txt
ok "pip 包已就绪"

# ---- Playwright 浏览器 ----
log "安装 Playwright Chromium"
python3 -m playwright install chromium
ok "Chromium 已就绪"

# ---- 运行 doctor ----
echo
log "运行环境自检"
if python3 scripts/doctor.py; then
  echo
  echo -e "${BOLD}${GREEN}✓ 安装完成！${RESET}"
  echo -e "${CYAN}  试试：python3 scripts/convert.py \"https://example.com/\" ${RESET}"
else
  echo
  echo -e "${BOLD}${YELLOW}⚠ 环境有残留问题，请按 doctor.py 输出修复${RESET}"
  exit 1
fi
