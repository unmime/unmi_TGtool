#!/usr/bin/env bash
#===============================================================================
# unmi — unmi_TGtool 控制台
#
# 在终端敲 `unmi` 打开控制台：集中管理这台机器上的所有 Telegram 机器人。
#   · 列出所有机器人（自动识别 bot 名 + 自定义名 + 运行状态）
#   · 添加机器人（输 token 自动识别，可自定义名字）
#   · 进入某个机器人做管理（配置 / 测试 / 代理 / 更新 / 卸载）
#
# 约定：
#   主实例   /opt/unmi_TGtool           服务 unmi_TGtool           配置 /etc/unmi_TGtool.env
#   其他实例 /opt/unmi_TGtool-<name>    服务 unmi_TGtool-<name>    配置 /etc/unmi_TGtool-<name>.env
#===============================================================================
set -uo pipefail

BASE="/opt/unmi_TGtool"
MAIN_SERVICE="unmi_TGtool"
MAIN_ENV="/etc/unmi_TGtool.env"

# ---- 颜色 ----
if [ -t 1 ]; then
  C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'
  C_CYAN=$'\033[36m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'
  C_RED=$'\033[31m'; C_PURPLE=$'\033[35m'; C_BLUE=$'\033[34m'
  C_PINK=$'\033[38;5;217m'   # 淡粉（备注用）
else
  C_RESET=""; C_BOLD=""; C_DIM=""; C_CYAN=""; C_GREEN=""; C_YELLOW=""; C_RED=""; C_PURPLE=""; C_BLUE=""; C_PINK=""
fi
ok()   { echo -e "${C_GREEN}  [✓]${C_RESET} $*"; }
warn() { echo -e "${C_YELLOW}  [!]${C_RESET} $*"; }
err()  { echo -e "${C_RED}  [✗]${C_RESET} $*"; }

# 分割线（贴合主题的暗青色，区分每一屏/每次操作）
divider() { echo -e "${C_DIM}${C_CYAN}  ──────────────────────────────────────────${C_RESET}"; }

#===============================================================================
# 实例发现与信息
#===============================================================================

# 输出每个实例一行：name|dir|env|service
# main 必须有配置文件才算实例（删除后代码目录还在，但没有 env 就不该再列出来）
list_instances() {
  [ -d "$BASE" ] && [ -f "$MAIN_ENV" ] && printf 'main|%s|%s|%s\n' "$BASE" "$MAIN_ENV" "$MAIN_SERVICE"
  local d n
  for d in "$BASE"-*/; do
    [ -d "$d" ] || continue
    n="$(basename "$d")"; n="${n#unmi_TGtool-}"
    printf '%s|%s|%s|%s\n' "$n" "${d%/}" "/etc/unmi_TGtool-$n.env" "unmi_TGtool-$n"
  done
}

get_val() { grep -E "^$2=" "$1" 2>/dev/null | head -1 | cut -d= -f2-; }

# 该 env 生效的代理（拼成 curl 参数）
proxy_args() { local p; p="$(get_val "$1" https_proxy)"; [ -n "$p" ] && printf -- '-x %s' "$p" || printf ''; }

# 全局代理（安装时配一次，所有机器人共用）。存 $BASE/data/proxy.conf
PROXY_CONF="$BASE/data/proxy.conf"
global_proxy() { cat "$PROXY_CONF" 2>/dev/null; }
# 供 curl 用（展开成 -x 参数或空）
global_proxy_args() { local p; p="$(global_proxy)"; [ -n "$p" ] && printf -- '-x %s' "$p" || printf ''; }

svc_state() {
  if systemctl is-active --quiet "$1" 2>/dev/null; then
    echo -e "${C_GREEN}运行中${C_RESET}"
  else
    echo -e "${C_RED}停止${C_RESET}"
  fi
}

# 实例标题里的 active/inactive（active 绿、inactive 红）
state_text() {
  if systemctl is-active --quiet "$1" 2>/dev/null; then
    echo -e "${C_GREEN}active${C_RESET}"
  else
    echo -e "${C_RED}inactive${C_RESET}"
  fi
}

# bot 名：优先读缓存 data/botinfo，没有则 getMe 拉取并缓存。输出 "@username"（拿不到则空）
bot_username() {  # $1=dir $2=env
  local cache="$1/data/botinfo" token un
  [ -f "$cache" ] && { cat "$cache" 2>/dev/null; return; }
  token="$(get_val "$2" TG_BOT_TOKEN)"
  [ -z "$token" ] && return
  un="$(curl -fsSL --connect-timeout 10 $(proxy_args "$2") \
        "https://api.telegram.org/bot${token}/getMe" 2>/dev/null \
        | grep -oE '"username":"[^"]+"' | head -1 | cut -d'"' -f4)"
  if [ -n "$un" ]; then
    mkdir -p "$1/data" 2>/dev/null
    echo "@$un" > "$cache" 2>/dev/null
    echo "@$un"
  fi
}

