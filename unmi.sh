#!/usr/bin/env bash
#===============================================================================
# unmi_TGtool 一键安装脚本
#
# 推荐用法（process substitution，stdin 仍是终端，可正常交互输入）：
#   bash <(curl -sL https://raw.githubusercontent.com/wazakid/unmi_TGtool/main/unmi.sh)
#
# 也兼容管道方式（脚本内 read 强制从 /dev/tty 读，依然可交互）：
#   curl -sL https://raw.githubusercontent.com/wazakid/unmi_TGtool/main/unmi.sh | bash
#
# 流程：艺术字 -> 环境检查 -> 下载 -> 解压 -> 输入 token/chat_id ->
#       写配置 -> 注册并启动 systemd -> 发测试消息 -> 使用说明
#===============================================================================
set -euo pipefail

# ---- 常量 ----
VERSION="v2.0.2"
REPO="wazakid/unmi_TGtool"
TAR_URL="https://github.com/${REPO}/releases/download/${VERSION}/unmi_TGtool.tar.gz"
APP_DIR="/opt/unmi_TGtool"
ENV_FILE="/etc/unmi_TGtool.env"
SERVICE="unmi_TGtool"

# ---- 颜色（非终端时自动关闭，避免管道里出现乱码）----
if [ -t 1 ]; then
  C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'
  C_CYAN=$'\033[36m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'
  C_RED=$'\033[31m'; C_PURPLE=$'\033[35m'; C_BLUE=$'\033[34m'
else
  C_RESET=""; C_BOLD=""; C_CYAN=""; C_GREEN=""; C_YELLOW=""; C_RED=""; C_PURPLE=""; C_BLUE=""
fi

# ---- 打印函数 ----
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
  echo -e "  ${C_BOLD}unmi_TGtool${C_RESET} · 开箱即用的自托管 Telegram 工具集"
  echo -e "  ${C_CYAN}github.com/${REPO}${C_RESET}   ${C_YELLOW}${VERSION}${C_RESET}"
}

# ---- 必须 root ----
need_root() {
  if [ "$(id -u)" -ne 0 ]; then
    err "需要 root 权限（要写 /opt、/etc、systemd）"
    echo    "    请改用：sudo bash <(curl -sL .../unmi.sh)"
    exit 1
  fi
}

# ---- 环境检查 ----
check_env() {
  step "环境检查"
  local missing=0
  command -v python3 >/dev/null 2>&1 || { err "缺少 python3"; missing=1; }
  command -v tar     >/dev/null 2>&1 || { err "缺少 tar";     missing=1; }
  if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
    err "需要 curl 或 wget 之一"; missing=1
  fi
  [ "$missing" = "1" ] && { err "环境检查未通过，请先安装缺失依赖"; exit 1; }
  ok "python3 $(python3 -V 2>&1 | awk '{print $2}')"
  ok "依赖齐全（python3 / tar / $(command -v curl >/dev/null && echo curl || echo wget)）"
}

# ---- token 冲突检查（同一 token 只能有一个轮询进程）----
check_conflict() {
  if command -v pgrep >/dev/null && \
     pgrep -af "getUpdates|main\.py|TG.*_bot\.py" 2>/dev/null | grep -v grep | grep -q .; then
    warn "检测到可能已在运行的 bot 进程（同一 token 两个进程会互相抢消息）："
    pgrep -af "main\.py|TG.*_bot\.py" 2>/dev/null | grep -v grep | sed 's/^/      /' || true
    printf "    仍要继续安装？[y/N] " > /dev/tty
    read -r ans < /dev/tty
    [ "$ans" = "y" ] || { info "已取消"; exit 0; }
  fi
}

# ---- 下载并解压 ----
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

  step "解压到 $APP_DIR"
  rm -rf "$APP_DIR"
  mkdir -p "$APP_DIR"
  # tar 包含顶层目录 unmi_TGtool/，用 --strip-components=1 去掉后直接落在 APP_DIR
  tar xzf "$TMP_DIR/pkg.tar.gz" -C "$APP_DIR" --strip-components=1
  ok "文件就绪（$(find "$APP_DIR" -type f | wc -l | tr -d ' ') 个文件）"
}

# ---- 交互输入（read 强制从 /dev/tty 读，兼容 curl|bash 管道）----
ask_config() {
  step "配置 Telegram Bot"
  echo -e "  ${C_CYAN}去 @BotFather 建 bot 拿 token；先给 bot 发条消息，再拿你的 chat id${C_RESET}"
  while :; do
    printf "  ${C_BOLD}Bot Token${C_RESET}（形如 123456:ABC-DEF...）: " > /dev/tty
    read -r TOKEN < /dev/tty
    if printf '%s' "$TOKEN" | grep -qE '^[0-9]+:[A-Za-z0-9_-]{20,}$'; then break; fi
    warn "token 格式不对，请重新输入"
  done
  while :; do
    printf "  ${C_BOLD}Chat ID${C_RESET}（纯数字）: " > /dev/tty
    read -r CHAT < /dev/tty
    if printf '%s' "$CHAT" | grep -qE '^-?[0-9]+$'; then break; fi
    warn "chat id 必须是数字，请重新输入"
  done
  ok "已获取配置"
}

# ---- 装 unmi 终端面板命令 ----
install_cli() {
  step "安装 unmi 终端面板"
  if [ -f "$APP_DIR/unmi-cli.sh" ]; then
    install -m 755 "$APP_DIR/unmi-cli.sh" /usr/local/bin/unmi
    ok "以后在终端敲 ${C_BOLD}unmi${C_RESET} 即可调出控制面板"
  fi
}

