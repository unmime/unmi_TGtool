#!/usr/bin/env bash
# 独立计算器 Telegram bot 一键安装
# 用法： sudo ./install.sh "<BOT_TOKEN>" "<CHAT_ID>" [--no-start]
#   --no-start  只装文件和 systemd，不启动服务（用于演练 / 稍后手动切换）
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
  echo "  也可以先 export TG_BOT_TOKEN / TG_CHAT_ID 再执行" >&2
  exit 2
fi
if [ "$(id -u)" -ne 0 ]; then
  echo "请用 sudo 运行（要写 /opt 和 systemd）" >&2
  exit 2
fi
command -v python3 >/dev/null || { echo "需要 python3" >&2; exit 2; }

echo "==> 检查 token 冲突（同一 token 只能有一个进程做 getUpdates）"
if command -v pgrep >/dev/null; then
  if pgrep -af "getUpdates|TGcalcbot.py" 2>/dev/null | grep -v grep | grep -q .; then
    echo "    检测到可能已在运行的 bot 进程："
    pgrep -af "TGcalcbot.py" 2>/dev/null | grep -v grep | sed 's/^/      /' || true
    echo "    如果它们用的是同一个 token，两边会互相抢消息。"
    read -r -p "    仍要继续安装？[y/N] " ans
    [ "$ans" = "y" ] || { echo "已取消"; exit 1; }
  fi
fi

echo "==> 安装到 $APP_DIR"
mkdir -p "$APP_DIR"
install -m 644 "$SRC_DIR/calc.py" "$APP_DIR/calc.py"
install -m 644 "$SRC_DIR/TGcalcbot.py"  "$APP_DIR/TGcalcbot.py"
[ -f "$SRC_DIR/selftest_calc.py" ] && install -m 644 "$SRC_DIR/selftest_calc.py" "$APP_DIR/selftest_calc.py"
[ -f "$SRC_DIR/selftest_TGcalcbot.py" ] && install -m 644 "$SRC_DIR/selftest_TGcalcbot.py" "$APP_DIR/selftest_TGcalcbot.py"

echo "==> 写配置 $ENV_FILE"
umask 077
cat > "$ENV_FILE" <<EOF
TG_BOT_TOKEN=$TOKEN
TG_CHAT_ID=$CHAT
EOF
chmod 600 "$ENV_FILE"

echo "==> 离线自检"
TG_BOT_TOKEN="$TOKEN" TG_CHAT_ID="$CHAT" python3 "$APP_DIR/TGcalcbot.py" --dry-run

echo "==> 安装 systemd 服务"
if [ -f "$SRC_DIR/unmi_TGtool.service" ]; then
  install -m 644 "$SRC_DIR/unmi_TGtool.service" "/etc/systemd/system/$SERVICE.service"
else
  cat > "/etc/systemd/system/$SERVICE.service" <<'EOF'
[Unit]
Description=Telegram Calculator Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=/etc/unmi_TGtool.env
WorkingDirectory=/opt/unmi_TGtool
ExecStart=/usr/bin/python3 /opt/unmi_TGtool/TGcalcbot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
fi

systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null 2>&1 || true

if [ "$NO_START" = "1" ]; then
  echo
  echo "✅ 安装完成（未启动，--no-start）"
  echo "   配置：$ENV_FILE"
  echo "   目录：$APP_DIR"
  echo "   手动启动：sudo systemctl start $SERVICE"
  echo "   ⚠️ 启动前确认：同一 bot token 不能有两个进程同时轮询 getUpdates"
  exit 0
fi

systemctl restart "$SERVICE"
sleep 2

echo
if systemctl is-active --quiet "$SERVICE"; then
  echo "✅ 已启动：$SERVICE"
  systemctl is-active "$SERVICE"
  echo
  echo "现在去 Telegram 给 bot 发一条消息（任意内容），它就能给你推送了。"
  echo "常用命令："
  echo "  sudo systemctl status $SERVICE"
  echo "  sudo journalctl -u $SERVICE -f"
  echo "  sudo systemctl restart $SERVICE"
else
  echo "❌ 启动失败，看日志："
  journalctl -u "$SERVICE" -n 20 --no-pager
  exit 1
fi