# 显示用名字：自定义名（INSTANCE_LABEL）优先，其次 @username，再次实例名
display_name() {  # $1=name $2=dir $3=env
  local label un
  label="$(get_val "$3" INSTANCE_LABEL)"
  [ -n "$label" ] && { echo "$label"; return; }
  un="$(bot_username "$2" "$3")"
  [ -n "$un" ] && { echo "$un"; return; }
  echo "$1"
}

#===============================================================================
# 添加机器人
#===============================================================================

add_bot() {
  echo
  divider
  echo -e "${C_BOLD}  添加机器人${C_RESET}  ${C_DIM}（共 3 步：Token → Chat ID → 备注）${C_RESET}"
  divider
  echo -e "${C_CYAN}${C_BOLD}【第 1 步】Bot Token${C_RESET} ${C_DIM}（去 @BotFather 建 bot 拿；先给 bot 发条消息）${C_RESET}"

  local token
  while :; do
    printf "  ${C_BOLD}Bot Token${C_RESET}（形如 123456:ABC-DEF...）: "; read -r token
    printf '%s' "$token" | grep -qE '^[0-9]+:[A-Za-z0-9_-]{20,}$' && break
    warn "token 格式不对，重新输入"
  done

  # 同 token 查重：这个 token 已被别的实例占用的话，两个进程会互相抢消息
  local f
  for f in /etc/unmi_TGtool*.env; do
    [ -f "$f" ] || continue
    if grep -q "^TG_BOT_TOKEN=${token}$" "$f" 2>/dev/null; then
      warn "这个 token 已被实例（$f）占用，同 token 跑两个会互相抢消息"
      printf "  仍要添加？[y/N] "; read -r c; [ "$c" = "y" ] || return
    fi
  done

  # 识别 bot 名（用安装时已配好的全局代理，这里不再询问）
  local proxy px; proxy="$(global_proxy)"; px=""
  [ -n "$proxy" ] && px="-x $proxy"
  echo -e "  ${C_DIM}正在识别机器人…$( [ -n "$proxy" ] && echo "（走全局代理）" )${C_RESET}"
  local me un fname
  me="$(curl -fsSL --connect-timeout 12 $px "https://api.telegram.org/bot${token}/getMe" 2>/dev/null)"
  un="$(printf '%s' "$me" | grep -oE '"username":"[^"]+"' | head -1 | cut -d'"' -f4)"
  fname="$(printf '%s' "$me" | grep -oE '"first_name":"[^"]+"' | head -1 | cut -d'"' -f4)"
  if [ -n "$un" ]; then
    ok "识别到机器人：${C_BOLD}@${un}${C_RESET}（${fname}）"
  else
    warn "没能识别（token 可能不对，或网络/代理不通）"
    printf "  仍要继续添加？[y/N] "; read -r c; [ "$c" = "y" ] || return
  fi

  divider
  echo -e "${C_CYAN}${C_BOLD}【第 2 步】Chat ID${C_RESET} ${C_DIM}（你的 Telegram 用户 ID，纯数字；必填，不可跳过）${C_RESET}"
  local chat
  while :; do
    printf "  ${C_BOLD}Chat ID${C_RESET}（纯数字）: "; read -r chat
    printf '%s' "$chat" | grep -qE '^-?[0-9]+$' && break
    warn "chat id 必须是数字，重新输入"
  done

  divider
  echo -e "${C_CYAN}${C_BOLD}【第 3 步】备注${C_RESET} ${C_DIM}（给机器人起个好认的名字，用于面板显示）${C_RESET}"
  local label slug
  printf "  ${C_BOLD}备注名${C_RESET}（默认 @%s）: " "${un:-bot}"; read -r label
  [ -z "$label" ] && label="${un:-bot}"
  slug="$(printf '%s' "$label" | tr -cd 'A-Za-z0-9_-' | tr 'A-Z' 'a-z')"
  [ -z "$slug" ] && slug="$(printf '%s' "$un" | tr -cd 'A-Za-z0-9_-' | tr 'A-Z' 'a-z')"
  [ -z "$slug" ] && slug="bot$(date +%s)"

  local dir env svc
  # 第一个 bot 复用主实例（$BASE 的共享代码 + main 服务）；之后的 bot 各开新目录
  if [ ! -f "$MAIN_ENV" ]; then
    dir="$BASE"; env="$MAIN_ENV"; svc="$MAIN_SERVICE"
  else
    dir="$BASE-$slug"; env="/etc/unmi_TGtool-$slug.env"; svc="unmi_TGtool-$slug"
  fi
  if [ -f "$env" ]; then
    warn "实例 $slug 已配置过（$env）"
    printf "  覆盖重装？[y/N] "; read -r c; [ "$c" = "y" ] || return
  fi

  # 落地：复制程序、写 env、建服务、启动
  divider
  echo -e "  ${C_DIM}创建实例 $slug …${C_RESET}"
  if [ "$dir" != "$BASE" ]; then
    mkdir -p "$dir"
    cp -r "$BASE/core" "$BASE/modules" "$dir/" 2>/dev/null || true
    cp "$BASE/main.py" "$BASE/TGcalc_bot.py" "$dir/" 2>/dev/null
    [ -f "$BASE/VERSION" ] && cp "$BASE/VERSION" "$dir/"
    mkdir -p "$dir/data"
  fi
  umask 077
  {
    echo "TG_BOT_TOKEN=$token"
    echo "TG_CHAT_ID=$chat"
    echo "DATA_DIR=$dir/data"
    echo "INSTANCE_LABEL=$label"
    [ -n "$proxy" ] && echo "https_proxy=$proxy"
  } > "$env"
  chmod 600 "$env"
  [ -n "$un" ] && { mkdir -p "$dir/data"; echo "@$un" > "$dir/data/botinfo"; }

  cat > "/etc/systemd/system/$svc.service" <<EOF
[Unit]
Description=unmi_TGtool bot ($label)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=$env
WorkingDirectory=$dir
ExecStart=/usr/bin/python3 $dir/main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable "$svc" >/dev/null 2>&1 || true
  systemctl restart "$svc"
  sleep 2
  systemctl is-active --quiet "$svc" && ok "已启动：$svc" \
    || { err "启动失败，看日志：journalctl -u $svc -n 20"; return; }

  local resp
  resp="$(curl -fsSL --connect-timeout 12 $px \
    -d "chat_id=$chat" --data-urlencode "text=🎉 机器人「$label」已上线！发 66*98 试试。" \
    -d "parse_mode=HTML" "https://api.telegram.org/bot${token}/sendMessage" 2>/dev/null)"
  printf '%s' "$resp" | grep -q '"ok":true' \
    && ok "测试消息已发到 Telegram" \
    || warn "测试消息没发出去（可进该机器人选「发送测试」重试）"

  echo
  divider
  echo -e "${C_GREEN}${C_BOLD}  ✅ 添加完成 · 配置摘要${C_RESET}"
  echo    "    机器人:  ${un:+@$un }（$label）"
  echo    "    Chat ID: $chat"
  echo    "    代理:    ${proxy:-直连}"
  echo    "    实例:    $slug（服务 $svc）"
  divider
  echo -e "  去 Telegram 给 ${C_BOLD}${un:+@$un}${C_RESET} 发 ${C_CYAN}66*98${C_RESET} 就能用"
}

#===============================================================================
# 单实例管理
#===============================================================================

set_current() {  # $1=name
  CUR_NAME="$1"
  if [ "$1" = "main" ]; then
    CUR_DIR="$BASE"; CUR_ENV="$MAIN_ENV"; CUR_SVC="$MAIN_SERVICE"
  else
    CUR_DIR="$BASE-$1"; CUR_ENV="/etc/unmi_TGtool-$1.env"; CUR_SVC="unmi_TGtool-$1"
  fi
  CUR_LABEL="$(display_name "$CUR_NAME" "$CUR_DIR" "$CUR_ENV")"
}

cval()   { get_val "$CUR_ENV" "$1"; }
cproxy() { local p; p="$(cval https_proxy)"; [ -n "$p" ] && printf -- '-x %s' "$p" || printf ''; }

inst_status() {
  echo -e "  名称:   ${C_BOLD}$CUR_LABEL${C_RESET}（实例 $CUR_NAME）"
  echo -e "  运行:   $(svc_state "$CUR_SVC")"
  echo    "  目录:   $CUR_DIR"
  echo    "  配置:   $CUR_ENV"
  local t c p v; t="$(cval TG_BOT_TOKEN)"; c="$(cval TG_CHAT_ID)"; p="$(cval https_proxy)"
  v="?"; [ -f "$CUR_DIR/VERSION" ] && v="$(cat "$CUR_DIR/VERSION")"
  echo    "  版本:   $v"
  [ -n "$t" ] && echo "  token:  ${t:0:10}…（已配置）" || echo "  token:  未配置"
  [ -n "$c" ] && echo "  chat:   $c" || echo "  chat:   未配置"
  [ -n "$p" ] && echo "  代理:   $p" || echo "  代理:   未配置（直连）"
}

# 统一写 env：读出现有全部字段，用传入的 k=v 覆盖指定项后写回。
# 这样每个功能只改自己那项，不会丢掉备注/代理等其它字段。
save_env() {  # 用法: save_env KEY=VAL [KEY=VAL ...]（作用于当前实例 $CUR_ENV）
  local token chat dd proxy label note
  token="$(cval TG_BOT_TOKEN)"; chat="$(cval TG_CHAT_ID)"
  dd="$(cval DATA_DIR)"; [ -z "$dd" ] && dd="$CUR_DIR/data"
  proxy="$(cval https_proxy)"; label="$(cval INSTANCE_LABEL)"; note="$(cval INSTANCE_NOTE)"
  local kv k v
  for kv in "$@"; do
    k="${kv%%=*}"; v="${kv#*=}"
    case "$k" in
      TG_BOT_TOKEN)   token="$v";;
      TG_CHAT_ID)     chat="$v";;
      DATA_DIR)       dd="$v";;
      https_proxy)    proxy="$v";;
      INSTANCE_LABEL) label="$v";;
      INSTANCE_NOTE)  note="$v";;
    esac
  done
  umask 077
  {
    [ -n "$token" ] && echo "TG_BOT_TOKEN=$token"
    [ -n "$chat" ] && echo "TG_CHAT_ID=$chat"
    echo "DATA_DIR=$dd"
    [ -n "$label" ] && echo "INSTANCE_LABEL=$label"
    [ -n "$note" ] && echo "INSTANCE_NOTE=$note"
    [ -n "$proxy" ] && echo "https_proxy=$proxy"
  } > "$CUR_ENV"
  chmod 600 "$CUR_ENV"
}

