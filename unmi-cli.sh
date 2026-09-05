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

# 统一交互输入：ask <变量名> <提示语>
# 返回 1 = 读不到输入（stdin 已到末尾：如 `curl ... | bash` 的尾部、被管道喂空）。
# 调用方必须接住这个返回值，否则输入循环拿不到值还不停重试，会刷屏空转。
ask() {
  local __v="$1"; shift
  printf '%s' "$*"
  read -r "$__v" || return 1
}

# 操作后暂停一下，让用户看清结果（EOF 时直接结束，不留空转的循环）
pause() {
  printf '%s' "${C_DIM}  按回车继续…${C_RESET}"
  read -r _ || exit 0
  echo
}

# 输入净化：去掉控制字符（含 ESC）和反斜杠。
# 备注名这类自由文本会拼进带颜色的输出里，含 \\n 之类会被解释成转义序列，把面板排版冲乱，
# 也可能被用来伪造终端控制序列。存之前统一洗一遍最省事。
sanitize() {
  printf '%s' "$1" | tr -d '\000-\037\177' | tr -d '\\'
}

# 临时目录统一登记，脚本正常退出或被 Ctrl-C 中断都能清干净（不会在 /tmp 留垃圾）
UNMI_TMPDIRS=()
make_tmp() {
  local d; d="$(mktemp -d)" || return 1
  UNMI_TMPDIRS+=("$d")
  printf '%s' "$d"
}
cleanup_tmp() {
  local d
  for d in ${UNMI_TMPDIRS[@]+"${UNMI_TMPDIRS[@]}"}; do
    [ -n "$d" ] && rm -rf "$d"
  done
}
trap cleanup_tmp EXIT INT TERM

# 分割线（贴合主题的暗青色，区分每一屏/每次操作）
divider() { echo -e "${C_DIM}${C_CYAN}  ──────────────────────────────────────────${C_RESET}"; }

# 显示宽度：中文/全角/emoji 算 2，ASCII 算 1（用 python 精确算，退化到字符数）
_disp_width() {
  python3 -c "import sys,unicodedata;s=sys.argv[1];print(sum(2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in s))" "$1" 2>/dev/null || echo -n "$1" | wc -m | tr -d ' '
}

# 版本号比较：只看数字段（忽略前缀 v），逐段比大小。
# 用来防止「一键更新」把新版本降回旧版本 —— 比如远端标签被回退、或本地版本比远端新。
ver_ge() {  # ver_ge a b —— a >= b 返回 0，否则返回 1
  local a="${1#v}" b="${2#v}" i n x y
  local -a A B
  IFS=. read -r -a A <<< "$a"
  IFS=. read -r -a B <<< "$b"
  n=${#A[@]}; [ ${#B[@]} -gt "$n" ] && n=${#B[@]}
  i=0
  while [ "$i" -lt "$n" ]; do
    x="${A[$i]:-0}"; y="${B[$i]:-0}"
    case "$x$y" in *[!0-9]*) return 0 ;; esac   # 含非数字（预发布后缀之类）就不比较，放行
    [ "$x" -gt "$y" ] && return 0
    [ "$x" -lt "$y" ] && return 1
    i=$((i+1))
  done
  return 0
}

# 剥离 ANSI 色码（算显示宽度前必须先剥，否则色码会被当成普通字符算进去）
_plain() { printf '%s' "$1" | sed 's/\x1b\[[0-9;]*m//g'; }

# 菜单项按列对齐排版：列宽固定，按显示宽度自动补空格。
# 手敲空格对不齐 —— 「删除此机器人」比「查看状态」宽 4 格，靠肉眼数空格迟早错位。
# 用法: menu_row 「A」 添加机器人 「T」 发送测试 …
menu_row() {
  local w="${MENU_COL_W:-19}" out="" k label cur pad
  while [ "$#" -gt 0 ]; do
    k="$1"; label="${2-}"; shift; [ "$#" -gt 0 ] && shift
    cur="${C_CYAN}${k}${C_RESET} ${label}"
    pad=$(( w - $(_disp_width "$(_plain "$cur")") ))
    [ "$pad" -lt 1 ] && pad=1
    out="${out}${cur}$(printf '%*s' "$pad" '')"
  done
  printf '  %s\n' "$out" | sed 's/[[:space:]]*$//'   # 末列补的空格没用，去掉
}

