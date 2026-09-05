#!/usr/bin/env bash
# unmi_TGtool 一键安装（开箱即用：计算器 bot，可插拔框架）
# 用法： sudo ./install.sh "<BOT_TOKEN>" "<CHAT_ID>" [--no-start]
set -euo pipefail

NO_START=0
for a in "$@"; do [ "$a" = "--no-start" ] && NO_START=1; done
set -- "${@/--no-start/}" 2>/dev/null || true

TOKEN="${1:-${TG_BOT_TOKEN:-}}"
CHAT="${2:-${TG_CHAT_ID:-}}"
APP_DIR="/opt/unmi_TGtool"
ENV_FILE="/etc/unmi_TGtool.env"
SERVICE="unmi_TGtool"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -z "$TOKEN" ] || [ -z "$CHAT" ]; then
  echo "用法: sudo $0 <BOT_TOKEN> <CHAT_ID>" >&2
  exit 2
fi
if [ "$(id -u)" -ne 0 ]; then
  echo "请用 sudo 运行" >&2
  exit 2
fi
command -v python3 >/dev/null || { echo "需要 python3" >&2; exit 2; }

echo "==> 检查 token 冲突（同一 token 只能有一个进程做 getUpdates）"
if command -v pgrep >/dev/null; then
  if pgrep -af "getUpdates|main\.py|TG.*_bot\.py" 2>/dev/null | grep -v grep | grep -q .; then
    echo "    检测到可能已在运行的 bot 进程："
    pgrep -af "main\.py|TG.*_bot\.py" 2>/dev/null | grep -v grep | sed 's/^/      /' || true
    # 读不到输入（非交互安装）就当「不继续」，别让 set -e 把安装流程打断
    read -r -p "    仍要继续安装？[y/N] " ans || ans=""
    [ "$ans" = "y" ] || { echo "已取消"; exit 1; }
  fi
fi

echo "==> 安装到 $APP_DIR"
mkdir -p "$APP_DIR"
cp -r "$SRC_DIR/core" "$APP_DIR/"
cp -r "$SRC_DIR/modules" "$APP_DIR/"
cp -r "$SRC_DIR/data" "$APP_DIR/"
install -m 644 "$SRC_DIR/main.py" "$APP_DIR/"
[ -f "$SRC_DIR/VERSION" ] && install -m 644 "$SRC_DIR/VERSION" "$APP_DIR/VERSION"
# 控制台命令：不装的话装完还得再跑一遍在线脚本才能用 unmi
if [ -f "$SRC_DIR/unmi-cli.sh" ]; then
  # 重装时沿用用户改过的命令名（存运行数据目录，不会被代码覆盖）
  PANEL_CMD="$(tr -d ' \t\r\n' < "$APP_DIR/data/panel-cmd.conf" 2>/dev/null)"
  PANEL_CMD="${PANEL_CMD:-unmi}"
  install -m 755 "$SRC_DIR/unmi-cli.sh" "/usr/local/bin/$PANEL_CMD"
  echo "    已安装控制台命令：$PANEL_CMD"
fi
[ -f "$SRC_DIR/selftest_calc.py" ] && install -m 644 "$SRC_DIR/selftest_calc.py" "$APP_DIR/"
[ -f "$SRC_DIR/selftest_public.py" ] && install -m 644 "$SRC_DIR/selftest_public.py" "$APP_DIR/"

echo "==> 写配置 $ENV_FILE"
umask 077
cat > "$ENV_FILE" <<EOF
TG_BOT_TOKEN=$TOKEN
TG_CHAT_ID=$CHAT
DATA_DIR=$APP_DIR/data
EOF
chmod 600 "$ENV_FILE"

echo "==> 离线自检"
set -a
# shellcheck source=/dev/null   # ENV_FILE 是变量路径，shellcheck 无法静态跟踪
. "$ENV_FILE"
set +a
python3 "$APP_DIR/main.py" --dry-run

echo "==> 安装 systemd 服务"
if [ -f "$SRC_DIR/unmi_TGtool.service" ]; then
  install -m 644 "$SRC_DIR/unmi_TGtool.service" "/etc/systemd/system/$SERVICE.service"
fi

systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null 2>&1 || true

if [ "$NO_START" = "1" ]; then
  echo
  echo "✅ 安装完成（未启动，--no-start）"
  echo "   手动启动：sudo systemctl start $SERVICE"
  exit 0
fi

systemctl restart "$SERVICE"
sleep 2
echo
if systemctl is-active --quiet "$SERVICE"; then
  echo "✅ 已启动：$SERVICE"
  echo "   去 Telegram 给 bot 发 66*98，就会出结果。"
else
  echo "❌ 启动失败："
  journalctl -u "$SERVICE" -n 20 --no-pager
  exit 1
fi