inst_config() {
  local token chat
  echo -e "  ${C_DIM}（随时输入 0 返回菜单）${C_RESET}"
  printf "  Bot Token: "; read -r token
  [ "$token" = "0" ] && return
  printf '%s' "$token" | grep -qE '^[0-9]+:[A-Za-z0-9_-]{20,}$' || { err "格式不对"; return; }
  printf "  Chat ID: "; read -r chat
  [ "$chat" = "0" ] && return
  printf '%s' "$chat" | grep -qE '^-?[0-9]+$' || { err "必须是数字"; return; }
  save_env TG_BOT_TOKEN="$token" TG_CHAT_ID="$chat"
  rm -f "$CUR_DIR/data/botinfo"
  systemctl restart "$CUR_SVC" && ok "已保存并重启"
}

inst_test() {
  local token chat; token="$(cval TG_BOT_TOKEN)"; chat="$(cval TG_CHAT_ID)"
  [ -z "$token" ] || [ -z "$chat" ] && { err "先配置 token / chat_id"; return; }
  echo "  发送中…（代理：$(cval https_proxy || echo 无)）"
  local resp
  resp="$(curl -fsSL --connect-timeout 12 $(cproxy) -d "chat_id=$chat" \
    --data-urlencode "text=🔔 「$CUR_LABEL」测试消息：配置正确，工作正常！" \
    -d "parse_mode=HTML" "https://api.telegram.org/bot${token}/sendMessage" 2>&1)"
  printf '%s' "$resp" | grep -q '"ok":true' && ok "已发送" \
    || { err "发送失败"; printf '%s' "$resp" | grep -oE '"description":"[^"]*"' | head -1 | sed 's/^/    /'; }
}