# 加粗框：把传入的每一行内容用粗线框框住。
# 用法： draw_box [left|center] 行1 行2 ...
#   默认 center 居中；left 左对齐（列表用）。宽度自适应最长行（剥离 ANSI 色码算宽）。
draw_box() {
  local align="center"
  case "${1:-}" in left|center) align="$1"; shift ;; esac
  # 宽度 = max(最长行, BOX_MIN)；BOX_MIN 可让实例页标题框对齐主面板的宽度
  local maxlen="${BOX_MIN:-0}" line plain len lpad rpad
  for line in "$@"; do
    plain="$(_plain "$line")"
    len="$(_disp_width "$plain")"
    [ "$len" -gt "$maxlen" ] && maxlen="$len"
  done
  LAST_BOX_INNER=$maxlen   # 记录本次内容宽（全局），供实例页标题框对齐主面板
  echo -e "${C_BOLD}${C_CYAN}╔$(printf '═%.0s' $(seq 1 $(( maxlen + 2 ))))╗${C_RESET}"
  for line in "$@"; do
    plain="$(_plain "$line")"
    len="$(_disp_width "$plain")"
    if [ "$align" = "left" ]; then
      lpad=0; rpad=$(( maxlen - len ))
    else
      lpad=$(( (maxlen - len) / 2 )); rpad=$(( maxlen - len - lpad ))
    fi
    printf "${C_BOLD}${C_CYAN}║${C_RESET} %*s%s%*s ${C_BOLD}${C_CYAN}║${C_RESET}\n" \
      "$lpad" "" "$line" "$rpad" ""
  done
  echo -e "${C_BOLD}${C_CYAN}╚$(printf '═%.0s' $(seq 1 $(( maxlen + 2 ))))╝${C_RESET}"
}

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

# 运行状态：三种展示风格统一由这里出，避免各处自己 if/else 导致文案和配色不一致。
#   svc_state <服务名> [dot|text|en]
#     dot  🟩 运行中 / 🟥 停止（主菜单列表，默认）
#     text 运行中 / 停止（选择列表）
#     en   active / inactive（实例页标题栏）
svc_state() {
  local style="${2:-dot}"
  if systemctl is-active --quiet "$1" 2>/dev/null; then
    case "$style" in
      text) echo -e "${C_GREEN}运行中${C_RESET}" ;;
      en)   echo -e "${C_GREEN}active${C_RESET}" ;;
      *)    echo -e "${C_GREEN}🟩 运行中${C_RESET}" ;;
    esac
  else
    case "$style" in
      text) echo -e "${C_RED}停止${C_RESET}" ;;
      en)   echo -e "${C_RED}inactive${C_RESET}" ;;
      *)    echo -e "${C_RED}🟥 停止${C_RESET}" ;;
    esac
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

