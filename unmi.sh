#!/usr/bin/env bash
#===============================================================================
# unmi_TGtool 一键安装脚本
#
# 推荐用法（process substitution，stdin 仍是终端，可正常交互）：
#   bash <(curl -sL https://raw.githubusercontent.com/unmime/unmi_TGtool/main/unmi.sh)
#
# 也兼容管道方式（脚本内 read 强制从 /dev/tty 读，依然可交互）：
#   curl -sL https://raw.githubusercontent.com/unmime/unmi_TGtool/main/unmi.sh | bash
#
# 流程：艺术字 -> 环境检查 -> 下载框架 -> 装 unmi 控制台 -> 引导添加第一个机器人
#
# 装完得到什么：
#   · /opt/unmi_TGtool      代码框架（所有机器人共享）
#   · /usr/local/bin/unmi   控制台命令（默认 unmi，可在面板里改成别的名字）
#   · 你的第一个机器人（在引导里配置并启动）
#===============================================================================
set -euo pipefail

# ---- 常量 ----
VERSION="v1.0.0.2"
REPO="unmime/unmi_TGtool"
TAR_URL="https://github.com/${REPO}/releases/download/${VERSION}/unmi_TGtool.tar.gz"
APP_DIR="/opt/unmi_TGtool"

# ---- 颜色（非终端时自动关闭）----
if [ -t 1 ]; then
  C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'
  C_CYAN=$'\033[36m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'
  C_RED=$'\033[31m'; C_PURPLE=$'\033[35m'
else
  C_RESET=""; C_BOLD=""; C_DIM=""; C_CYAN=""; C_GREEN=""; C_YELLOW=""; C_RED=""; C_PURPLE=""
fi
# 从终端读一行。优先 /dev/tty（兼容 `curl ... | bash` 时 stdin 是管道的情况），
# 没有控制终端就退回 stdin，都读不到返回 1 —— 本脚本开了 set -e，裸 read 失败会直接中断安装。
tty_read() {
  local __v="$1"; shift
  printf '%s' "$*" > /dev/tty 2>/dev/null || printf '%s' "$*"
  # shellcheck disable=SC2229  # "$__v" 是故意的：按调用方传入的变量名动态赋值
  read -r "$__v" < /dev/tty 2>/dev/null || read -r "$__v" || return 1
}

info()  { echo -e "${C_CYAN}  [i]${C_RESET} $*"; }
ok()    { echo -e "${C_GREEN}  [✓]${C_RESET} $*"; }
warn()  { echo -e "${C_YELLOW}  [!]${C_RESET} $*"; }
err()   { echo -e "${C_RED}  [✗]${C_RESET} $*" >&2; }
step()  { echo -e "\n${C_PURPLE}${C_BOLD}▶ $*${C_RESET}"; }

# ---- 艺术字 ----
banner() {
  echo -e "${C_CYAN}"
  cat <<'EOF'
  ██╗   ██╗███╗   ██╗███╗   ███╗██╗
  ██║   ██║████╗  ██║████╗ ████║██║
  ██║   ██║██╔██╗ ██║██╔████╔██║██║
  ██║   ██║██║╚██╗██║██║╚██╔╝██║██║
  ╚██████╔╝██║ ╚████║██║ ╚═╝ ██║██║
   ╚═════╝ ╚═╝  ╚═══╝╚═╝     ╚═╝╚═╝
EOF
  echo -e "${C_RESET}"
  echo -e "  ${C_BOLD}unmi_TGtool${C_RESET}  ${C_DIM}集中管理本机的 Telegram 机器人${C_RESET}"
  echo -e "  ${C_CYAN}github.com/${REPO}${C_RESET}   ${C_YELLOW}${VERSION}${C_RESET}"
}

need_root() {
  if [ "$(id -u)" -ne 0 ]; then
    err "需要 root 权限（要写 /opt、/etc、systemd）"
    echo    "    请改用：sudo bash <(curl -sL .../unmi.sh)"
    exit 1
  fi
}

check_env() {
  step "环境检查"
  local missing=0
  command -v python3 >/dev/null 2>&1 || { err "缺少 python3"; missing=1; }
  command -v tar     >/dev/null 2>&1 || { err "缺少 tar";     missing=1; }
  if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
    err "需要 curl 或 wget 之一"; missing=1
  fi
  [ "$missing" = "1" ] && { err "环境检查未通过"; exit 1; }
  ok "python3 $(python3 -V 2>&1 | awk '{print $2}')"
}