inst_proxy() {
  local p; p="$(cval https_proxy)"; [ -n "$p" ] && echo "  当前：$p"
  echo -e "  ${C_DIM}（输入 0 返回菜单）${C_RESET}"
  printf "  代理地址（留空清除）: "; read -r p
  [ "$p" = "0" ] && return
  save_env https_proxy="$p"
  [ -n "$p" ] && ok "代理已设为 $p" || ok "已清除代理"
  systemctl restart "$CUR_SVC" >/dev/null 2>&1 && ok "已重启生效"
}

# 添加/修改备注（存在 env 的 INSTANCE_NOTE，标题栏显示）
inst_note() {
  local cur; cur="$(cval INSTANCE_NOTE)"
  [ -n "$cur" ] && echo "  当前备注：$cur"
  echo -e "  ${C_DIM}（输入 0 返回菜单）${C_RESET}"
  printf "  备注（留空清除）: "; read -r cur
  [ "$cur" = "0" ] && return
  save_env INSTANCE_NOTE="$cur"
  CUR_NOTE="$cur"
  [ -n "$cur" ] && ok "备注已保存：$cur" || ok "备注已清除"
}

inst_log()     { journalctl -u "$CUR_SVC" -n 30 --no-pager; }
inst_restart() { systemctl restart "$CUR_SVC" && ok "已重启"; }