# 显示用名字：备注 + @电报号（备注在前；没起别名或别名即电报号时不重复）
display_name() {  # $1=name $2=dir $3=env
  local label un
  label="$(get_val "$3" INSTANCE_LABEL)"
  un="$(bot_username "$2" "$3")"
  if [ -n "$label" ] && [ -n "$un" ] && [ "$label" != "$un" ]; then
    echo "$label $un"            # 备注 + @电报号
  elif [ -n "$label" ]; then
    echo "$label"
  elif [ -n "$un" ]; then
    echo "$un"
  else
    echo "$1"
  fi
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

  local token c
  echo -e "  ${C_DIM}（输 0 或 q 可随时取消添加）${C_RESET}"
  while :; do
    ask token "  ${C_BOLD}Bot Token${C_RESET}（形如 123456:ABC-DEF...）: " || return
    [ "$token" = "0" ] || [ "$token" = "q" ] && { warn "已取消添加"; return; }
    printf '%s' "$token" | grep -qE '^[0-9]+:[A-Za-z0-9_-]{20,}$' && break
    warn "token 格式不对，重新输入（输 0 取消）"
  done

  # 同 token 查重：这个 token 已被别的实例占用的话，两个进程会互相抢消息
  local f
  for f in /etc/unmi_TGtool*.env; do
    [ -f "$f" ] || continue
    if grep -q "^TG_BOT_TOKEN=${token}$" "$f" 2>/dev/null; then
      warn "这个 token 已被实例（$f）占用，同 token 跑两个会互相抢消息"
      ask c "  仍要添加？[y/N] " || return; [ "$c" = "y" ] || return
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
    if [ -z "$proxy" ]; then
      echo -e "  ${C_DIM}提示：当前未配代理，国内服务器很可能因此连不上 Telegram。${C_RESET}"
      echo -e "  ${C_DIM}      可先到主页选「P 配置代理」填好，再回来添加。${C_RESET}"
    fi
    ask c "  仍要继续添加？[y/N] " || return; [ "$c" = "y" ] || return
  fi

  divider
  echo -e "${C_CYAN}${C_BOLD}【第 2 步】Chat ID${C_RESET} ${C_DIM}（你的 Telegram 用户 ID，纯数字；必填，不可跳过）${C_RESET}"
  local chat
  while :; do
    ask chat "  ${C_BOLD}Chat ID${C_RESET}（纯数字，输 ${C_BOLD}0${C_RESET} 取消）: " || return
    [ "$chat" = "0" ] || [ "$chat" = "q" ] && { warn "已取消添加"; return; }
    printf '%s' "$chat" | grep -qE '^-?[0-9]+$' && break
    warn "chat id 必须是数字，重新输入（输 0 取消）"
  done

  divider
  echo -e "${C_CYAN}${C_BOLD}【第 3 步】备注${C_RESET} ${C_DIM}（给机器人起个好认的名字，用于面板显示）${C_RESET}"
  local label slug
  ask label "  ${C_BOLD}备注名${C_RESET}（默认 @${un:-bot}，输 ${C_BOLD}q${C_RESET} 取消）: " || return
  [ "$label" = "q" ] && { warn "已取消添加"; return; }
  label="$(sanitize "$label")"
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
    ask c "  覆盖重装？[y/N] " || return; [ "$c" = "y" ] || return
  fi

  # 落地：复制程序、写 env、建服务、启动
  divider
  echo -e "  ${C_DIM}创建实例 $slug …${C_RESET}"
  if [ "$dir" != "$BASE" ]; then
    mkdir -p "$dir"
    cp -r "$BASE/core" "$BASE/modules" "$dir/" 2>/dev/null || true
    cp "$BASE/main.py" "$dir/" 2>/dev/null
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

  # 添加完成，直接进入这个机器人的管理页面（而不是退回主菜单）
  local iname="main"; [ "$dir" != "$BASE" ] && iname="$slug"
  echo
  echo -e "  ${C_DIM}进入「$label」的管理页面…${C_RESET}"
  sleep 1
  set_current "$iname"
  inst_menu
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

cur_val()   { get_val "$CUR_ENV" "$1"; }
cur_proxy_args() { local p; p="$(cur_val https_proxy)"; [ -n "$p" ] && printf -- '-x %s' "$p" || printf ''; }

inst_status() {
  echo -e "  名称:   ${C_BOLD}$CUR_LABEL${C_RESET}（实例 $CUR_NAME）"
  echo -e "  运行:   $(svc_state "$CUR_SVC")"
  echo    "  目录:   $CUR_DIR"
  echo    "  配置:   $CUR_ENV"
  local t c p v; t="$(cur_val TG_BOT_TOKEN)"; c="$(cur_val TG_CHAT_ID)"; p="$(cur_val https_proxy)"
  v="?"; [ -f "$CUR_DIR/VERSION" ] && v="$(cat "$CUR_DIR/VERSION")"
  echo    "  版本:   $v"
  [ -n "$t" ] && echo "  token:  ${t:0:10}…（已配置）" || echo "  token:  未配置"
  [ -n "$c" ] && echo "  chat:   $c" || echo "  chat:   未配置"
  [ -n "$p" ] && echo "  代理:   $p" || echo "  代理:   未配置（直连）"
}

# 统一写 env：以原文件为底，只覆盖本次传入的键，其余字段（含以后新增的未知键）原样保留。
# 先写临时文件再原子替换，中途被打断也不会留下写了一半的配置。
# 刻意不用关联数组：保持 bash 3.2 兼容（macOS 自带 bash 仍是 3.2，方便本地自测）。
save_env() {  # 用法: save_env KEY=VAL [KEY=VAL ...]（作用于当前实例 $CUR_ENV）
  local tmpf kv k v
  tmpf="$(mktemp "${CUR_ENV}.tmp.XXXXXX")" || { err "无法创建临时文件"; return 1; }
  cp -f "$CUR_ENV" "$tmpf" 2>/dev/null || : > "$tmpf"

  for kv in "$@"; do
    k="${kv%%=*}"; v="${kv#*=}"
    [ -n "$k" ] || continue
    if grep -q "^${k}=" "$tmpf" 2>/dev/null; then
      # 按第一个 = 切分来定位键，值里的 / & = 都不会被当成特殊字符
      if [ -n "$v" ]; then
        awk -v key="$k" -v val="$v" 'BEGIN{FS="="} $1==key {print key "=" val; next} {print}' \
          "$tmpf" > "$tmpf.n"
      else
        # 传空值等于删除这一项
        awk -v key="$k" 'BEGIN{FS="="} $1==key {next} {print}' "$tmpf" > "$tmpf.n"
      fi
      mv -f "$tmpf.n" "$tmpf"
    else
      [ -n "$v" ] && printf '%s=%s\n' "$k" "$v" >> "$tmpf"
    fi
  done

  # DATA_DIR 是运行目录，必须有个值；旧配置里也没有就补默认路径
  grep -q '^DATA_DIR=' "$tmpf" 2>/dev/null || printf 'DATA_DIR=%s\n' "$CUR_DIR/data" >> "$tmpf"

  chmod 600 "$tmpf"
  mv -f "$tmpf" "$CUR_ENV"
}

inst_config() {
  local token chat
  echo -e "  ${C_DIM}（随时输入 0 返回菜单）${C_RESET}"
  ask token "  Bot Token: " || return
  [ "$token" = "0" ] && return
  printf '%s' "$token" | grep -qE '^[0-9]+:[A-Za-z0-9_-]{20,}$' || { err "格式不对"; return; }
  ask chat "  Chat ID: " || return
  [ "$chat" = "0" ] && return
  printf '%s' "$chat" | grep -qE '^-?[0-9]+$' || { err "必须是数字"; return; }
  save_env TG_BOT_TOKEN="$token" TG_CHAT_ID="$chat"
  rm -f "$CUR_DIR/data/botinfo"
  systemctl restart "$CUR_SVC" && ok "已保存并重启"
}

inst_test() {
  local token chat; token="$(cur_val TG_BOT_TOKEN)"; chat="$(cur_val TG_CHAT_ID)"
  [ -z "$token" ] || [ -z "$chat" ] && { err "先配置 token / chat_id"; return; }
  local _px; _px="$(cur_val https_proxy)"
  echo "  发送中…（代理：${_px:-无}）"
  local resp
  resp="$(curl -fsSL --connect-timeout 12 $(cur_proxy_args) -d "chat_id=$chat" \
    --data-urlencode "text=🔔 「$CUR_LABEL」测试消息：配置正确，工作正常！" \
    -d "parse_mode=HTML" "https://api.telegram.org/bot${token}/sendMessage" 2>&1)"
  printf '%s' "$resp" | grep -q '"ok":true' && ok "已发送" \
    || { err "发送失败"; printf '%s' "$resp" | grep -oE '"description":"[^"]*"' | head -1 | sed 's/^/    /'; }
}

inst_proxy() {
  local p; p="$(cur_val https_proxy)"; [ -n "$p" ] && echo "  当前：$p"
  echo -e "  ${C_DIM}（输入 0 返回菜单）${C_RESET}"
  ask p "  代理地址（留空清除）: " || return
  [ "$p" = "0" ] && return
  save_env https_proxy="$p"
  [ -n "$p" ] && ok "代理已设为 $p" || ok "已清除代理"
  systemctl restart "$CUR_SVC" >/dev/null 2>&1 && ok "已重启生效"
}

# 添加/修改备注（存在 env 的 INSTANCE_NOTE，标题栏显示）
inst_note() {
  local cur; cur="$(cur_val INSTANCE_NOTE)"
  [ -n "$cur" ] && echo "  当前备注：$cur"
  echo -e "  ${C_DIM}（输入 0 返回菜单）${C_RESET}"
  ask cur "  备注（留空清除）: " || return
  [ "$cur" = "0" ] && return
  cur="$(sanitize "$cur")"
  save_env INSTANCE_NOTE="$cur"
  CUR_NOTE="$cur"
  [ -n "$cur" ] && ok "备注已保存：$cur" || ok "备注已清除"
}

inst_log()     { journalctl -u "$CUR_SVC" -n 30 --no-pager; }
inst_restart() { systemctl restart "$CUR_SVC" && ok "已重启"; }

inst_update() {
  local latest cur; cur="未知"; [ -f "$CUR_DIR/VERSION" ] && cur="$(cat "$CUR_DIR/VERSION")"
  echo "    当前: $cur"
  latest="$(curl -fsSL --connect-timeout 12 $(cur_proxy_args) \
    "https://api.github.com/repos/unmime/unmi_TGtool/releases/latest" 2>/dev/null \
    | grep -oE '"tag_name":[[:space:]]*"[^"]+"' | head -1 | cut -d'"' -f4)"
  [ -z "$latest" ] && { err "获取最新版本失败（网络问题）"; return; }
  echo "    最新: $latest"
  [ "$cur" = "$latest" ] && { ok "已是最新"; return; }
  # 远端比当前旧：不直接拦死（版本号重置时会出现这种情况，硬拦就永远升不了级），
  # 但要说清楚并让用户输入 downgrade 二次确认，避免手滑把新版本刷回旧版本。
  if [ "$cur" != "未知" ] && ver_ge "$cur" "$latest"; then
    warn "远端 $latest 不高于当前 $cur —— 继续的话会回退到旧版本"
    ask a "    ${C_BOLD}确认降级？${C_RESET} 输入 downgrade 继续，其它任意键取消: " || return
    [ "$a" = "downgrade" ] || { warn "已取消"; return; }
  fi
  echo
  ask a "    ${C_BOLD}是否更新到 ${latest}？${C_RESET} [y] 更新  [0/其它] 返回: " || return
  [ "$a" = "y" ] || { warn "已取消"; return; }
  local tmp; tmp="$(make_tmp)" || { err "无法创建临时目录"; return; }
  curl -fsSL --connect-timeout 20 $(cur_proxy_args) \
    "https://github.com/unmime/unmi_TGtool/releases/download/${latest}/unmi_TGtool.tar.gz" \
    -o "$tmp/p.tgz" 2>/dev/null || { err "下载失败"; rm -rf "$tmp"; return; }
  cp -r "$CUR_DIR/data" "$tmp/dbak" 2>/dev/null || true
  # 解压必须先成功：脚本无 set -e，解压失败若继续会删掉 core/modules 却复制不上新文件
  tar xzf "$tmp/p.tgz" -C "$tmp" || { err "解压失败（安装包损坏），未改动任何文件"; rm -rf "$tmp"; return; }
  [ -d "$tmp/unmi_TGtool/core" ] || { err "安装包结构异常，未改动任何文件"; rm -rf "$tmp"; return; }
  rm -rf "$CUR_DIR/core" "$CUR_DIR/modules"
  cp -r "$tmp/unmi_TGtool/core" "$tmp/unmi_TGtool/modules" "$CUR_DIR/"
  cp "$tmp/unmi_TGtool/main.py" "$CUR_DIR/"
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
  ask a "    ${C_BOLD}是否删除？${C_RESET} [y] 删除  [0/其它] 取消: " || return
  [ "$a" = "y" ] || { warn "已取消"; return; }
  systemctl stop "$CUR_SVC" 2>/dev/null; systemctl disable "$CUR_SVC" 2>/dev/null
  rm -f "/etc/systemd/system/$CUR_SVC.service" "$CUR_ENV"
  [ "$CUR_NAME" != "main" ] && rm -rf "$CUR_DIR" || warn "主实例目录保留（其它实例可能共享其代码）"
  systemctl daemon-reload
  ok "已删除「$CUR_LABEL」"
  return 9
}

