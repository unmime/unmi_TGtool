#!/usr/bin/env bash
#===============================================================================
# unmi — unmi_TGtool 终端控制面板
#
# 在终端敲 `unmi` 即可调出。安装脚本会把它放到 /usr/local/bin/unmi。
#
# 功能：查看状态 / 配置机器人 / 发送测试信息 / 配置代理 / 查看日志 /
#       重启服务 / 一键卸载
#===============================================================================
set -uo pipefail

APP_DIR="/opt/unmi_TGtool"
ENV_FILE="/etc/unmi_TGtool.env"
SERVICE="unmi_TGtool"

# ---- 颜色 ----
if [ -t 1 ]; then
  C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'
  C_CYAN=$'\033[36m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'
  C_RED=$'\033[31m'; C_PURPLE=$'\033[35m'
else
  C_RESET=""; C_BOLD=""; C_CYAN=""; C_GREEN=""; C_YELLOW=""; C_RED=""; C_PURPLE=""
fi
ok()   { echo -e "${C_GREEN}  [✓]${C_RESET} $*"; }
warn() { echo -e "${C_YELLOW}  [!]${C_RESET} $*"; }
err()  { echo -e "${C_RED}  [✗]${C_RESET} $*"; }

# ---- 读配置 ----
get_val() { grep -E "^$1=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2-; }
TOKEN()  { get_val TG_BOT_TOKEN; }
CHAT()   { get_val TG_CHAT_ID; }
PROXY()  { get_val https_proxy; }

# 当前生效的代理（curl 用）
proxy_args() {
  local p; p="$(PROXY)"
  [ -n "$p" ] && printf '%s' "-x $p" || printf ''
}

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
}

# ---- 1. 查看状态 ----
do_status() {
  echo -e "${C_BOLD}  服务状态${C_RESET}"
  systemctl is-active --quiet "$SERVICE" \
    && echo -e "    运行:  ${C_GREEN}active（运行中）${C_RESET}" \
    || echo -e "    运行:  ${C_RED}inactive（未运行）${C_RESET}"
  systemctl is-enabled --quiet "$SERVICE" 2>/dev/null \
    && echo -e "    自启:  enabled" || echo -e "    自启:  disabled"
  echo    "    目录:  $APP_DIR"
  echo    "    配置:  $ENV_FILE"
  local t c p; t="$(TOKEN)"; c="$(CHAT)"; p="$(PROXY)"
  [ -n "$t" ] && echo "    token: ${t:0:10}…（已配置）" || echo "    token: 未配置"
  [ -n "$c" ] && echo "    chat:  $c" || echo "    chat:  未配置"
  [ -n "$p" ] && echo "    代理:  $p" || echo "    代理:  未配置（直连）"
}

# ---- 2. 配置机器人 ----
do_config_bot() {
  echo -e "${C_BOLD}  配置机器人${C_RESET}"
  local token chat
  printf "  Bot Token（形如 123456:ABC...）: "; read -r token
  printf '%s' "$token" | grep -qE '^[0-9]+:[A-Za-z0-9_-]{20,}$' \
    || { err "token 格式不对，未保存"; return; }
  printf "  Chat ID（纯数字）: "; read -r chat
  printf '%s' "$chat" | grep -qE '^-?[0-9]+$' \
    || { err "chat id 必须是数字，未保存"; return; }

  # 保留已有的 DATA_DIR / 代理，只更新 token 和 chat_id
  local dd proxy; dd="$(get_val DATA_DIR)"; proxy="$(PROXY)"
  [ -z "$dd" ] && dd="$APP_DIR/data"
  umask 077
  {
    echo "TG_BOT_TOKEN=$token"
    echo "TG_CHAT_ID=$chat"
    echo "DATA_DIR=$dd"
    [ -n "$proxy" ] && echo "https_proxy=$proxy"
  } > "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  ok "已保存"
  systemctl is-active --quiet "$SERVICE" && { systemctl restart "$SERVICE"; ok "服务已重启生效"; }
  warn "建议用「发送测试信息」验证配置是否正确"
}