inst_update() {
  local latest cur; cur="未知"; [ -f "$CUR_DIR/VERSION" ] && cur="$(cat "$CUR_DIR/VERSION")"
  echo "    当前: $cur"
  latest="$(curl -fsSL --connect-timeout 12 $(cproxy) \
    "https://api.github.com/repos/unmime/unmi_TGtool/releases/latest" 2>/dev/null \
    | grep -oE '"tag_name":[[:space:]]*"[^"]+"' | head -1 | cut -d'"' -f4)"
  [ -z "$latest" ] && { err "获取最新版本失败（网络问题）"; return; }
  echo "    最新: $latest"
  [ "$cur" = "$latest" ] && { ok "已是最新"; return; }
  echo
  printf "    ${C_BOLD}是否更新到 %s？${C_RESET} [y] 更新  [0/其它] 返回: " "$latest"
  read -r a; [ "$a" = "y" ] || { warn "已取消"; return; }
  local tmp; tmp="$(mktemp -d)"
  curl -fsSL --connect-timeout 20 $(cproxy) \
    "https://github.com/unmime/unmi_TGtool/releases/download/${latest}/unmi_TGtool.tar.gz" \
    -o "$tmp/p.tgz" 2>/dev/null || { err "下载失败"; rm -rf "$tmp"; return; }
  cp -r "$CUR_DIR/data" "$tmp/dbak" 2>/dev/null || true
  # 解压必须先成功：脚本无 set -e，解压失败若继续会删掉 core/modules 却复制不上新文件
  tar xzf "$tmp/p.tgz" -C "$tmp" || { err "解压失败（安装包损坏），未改动任何文件"; rm -rf "$tmp"; return; }
  [ -d "$tmp/unmi_TGtool/core" ] || { err "安装包结构异常，未改动任何文件"; rm -rf "$tmp"; return; }
  rm -rf "$CUR_DIR/core" "$CUR_DIR/modules"
  cp -r "$tmp/unmi_TGtool/core" "$tmp/unmi_TGtool/modules" "$CUR_DIR/"
  cp "$tmp/unmi_TGtool/main.py" "$tmp/unmi_TGtool/TGcalc_bot.py" "$CUR_DIR/"
  mkdir -p "$CUR_DIR/data"; cp -r "$tmp/dbak/." "$CUR_DIR/data/" 2>/dev/null || true
  echo "$latest" > "$CUR_DIR/VERSION"
  [ -f "$tmp/unmi_TGtool/unmi-cli.sh" ] && install -m 755 "$tmp/unmi_TGtool/unmi-cli.sh" /usr/local/bin/unmi
  rm -rf "$tmp"
  systemctl restart "$CUR_SVC" && ok "已更新到 $latest 并重启"
}

inst_uninstall() {
  # 只删除当前这个机器人（它的配置/服务/目录），不动控制台本身和其它机器人
  echo -e "  ${C_RED}删除机器人「$CUR_LABEL」（实例 $CUR_NAME）${C_RESET}"
  echo "    将删除：$CUR_ENV、服务 $CUR_SVC$( [ "$CUR_NAME" != "main" ] && echo "、$CUR_DIR" )"
  echo -e "    ${C_DIM}控制台和其它机器人不受影响${C_RESET}"
  echo
  printf "    ${C_BOLD}是否删除？${C_RESET} [y] 删除  [0/其它] 取消: "; read -r a
  [ "$a" = "y" ] || { warn "已取消"; return; }
  systemctl stop "$CUR_SVC" 2>/dev/null; systemctl disable "$CUR_SVC" 2>/dev/null
  rm -f "/etc/systemd/system/$CUR_SVC.service" "$CUR_ENV"
  [ "$CUR_NAME" != "main" ] && rm -rf "$CUR_DIR" || warn "主实例目录保留（其它实例可能共享其代码）"
  systemctl daemon-reload
  ok "已删除「$CUR_LABEL」"
  return 9
}