inst_menu() {
  local n _note _st
  while :; do
    _note="$(cur_val INSTANCE_NOTE)"
    _st="$(svc_state "$CUR_SVC" en)"
    echo
    # 标题框宽度对齐主面板（用主面板实例列表框的宽度），不再只按标题宽度收窄
    local BOX_MIN="${LAST_BOX_INNER:-0}"
    if [ -n "$_note" ]; then
      draw_box "🤖 $CUR_LABEL ${C_PINK}（$_note）${C_RESET}" "${C_DIM}$CUR_SVC${C_RESET} · $_st"
    else
      draw_box "🤖 $CUR_LABEL" "${C_DIM}$CUR_SVC${C_RESET} · $_st"
    fi
    menu_row "「1」" "查看状态" "「2」" "配置机器人"   "「3」" "添加备注"
    menu_row "「4」" "查看日志" "「5」" "删除此机器人" "「0」" "返回面板"
    divider
    ask n "  选择: " || return
    case "$n" in
      1) inst_status ;; 2) inst_config ;; 3) inst_note ;;
      4) inst_log ;;
      5) inst_uninstall; [ $? = 9 ] && return ;;
      0|q) return ;;
      *) warn "无效" ;;
    esac
    # 每个操作完成后暂停，让用户看到结果（否则新菜单会把反馈顶出屏幕）
    pause
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
  local i=0 name dir env svc label state
  PICK_LIST=()
  while IFS='|' read -r name dir env svc; do
    i=$((i+1)); PICK_LIST+=("$name|$dir|$env|$svc")
    label="$(display_name "$name" "$dir" "$env")"
    state="$(svc_state "$svc" text)"
    # 不能用 printf 的 %-30s：它按字符数补空格，中文占 2 格却只算 1 个字符，列会错开。
    # 这里按显示宽度算补多少，和 menu_row 保持一致。
    local _pad=$(( 30 - $(_disp_width "$label") ))
    [ "$_pad" -lt 1 ] && _pad=1
    printf "   ${C_CYAN}「%d」${C_RESET} %s%*s %s\n" "$i" "$label" "$_pad" "" "$state"
  done <<< "$list"
  [ -n "$extra" ] && echo -e "   ${C_CYAN}$extra${C_RESET}"
  ask _pc "  选择: " || return 1
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
  # 连通性检测（要等几秒，先给提示，别让用户以为卡死）
  echo -e "  ${C_DIM}正在检测 Telegram 连通性，请稍候…${C_RESET}"
  if curl -fsSL --connect-timeout 6 -o /dev/null https://api.telegram.org 2>/dev/null; then
    ok "当前可直连 Telegram"
  else
    warn "直连 Telegram 不通（国内服务器需要代理）"
  fi
  divider
  # 操作说明：回车=保持现状（点错了安全退出），输地址=修改，输「直连」=清除代理
  echo -e "  ${C_BOLD}怎么操作：${C_RESET}"
  echo -e "    ${C_DIM}直接回车${C_RESET}   = 保持现状（点错了就这样退出，不会改动）"
  echo -e "    ${C_DIM}输入地址${C_RESET}   = 改成这个代理（如 http://127.0.0.1:7890）"
  echo -e "    ${C_DIM}输入「直连」${C_RESET} = 清除代理，改回直连"
  local p
  ask p "  ${C_BOLD}请选择${C_RESET}: " || return
  case "$p" in
    ""|0)              warn "未做修改"; return ;;          # 回车/0 = 保持现状
    直连|direct|none|-) p="" ;;                             # 明确要直连才清代理
  esac
  # 验证代理可达（只在设了代理时）
  if [ -n "$p" ]; then
    echo -e "  ${C_DIM}验证代理连通性…${C_RESET}"
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
    # 不用 sed：代理地址里若含 |（sed 的分隔符）会直接写坏配置。
    # 一律走 awk 按第一个 = 切分重写，值里出现任何符号都安全。
    local _t; _t="$(mktemp)" || return
    if [ -n "$p" ]; then
      if grep -q '^https_proxy=' "$env" 2>/dev/null; then
        awk -v val="$p" 'BEGIN{FS="="} $1=="https_proxy" {print "https_proxy=" val; next} {print}' \
          "$env" > "$_t"
      else
        cp -f "$env" "$_t"; printf 'https_proxy=%s\n' "$p" >> "$_t"
      fi
    else
      grep -v '^https_proxy=' "$env" > "$_t" 2>/dev/null || cp -f "$env" "$_t"
    fi
    chmod 600 "$_t"; mv -f "$_t" "$env"
    systemctl restart "$svc" 2>/dev/null && ok "已同步并重启：$(display_name "$name" "$dir" "$env")"
  done <<< "$(list_instances)"
}