# ---- 网络检测 + 代理（国内服务器连不上 api.telegram.org 时提示）----
detect_proxy() {
  step "网络连通性检查"
  PROXY=""
  if curl -fsSL --connect-timeout 6 -o /dev/null https://api.telegram.org 2>/dev/null; then
    ok "可以直连 Telegram"
    return
  fi
  warn "连不上 api.telegram.org（国内服务器常见，需要走代理）"
  printf "  ${C_BOLD}代理地址${C_RESET}（如 http://127.0.0.1:7890，留空跳过）: " > /dev/tty
  read -r PROXY < /dev/tty
  if [ -n "$PROXY" ]; then
    if curl -fsSL --connect-timeout 8 -x "$PROXY" -o /dev/null https://api.telegram.org 2>/dev/null; then
      ok "走代理 $PROXY 可以连通"
    else
      warn "走 $PROXY 也连不通，请确认代理可用（可稍后敲 unmi 选 4 重配）"
    fi
  else
    warn "未配置代理，bot 将无法连接 Telegram（可稍后敲 unmi 选 4 配置）"
  fi
}

# ---- 写配置 ----
write_env() {
  step "写入配置 $ENV_FILE"
  umask 077
  {
    echo "TG_BOT_TOKEN=$TOKEN"
    echo "TG_CHAT_ID=$CHAT"
    echo "DATA_DIR=$APP_DIR/data"
    [ -n "${PROXY:-}" ] && echo "https_proxy=$PROXY"
  } > "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  ok "配置已写入（权限 600）"
}

# ---- 注册并启动 systemd ----
setup_service() {
  step "注册并启动 systemd 服务"
  [ -f "$APP_DIR/unmi_TGtool.service" ] && \
    install -m 644 "$APP_DIR/unmi_TGtool.service" "/etc/systemd/system/$SERVICE.service"
  systemctl daemon-reload
  systemctl enable "$SERVICE" >/dev/null 2>&1 || true
  systemctl restart "$SERVICE"
  sleep 2
  if systemctl is-active --quiet "$SERVICE"; then
    ok "服务运行中（开机自启）"
  else
    err "启动失败，看日志：journalctl -u $SERVICE -n 20"
    exit 1
  fi
}

# ---- 发测试消息 ----
send_test() {
  step "发送测试消息"
  local text="🎉 unmi_TGtool 安装成功！%0A%0A直接发算式就能算，比如发 66*98%0A/calc 打开设置面板%0A/help 查看已加载模块"
  local url="https://api.telegram.org/bot${TOKEN}/sendMessage"
  local resp=""
  local px=""
  [ -n "${PROXY:-}" ] && px="-x $PROXY"
  if command -v curl >/dev/null 2>&1; then
    resp=$(curl -fsSL --connect-timeout 12 $px \
      -d "chat_id=${CHAT}" -d "text=${text}" -d "parse_mode=HTML" "$url" 2>/dev/null) || resp=""
  else
    resp=$(wget -q --timeout=12 -e "use_proxy=yes" -e "https_proxy=$PROXY" \
      --post-data "chat_id=${CHAT}&text=${text}&parse_mode=HTML" -O- "$url" 2>/dev/null) || resp=""
  fi
  if printf '%s' "$resp" | grep -q '"ok":true'; then
    ok "测试消息已发到你的 Telegram，去看看"
  else
    warn "测试消息没发出去"
    printf '%s' "$resp" | grep -oE '"description":"[^"]*"' | head -1 | sed 's/^/      /'
    echo  "      常见原因：token/chat_id 不对、没先给 bot 发过消息、或网络不通"
    echo  "      排查：敲 unmi → 2 检查配置 / 3 重发测试 / 4 配代理"
  fi
}

# ---- 使用说明 ----
usage() {
  echo
  echo -e "${C_GREEN}${C_BOLD}════════════════════════════════════════${C_RESET}"
  echo -e "${C_GREEN}${C_BOLD}  ✅ unmi_TGtool 安装完成！${C_RESET}"
  echo -e "${C_GREEN}${C_BOLD}════════════════════════════════════════${C_RESET}"
  echo
  echo -e "${C_BOLD}  立即使用${C_RESET}（在 Telegram 里发给 bot）："
  echo -e "    ${C_CYAN}66*98${C_RESET}     直接算，出结果 + 中文读法 + 会计大写"
  echo -e "    ${C_CYAN}/calc${C_RESET}     打开设置面板（小数位 / 格式 / 连续计算）"
  echo -e "    ${C_CYAN}/help${C_RESET}     查看已加载模块"
  echo
  echo -e "${C_BOLD}  控制面板${C_RESET}："
  echo -e "    ${C_CYAN}unmi${C_RESET}              调出终端面板（配置 / 测试 / 代理 / 卸载）"
  echo
  echo -e "${C_BOLD}  常用运维${C_RESET}："
  echo    "    systemctl status  $SERVICE      查看状态"
  echo    "    journalctl -u $SERVICE -f       实时日志"
  echo    "    systemctl restart $SERVICE      重启（改代码后必做）"
  echo
  echo -e "${C_BOLD}  加功能${C_RESET}：写 modules/x.py → 加进 data/modules.json → 重启"
  echo -e "  文档：${C_CYAN}github.com/${REPO}${C_RESET}"
  echo
}

# ---- 主流程 ----
main() {
  clear 2>/dev/null || true
  banner
  need_root
  check_env
  check_conflict
  download
  ask_config
  detect_proxy
  write_env
  install_cli
  setup_service
  send_test
  usage
}

main "$@"