inst_menu() {
  local n _note
  while :; do
    _note="$(cval INSTANCE_NOTE)"
    echo
    divider
    if [ -n "$_note" ]; then
      echo -e "${C_BOLD}  🤖 $CUR_LABEL${C_RESET} ${C_PINK}（$_note）${C_RESET}"
    else
      echo -e "${C_BOLD}  🤖 $CUR_LABEL${C_RESET}"
    fi
    echo -e "  ${C_DIM}$CUR_SVC · $(state_text "$CUR_SVC")${C_RESET}"
    divider
    echo -e "  ${C_CYAN}1${C_RESET}) 查看状态      ${C_CYAN}2${C_RESET}) 配置机器人    ${C_CYAN}3${C_RESET}) 添加备注"
    echo -e "  ${C_CYAN}4${C_RESET}) 查看日志      ${C_CYAN}5${C_RESET}) 重启服务      ${C_CYAN}6${C_RESET}) 删除此机器人"
    echo -e "  ${C_CYAN}0${C_RESET}) 返回面板"
    divider
    printf "  选择: "; read -r n
    case "$n" in
      1) inst_status ;; 2) inst_config ;; 3) inst_note ;;
      4) inst_log ;;   5) inst_restart ;;
      6) inst_uninstall; [ $? = 9 ] && return ;;
      0|q) return ;;
      *) warn "无效" ;;
    esac
    # 每个操作完成后暂停，让用户看到结果（否则新菜单会把反馈顶出屏幕）
    printf "  ${C_DIM}按回车继续…${C_RESET}"; read -r _
  done
}

#===============================================================================
# 主页功能：发送测试 / 配置代理 / 一键更新 / 卸载面板
#===============================================================================

# 给某个机器人发一条测试消息
_send_one() {  # $1=name $2=dir $3=env
  local token chat px resp label
  token="$(get_val "$3" TG_BOT_TOKEN)"; chat="$(get_val "$3" TG_CHAT_ID)"
  label="$(display_name "$1" "$2" "$3")"
  if [ -z "$token" ] || [ -z "$chat" ]; then
    err "「$label」未配置 token/chat_id"
    return
  fi
  px="$(proxy_args "$3")"
  resp="$(curl -fsSL --connect-timeout 12 $px -d "chat_id=$chat" \
    --data-urlencode "text=🔔 「$label」测试消息：配置正确，工作正常！" \
    -d "parse_mode=HTML" "https://api.telegram.org/bot${token}/sendMessage" 2>&1)"
  printf '%s' "$resp" | grep -q '"ok":true' \
    && ok "「$label」已发送" \
    || { err "「$label」发送失败"; printf '%s' "$resp" | grep -oE '"description":"[^"]*"' | head -1 | sed 's/^/    /'; }
}

# 列出让用户选一个机器人，把选中的 name|dir|env|service 放进全局 PICKED
# 返回 0=选好了，1=取消/无效。$1=额外选项提示（如 "a) 全部"），会设 PICKED=all
_pick_bot() {
  local extra="${1:-}"
  local list; list="$(list_instances)"
  [ -z "$list" ] && { warn "还没有机器人"; return 1; }
  local i=0 name dir env svc label
  PICK_LIST=()
  while IFS='|' read -r name dir env svc; do
    i=$((i+1)); PICK_LIST+=("$name|$dir|$env|$svc")
    label="$(display_name "$name" "$dir" "$env")"
    printf "   ${C_CYAN}「%d」${C_RESET} %s\n" "$i" "$label"
  done <<< "$list"
  [ -n "$extra" ] && echo -e "   ${C_CYAN}$extra${C_RESET}"
  printf "  选择: "; read -r _pc
  if [ -n "$extra" ] && { [ "$_pc" = "a" ] || [ "$_pc" = "A" ]; }; then
    PICKED="all"; return 0
  fi
  case "$_pc" in
    ''|*[!0-9]*) warn "无效"; return 1 ;;
    *)
      [ "$_pc" -ge 1 ] && [ "$_pc" -le "$i" ] || { warn "没有这个编号"; return 1; }
      PICKED="${PICK_LIST[$((_pc-1))]}"; return 0 ;;
  esac
}

# 主页：发送测试（选一个，或全部）
do_send_test() {
  echo -e "${C_BOLD}  发送测试${C_RESET}（选哪个机器人，或全部）"
  _pick_bot "「a」全部发送" || return
  if [ "$PICKED" = "all" ]; then
    local entry
    for entry in "${PICK_LIST[@]}"; do
      IFS='|' read -r n d e s <<< "$entry"
      _send_one "$n" "$d" "$e"
    done
  else
    IFS='|' read -r n d e s <<< "$PICKED"
    _send_one "$n" "$d" "$e"
  fi
}