# ---- 下载并解压代码框架 ----
download() {
  step "下载 unmi_TGtool ${VERSION}"
  TMP_DIR="$(mktemp -d)"
  trap 'rm -rf "$TMP_DIR"' EXIT
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL --connect-timeout 15 "$TAR_URL" -o "$TMP_DIR/pkg.tar.gz" \
      || { err "下载失败：$TAR_URL"; exit 1; }
  else
    wget -q --timeout=15 "$TAR_URL" -O "$TMP_DIR/pkg.tar.gz" \
      || { err "下载失败：$TAR_URL"; exit 1; }
  fi
  ok "已下载 $(du -h "$TMP_DIR/pkg.tar.gz" | awk '{print $1}')"

  step "安装代码框架到 $APP_DIR"
  mkdir -p "$APP_DIR"
  tar xzf "$TMP_DIR/pkg.tar.gz" -C "$APP_DIR" --strip-components=1
  echo "$VERSION" > "$APP_DIR/VERSION"
  ok "框架就绪"
}

# ---- 装控制台命令（默认 unmi；重装时沿用用户改过的名字）----
PANEL_CMD="unmi"

install_cli() {
  step "安装 unmi 控制台"
  # 重装时沿用用户之前改过的命令名，别把人家的习惯打回 unmi
  # 必须先判断文件存在再读：全新安装时 data/ 目录都还没有，
  # 直接 `< 文件` 会让 bash 报重定向错误 —— 这种错误 2>/dev/null 拦不住，
  # 而本脚本开了 set -e + pipefail，连 `cat f 2>/dev/null | tr ...` 也会因为
  # pipefail 拿到非 0 而中断安装。用 -f 先挡一道最干净。
  local saved=""
  if [ -f "$APP_DIR/data/panel-cmd.conf" ]; then
    saved="$(tr -d ' \t\r\n' < "$APP_DIR/data/panel-cmd.conf")"
  fi
  [ -n "$saved" ] && PANEL_CMD="$saved"
  install -m 755 "$APP_DIR/unmi-cli.sh" "/usr/local/bin/$PANEL_CMD"
  ok "以后敲 ${C_BOLD}${PANEL_CMD}${C_RESET} 打开控制台"
}

# ---- 安装时检测网络，连不上 Telegram 就配代理（写全局，所有机器人共用）----
detect_proxy() {
  step "网络连通性检查"
  mkdir -p "$APP_DIR/data"
  if curl -fsSL --connect-timeout 6 -o /dev/null https://api.telegram.org 2>/dev/null; then
    ok "可以直连 Telegram"
    printf '' > "$APP_DIR/data/proxy.conf"
    return
  fi
  warn "连不上 api.telegram.org（国内服务器需要代理才能用 Telegram）"
  local p r
  while :; do
    tty_read p "  ${C_BOLD}代理地址${C_RESET}（如 http://127.0.0.1:7890）: " || return
    # 去掉首尾误粘的括号/引号/空白：提示语里的括号经常被一起复制进来，
    # 存成 http://127.0.0.1:7890） 这种脏值，之后会莫名连不通且极难排查
    p="$(printf '%s' "$p" | sed 's/^[^A-Za-z0-9]*//; s/[^A-Za-z0-9/:._~%@+-]*$//')"
    if [ -z "$p" ]; then
      warn "连不上 Telegram 时必须配代理，否则机器人无法收发消息"
      continue
    fi
    if curl -fsSL --connect-timeout 8 -x "$p" -o /dev/null https://api.telegram.org 2>/dev/null; then
      ok "走代理 $p 可连通 Telegram"
      printf '%s' "$p" > "$APP_DIR/data/proxy.conf"
      return
    fi
    warn "走 $p 也连不通 Telegram"
    tty_read r "  重新输入代理？[y/N] " || return
    if [ "$r" != "y" ]; then
      warn "暂未配置代理（可稍后敲 unmi → p 配置全局代理）"
      printf '' > "$APP_DIR/data/proxy.conf"
      return
    fi
  done
}

# ---- 安装完成，进入控制台主页（不直接弹添加流程，让用户自己选）----
finish() {
  echo
  echo -e "${C_GREEN}${C_BOLD}════════════════════════════════════════${C_RESET}"
  echo -e "${C_GREEN}${C_BOLD}  ✅ 安装完成！${C_RESET}"
  echo -e "${C_GREEN}${C_BOLD}════════════════════════════════════════${C_RESET}"
  echo
  echo -e "  即将进入${C_BOLD}控制台主页${C_RESET}，你可以："
  echo -e "    ${C_CYAN}a${C_RESET}) 添加机器人    ${C_CYAN}p${C_RESET}) 配置全局代理    ${C_CYAN}u${C_RESET}) 一键更新"
  echo
  echo -e "  ${C_DIM}（以后随时敲 ${C_CYAN}${PANEL_CMD}${C_RESET}${C_DIM} 都能回到这个主页）${C_RESET}"
  echo
  # 进入控制台主菜单（read 从 /dev/tty 读，兼容 curl|bash）
  unmi || true
}

main() {
  clear 2>/dev/null || true
  banner
  need_root
  check_env
  download
  install_cli
  detect_proxy
  finish
}

main "$@"