# ---- 3. 发送测试信息 ----
do_send_test() {
  local token chat; token="$(TOKEN)"; chat="$(CHAT)"
  [ -z "$token" ] || [ -z "$chat" ] && { err "还没配置 token / chat_id，先选 2 配置"; return; }
  echo "  发送中…（走代理：$(PROXY || echo 无)）"
  local resp
  resp=$(curl -fsSL --connect-timeout 12 $(proxy_args) \
    -d "chat_id=${chat}" \
    --data-urlencode "text=🔔 unmi_TGtool 测试消息：配置正确，bot 工作正常！发 66*98 试试。" \
    -d "parse_mode=HTML" \
    "https://api.telegram.org/bot${token}/sendMessage" 2>&1) || resp=""
  if printf '%s' "$resp" | grep -q '"ok":true'; then
    ok "已发送，去 Telegram 看"
  else
    err "发送失败"
    printf '%s' "$resp" | grep -oE '"description":"[^"]*"' | head -1 | sed 's/^/    /'
    warn "常见原因：token/chat_id 不对、没先给 bot 发过消息、或网络不通（国内要配代理，选 4）"
  fi
}

# ---- 4. 配置代理（国内服务器连不上 api.telegram.org 时用）----
do_config_proxy() {
  echo -e "${C_BOLD}  配置代理${C_RESET}（国内 VPS 访问 Telegram 需要；留空表示直连）"
  local p; p="$(PROXY)"
  [ -n "$p" ] && echo "  当前：$p"
  printf "  代理地址（如 http://127.0.0.1:7890，留空清除）: "; read -r p
  local token chat dd; token="$(TOKEN)"; chat="$(CHAT)"; dd="$(get_val DATA_DIR)"
  [ -z "$dd" ] && dd="$APP_DIR/data"
  umask 077
  {
    [ -n "$token" ] && echo "TG_BOT_TOKEN=$token"
    [ -n "$chat" ] && echo "TG_CHAT_ID=$chat"
    echo "DATA_DIR=$dd"
    [ -n "$p" ] && echo "https_proxy=$p"
  } > "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  [ -n "$p" ] && ok "代理已设为 $p" || ok "已清除代理（直连）"
  systemctl is-active --quiet "$SERVICE" && { systemctl restart "$SERVICE"; ok "服务已重启生效"; }
}

# ---- 5. 查看日志 ----
do_log() { journalctl -u "$SERVICE" -n 30 --no-pager; }

# ---- 6. 重启 ----
do_restart() { systemctl restart "$SERVICE" && ok "已重启"; }

# ---- 7. 一键卸载 ----
do_uninstall() {
  echo -e "${C_RED}${C_BOLD}  一键卸载 unmi_TGtool${C_RESET}"
  echo "    将删除：$APP_DIR、$ENV_FILE、systemd 服务、unmi 命令"
  printf "    确认卸载？输入 yes: "; read -r ans
  [ "$ans" = "yes" ] || { warn "已取消"; return; }
  systemctl stop "$SERVICE" 2>/dev/null || true
  systemctl disable "$SERVICE" 2>/dev/null || true
  rm -f "/etc/systemd/system/$SERVICE.service" "$ENV_FILE"
  rm -rf "$APP_DIR"
  systemctl daemon-reload
  ok "已卸载"
  echo "    unmi 命令将于退出后移除（/usr/local/bin/unmi）"
  (sleep 1; rm -f /usr/local/bin/unmi) &
  exit 0
}

# ---- 主菜单 ----
menu() {
  clear 2>/dev/null || true
  banner
  local st
  systemctl is-active --quiet "$SERVICE" && st="${C_GREEN}运行中${C_RESET}" || st="${C_RED}未运行${C_RESET}"
  echo -e "  ${C_BOLD}unmi_TGtool 控制面板${C_RESET}   服务：$st"
  echo
  echo -e "  ${C_CYAN}1${C_RESET}) 查看服务状态"
  echo -e "  ${C_CYAN}2${C_RESET}) 配置机器人（token / chat_id）"
  echo -e "  ${C_CYAN}3${C_RESET}) 发送测试信息"
  echo -e "  ${C_CYAN}4${C_RESET}) 配置代理（国内连不上 Telegram 时用）"
  echo -e "  ${C_CYAN}5${C_RESET}) 查看日志"
  echo -e "  ${C_CYAN}6${C_RESET}) 重启服务"
  echo -e "  ${C_CYAN}7${C_RESET}) 一键卸载"
  echo -e "  ${C_CYAN}0${C_RESET}) 退出"
  echo
}

main() {
  [ "$(id -u)" -ne 0 ] && { err "需要 root（sudo unmi）"; exit 1; }
  while :; do
    menu
    printf "  请选择 [0-7]: "; read -r n
    case "$n" in
      1) do_status ;;
      2) do_config_bot ;;
      3) do_send_test ;;
      4) do_config_proxy ;;
      5) do_log ;;
      6) do_restart ;;
      7) do_uninstall ;;
      0|q) echo "  再见"; exit 0 ;;
      *) warn "无效选项" ;;
    esac
    echo
    printf "  按回车返回菜单…"; read -r _
  done
}

main "$@"