# 主页：配置全局代理（一次配置，所有机器人共用，并同步重启）
do_proxy_global() {
  echo -e "${C_BOLD}  配置全局代理${C_RESET} ${C_DIM}（所有机器人共用；安装时已配的话这里可改）${C_RESET}"
  local cur; cur="$(global_proxy)"
  [ -n "$cur" ] && echo "  当前代理: $cur" || echo "  当前代理: 直连（未配置）"
  # 连通性检测
  if curl -fsSL --connect-timeout 6 -o /dev/null https://api.telegram.org 2>/dev/null; then
    ok "当前可直连 Telegram"
  else
    warn "直连 Telegram 不通（国内服务器需要代理）"
  fi
  echo -e "  ${C_DIM}（输入 0 返回）${C_RESET}"
  local p
  printf "  ${C_BOLD}代理地址${C_RESET}（如 http://127.0.0.1:7890，留空=直连）: "; read -r p
  [ "$p" = "0" ] && return
  # 验证代理可达
  if [ -n "$p" ]; then
    if curl -fsSL --connect-timeout 8 -x "$p" -o /dev/null https://api.telegram.org 2>/dev/null; then
      ok "走 $p 可连通 Telegram"
    else
      warn "走 $p 连不通 Telegram，请确认代理可用（仍可保存，稍后重试）"
    fi
  fi
  # 写全局文件
  mkdir -p "$BASE/data"
  printf '%s' "$p" > "$PROXY_CONF"
  ok "全局代理已保存：${p:-直连}"
  # 同步到每个机器人的 env 并重启
  local name dir env svc
  while IFS='|' read -r name dir env svc; do
    [ -f "$env" ] || continue
    if [ -n "$p" ]; then
      if grep -q '^https_proxy=' "$env" 2>/dev/null; then
        sed -i "s|^https_proxy=.*|https_proxy=$p|" "$env"
      else
        echo "https_proxy=$p" >> "$env"
      fi
    else
      sed -i '/^https_proxy=/d' "$env" 2>/dev/null
    fi
    systemctl restart "$svc" 2>/dev/null && ok "已同步并重启：$(display_name "$name" "$dir" "$env")"
  done <<< "$(list_instances)"
}

# 主页：一键更新（更新框架 + 所有机器人 + unmi 命令，重启全部）
do_update_all() {
  echo -e "${C_BOLD}  一键更新${C_RESET}"
  local latest cur; cur="未知"; [ -f "$BASE/VERSION" ] && cur="$(cat "$BASE/VERSION")"
  echo "    当前: $cur"
  latest="$(curl -fsSL --connect-timeout 12 $(proxy_args "$MAIN_ENV") \
    "https://api.github.com/repos/unmime/unmi_TGtool/releases/latest" 2>/dev/null \
    | grep -oE '"tag_name":[[:space:]]*"[^"]+"' | head -1 | cut -d'"' -f4)"
  [ -z "$latest" ] && { err "获取最新版本失败（网络问题）"; return; }
  echo "    最新: $latest"
  [ "$cur" = "$latest" ] && { ok "已是最新"; return; }
  printf "    ${C_BOLD}是否更新到 %s？${C_RESET} [y] 更新  [0/其它] 返回: " "$latest"
  read -r a; [ "$a" = "y" ] || { warn "已取消"; return; }

  local tmp; tmp="$(mktemp -d)"
  echo "    下载中…"
  curl -fsSL --connect-timeout 20 $(proxy_args "$MAIN_ENV") \
    "https://github.com/unmime/unmi_TGtool/releases/download/${latest}/unmi_TGtool.tar.gz" \
    -o "$tmp/p.tgz" 2>/dev/null || { err "下载失败"; rm -rf "$tmp"; return; }
  # 解压必须先成功：脚本无 set -e，解压失败若继续会删掉各实例的 core/modules 却复制不上新文件
  tar xzf "$tmp/p.tgz" -C "$tmp" || { err "解压失败（安装包损坏），未改动任何文件"; rm -rf "$tmp"; return; }
  [ -d "$tmp/unmi_TGtool/core" ] || { err "安装包结构异常，未改动任何文件"; rm -rf "$tmp"; return; }

  # 更新框架 + 每个实例目录的代码（保留各自 data 与 env）
  local d
  for d in "$BASE" "$BASE"-*/; do
    [ -d "$d" ] || continue
    cp -r "$d/data" "$tmp/dbak" 2>/dev/null || true
    rm -rf "$d/core" "$d/modules"
    cp -r "$tmp/unmi_TGtool/core" "$tmp/unmi_TGtool/modules" "$d/"
    cp "$tmp/unmi_TGtool/main.py" "$tmp/unmi_TGtool/TGcalc_bot.py" "$d/"
    mkdir -p "$d/data"; cp -r "$tmp/dbak/." "$d/data/" 2>/dev/null || true
    echo "$latest" > "$d/VERSION"
    rm -rf "$tmp/dbak"
  done
  [ -f "$tmp/unmi_TGtool/unmi-cli.sh" ] && install -m 755 "$tmp/unmi_TGtool/unmi-cli.sh" /usr/local/bin/unmi
  rm -rf "$tmp"

  # 重启所有实例服务
  local name dir env svc
  while IFS='|' read -r name dir env svc; do
    systemctl restart "$svc" 2>/dev/null && ok "已更新并重启：$(display_name "$name" "$dir" "$env")"
  done <<< "$(list_instances)"
  ok "全部更新到 $latest"
}