# 主页：重启服务（选一个机器人，或全部重启）
do_restart_pick() {
  echo -e "${C_BOLD}  重启服务${C_RESET}（选哪个机器人，或全部）"
  _pick_bot "「a」全部重启" || return
  if [ "$PICKED" = "all" ]; then
    local entry n d e s
    for entry in "${PICK_LIST[@]}"; do
      IFS='|' read -r n d e s <<< "$entry"
      systemctl restart "$s" 2>/dev/null && ok "已重启：$(display_name "$n" "$d" "$e")"
    done
  else
    local n d e s
    IFS='|' read -r n d e s <<< "$PICKED"
    systemctl restart "$s" 2>/dev/null && ok "已重启：$(display_name "$n" "$d" "$e")"
  fi
}

# 主页：开 / 关机器人（选一个；运行中→停止，已停止→启动）
do_toggle_bot() {
  echo -e "${C_BOLD}  开 / 关机器人${C_RESET}（选哪个）"
  _pick_bot || return
  local n d e s label
  IFS='|' read -r n d e s <<< "$PICKED"
  label="$(display_name "$n" "$d" "$e")"
  if systemctl is-active --quiet "$s" 2>/dev/null; then
    ask a "  「${label}」当前${C_GREEN}运行中${C_RESET}，要${C_BOLD}停止${C_RESET}它吗？[y/N] " || return
    [ "$a" = "y" ] || { warn "已取消"; return; }
    systemctl stop "$s" && ok "已停止「$label」"
  else
    ask a "  「${label}」当前${C_RED}已停止${C_RESET}，要${C_BOLD}启动${C_RESET}它吗？[y/N] " || return
    [ "$a" = "y" ] || { warn "已取消"; return; }
    systemctl start "$s" && ok "已启动「$label」"
  fi
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
  # 远端比当前旧：不直接拦死（版本号重置时会出现这种情况，硬拦就永远升不了级），
  # 但要说清楚并让用户输入 downgrade 二次确认，避免手滑把新版本刷回旧版本。
  if [ "$cur" != "未知" ] && ver_ge "$cur" "$latest"; then
    warn "远端 $latest 不高于当前 $cur —— 继续的话会回退到旧版本"
    ask a "    ${C_BOLD}确认降级？${C_RESET} 输入 downgrade 继续，其它任意键取消: " || return
    [ "$a" = "downgrade" ] || { warn "已取消"; return; }
  fi
  ask a "    ${C_BOLD}是否更新到 ${latest}？${C_RESET} [y] 更新  [0/其它] 返回: " || return
  [ "$a" = "y" ] || { warn "已取消"; return; }

  local tmp; tmp="$(make_tmp)" || { err "无法创建临时目录"; return; }
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
    cp "$tmp/unmi_TGtool/main.py" "$d/"
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
  ask a "    ${C_BOLD}确定要全部卸载？${C_RESET}输入 ${C_RED}yes${C_RESET} 确认: " || return
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
  divider
  banner
  echo -e "  ${C_BOLD}unmi_TGtool 控制台${C_RESET}  ${C_DIM}集中管理本机的 Telegram 机器人${C_RESET}"
  local _ver="?"; [ -f "$BASE/VERSION" ] && _ver="$(cat "$BASE/VERSION")"
  echo -e "  ${C_CYAN}${C_DIM}https://github.com/unmime/unmi_TGtool${C_RESET}   ${C_YELLOW}${_ver}${C_RESET}"
  echo

  local i=0 name dir env svc lab un st namepart np_plain
  declare -a NAMES=() ITEMS=()
  local count; count="$(list_instances | wc -l | tr -d ' ')"
  if [ "$count" = "0" ]; then
    draw_box left "${C_BOLD}已装机器人：${C_RESET}" "${C_DIM}（还没有机器人，按 a 添加一个）${C_RESET}"
  else
    # 收集各实例：备注(主题色) + @电报号(淡粉) + 状态(绿/红方块)；算最长名让状态列对齐
    local maxlab=0 ll
    while IFS='|' read -r name dir env svc; do
      i=$((i+1)); NAMES+=("$name")
      lab="$(get_val "$env" INSTANCE_LABEL)"
      un="$(bot_username "$dir" "$env")"
      if [ -n "$lab" ] && [ -n "$un" ] && [ "$lab" != "$un" ]; then
        namepart="${C_CYAN}${lab}${C_RESET} ${C_PINK}${un}${C_RESET}"; np_plain="$lab $un"
      elif [ -n "$lab" ]; then
        namepart="${C_CYAN}${lab}${C_RESET}"; np_plain="$lab"
      elif [ -n "$un" ]; then
        namepart="${C_PINK}${un}${C_RESET}"; np_plain="$un"
      else
        namepart="${C_CYAN}${name}${C_RESET}"; np_plain="$name"
      fi
      st="$(svc_state "$svc")"
      ITEMS+=("$i"$'\x01'"$namepart"$'\x01'"$np_plain"$'\x01'"$st")
      ll="$(_disp_width "$np_plain")"; [ "$ll" -gt "$maxlab" ] && maxlab="$ll"
    done <<EOF
$(list_instances)
EOF
    # 生成实例行并记下最长行宽；下划线用与框一致的粗线 ═，长度取最长行宽（顶到框边）
    local rowlines=() maxrow=0 it num row rowplain rl
    for it in "${ITEMS[@]}"; do
      num="${it%%$'\x01'*}"; it="${it#*$'\x01'}"
      namepart="${it%%$'\x01'*}"; it="${it#*$'\x01'}"
      np_plain="${it%%$'\x01'*}"; st="${it#*$'\x01'}"
      ll="$(_disp_width "$np_plain")"
      row="$(printf "${C_CYAN}「%s」${C_RESET} %s%*s  %s" "$num" "$namepart" "$((maxlab-ll))" "" "$st")"
      rowlines+=("$row")
      rowplain="$(printf '%s' "$row" | sed 's/\x1b\[[0-9;]*m//g')"
      rl="$(_disp_width "$rowplain")"; [ "$rl" -gt "$maxrow" ] && maxrow="$rl"
    done
    local lines=() row
    for row in "${rowlines[@]}"; do
      lines+=("$row")
      lines+=("${C_DIM}$(printf '═%.0s' $(seq 1 "$maxrow"))${C_RESET}")
    done
    echo
    draw_box left "${C_BOLD}已装机器人：${C_RESET}" "${lines[@]}"
  fi
  echo
  menu_row "「A」" "添加机器人" "「T」" "发送测试"   "「S」" "开关机器人"
  menu_row "「R」" "重启服务"   "「P」" "配置代理"   "「U」" "一键更新"
  menu_row "「X」" "卸载面板"   "「0」" "退出"
  divider

  local n
  ask n "  选择（数字进入管理）: " || exit 0
  case "$n" in
    a|A) add_bot; pause ;;
    t|T) do_send_test; pause ;;
    s|S) do_toggle_bot; pause ;;
    r|R) do_restart_pick; pause ;;
    p|P) do_proxy_global; pause ;;
    u|U) do_update_all; pause ;;
    x|X) do_uninstall_panel ;;
    0|q) echo "  再见"; exit 0 ;;
    ''|*[!0-9]*) warn "无效选项" ;;
    *)
      if [ "$n" -ge 1 ] && [ "$n" -le "$i" ]; then
        divider
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