# 主页：卸载整个面板（删除所有机器人 + 控制台本身）
do_uninstall_panel() {
  echo -e "${C_RED}${C_BOLD}  卸载整个 unmi_TGtool 面板${C_RESET}"
  echo "    将删除：所有机器人（服务/配置/目录）、代码框架、unmi 命令"
  echo
  printf "    ${C_BOLD}确定要全部卸载？${C_RESET}输入 ${C_RED}yes${C_RESET} 确认: "; read -r a
  [ "$a" = "yes" ] || { warn "已取消"; return; }
  local name dir env svc
  while IFS='|' read -r name dir env svc; do
    systemctl stop "$svc" 2>/dev/null; systemctl disable "$svc" 2>/dev/null
    rm -f "/etc/systemd/system/$svc.service" "$env"
    ok "已删除：$(display_name "$name" "$dir" "$env")"
  done <<< "$(list_instances)"
  rm -rf "$BASE" "$BASE"-*/ 2>/dev/null
  systemctl daemon-reload
  echo
  ok "已全部卸载，unmi 命令将于退出后移除"
  (sleep 1; rm -f /usr/local/bin/unmi) &
  exit 0
}

#===============================================================================
# 主菜单
#===============================================================================

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

main_menu() {
  clear 2>/dev/null || true
  banner
  echo -e "  ${C_BOLD}unmi_TGtool 控制台${C_RESET}  ${C_DIM}集中管理本机的 Telegram 机器人${C_RESET}"
  echo

  local i=0 name dir env svc label state
  declare -a NAMES=()
  local count; count="$(list_instances | wc -l | tr -d ' ')"
  if [ "$count" = "0" ]; then
    echo -e "  ${C_DIM}还没有任何机器人。${C_RESET}"
  else
    echo -e "  ${C_BOLD}已装机器人：${C_RESET}"
    divider
    while IFS='|' read -r name dir env svc; do
      i=$((i+1)); NAMES+=("$name")
      label="$(display_name "$name" "$dir" "$env")"
      state="$(svc_state "$svc")"
      printf "   ${C_CYAN}「%d」${C_RESET} %-28s %s\n" "$i" "$label" "$state"
    done <<EOF
$(list_instances)
EOF
    divider
  fi
  echo
  echo -e "  ${C_CYAN}a${C_RESET}) 添加机器人   ${C_CYAN}t${C_RESET}) 发送测试   ${C_CYAN}p${C_RESET}) 配置代理"
  echo -e "  ${C_CYAN}u${C_RESET}) 一键更新     ${C_CYAN}x${C_RESET}) 卸载面板   ${C_CYAN}0${C_RESET}) 退出"
  echo

  local n
  printf "  选择（数字进入管理）: "; read -r n
  case "$n" in
    a|A) add_bot; printf "  ${C_DIM}按回车继续…${C_RESET}"; read -r _ ;;
    t|T) do_send_test; printf "  ${C_DIM}按回车继续…${C_RESET}"; read -r _ ;;
    p|P) do_proxy_global; printf "  ${C_DIM}按回车继续…${C_RESET}"; read -r _ ;;
    u|U) do_update_all; printf "  ${C_DIM}按回车继续…${C_RESET}"; read -r _ ;;
    x|X) do_uninstall_panel ;;
    0|q) echo "  再见"; exit 0 ;;
    ''|*[!0-9]*) warn "无效选项" ;;
    *)
      if [ "$n" -ge 1 ] && [ "$n" -le "$i" ]; then
        set_current "${NAMES[$((n-1))]}"
        inst_menu
      else
        warn "没有这个编号"
      fi ;;
  esac
}

main() {
  [ "$(id -u)" -ne 0 ] && { err "需要 root（sudo unmi）"; exit 1; }
  case "${1:-}" in
    add|a) add_bot; exit 0 ;;        # unmi add —— 直接进添加流程（安装脚本首次调用）
  esac
  while :; do
    main_menu
  done
}

main "$@"
