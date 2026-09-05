#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独立计算器 Telegram bot。

零第三方依赖（纯标准库），只依赖同目录的 calc.py。
自带消息轮询，不依赖任何 bot 框架，可以直接搬到任意有 Python3 的机器上跑。

用法：
    TG_BOT_TOKEN=xxx TG_CHAT_ID=yyy python3 TGcalcbot.py
    python3 TGcalcbot.py --dry-run          # 不联网，只自检（用于验证安装）

注意：同一个 bot token 只能有一个进程在做 getUpdates 轮询。
如果机器上已有别的程序在用同一个 token，两边会互相抢消息 —— install.sh 会做检查。
"""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import calc  # noqa: E402  计算器核心（AST 白名单求值 + 设置 + 面板）

BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TG_CHAT_ID", "")
TELEGRAM_API = "https://api.telegram.org/bot%s" % BOT_TOKEN


# ---------------------------------------------------------------------------
# Telegram API
# ---------------------------------------------------------------------------

def tg_call(method, params):
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request("%s/%s" % (TELEGRAM_API, method), data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            r = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        r = {"ok": False, "error": "HTTP %s: %s" % (e.code, e.read().decode("utf-8", "ignore")[:200])}
    except Exception as e:  # noqa: BLE001
        r = {"ok": False, "error": str(e)}
    if not r.get("ok") and method != "getUpdates":
        sys.stderr.write("[calc-bot] tg %s FAILED: %s\n" % (method, str(r)[:200]))
    return r


def send_html(text, buttons=None, silent=False):
    params = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML",
              "disable_web_page_preview": "true",
              "disable_notification": "true" if silent else "false"}
    if buttons:
        params["reply_markup"] = json.dumps({"inline_keyboard": buttons}, ensure_ascii=False)
    return tg_call("sendMessage", params)


def edit_message(chat_id, message_id, text, buttons=None):
    params = {"chat_id": chat_id, "message_id": message_id, "text": text,
              "parse_mode": "HTML", "disable_web_page_preview": "true"}
    if buttons:
        params["reply_markup"] = json.dumps({"inline_keyboard": buttons}, ensure_ascii=False)
    return tg_call("editMessageText", params)


def answer_cb(cb_id, text):
    return tg_call("answerCallbackQuery", {"callback_query_id": cb_id, "text": text})


def delete_message(chat_id, message_id):
    return tg_call("deleteMessage", {"chat_id": chat_id, "message_id": message_id})


# ---------------------------------------------------------------------------
# 文案
# ---------------------------------------------------------------------------

HELP = (
    u"🧮 <b>计算器</b>\n\n"
    u"直接发算式就出结果，不用任何命令：\n"
    u"<code>66*98</code> → 6468\n"
    u"<code>(12+8)/4</code> → 5\n\n"
    u"<b>结果分两段，点哪段复制哪段：</b>\n"
    u"· 点 <code>66*98=6468</code> —— 复制整段\n"
    u"· 点 <code>6468</code> —— 只复制结果\n\n"
    u"<b>命令</b>\n"
    u"<code>/calc</code> —— 打开设置面板\n"
    u"<code>/calc set 4</code> —— 小数保留 4 位（0~10）\n"
    u"<code>/start</code> /help —— 本说明"
)

WELCOME = (
    u"🧮 <b>计算器已就绪</b>\n\n"
    u"直接发算式：<code>66*98</code>\n"
    u"打开设置：<code>/calc</code>\n\n"
    u"<i>提示：每个人要先给 bot 发过一条消息，它才能主动给你推送。</i>"
)


# ---------------------------------------------------------------------------
# 消息处理
# ---------------------------------------------------------------------------

def handle_command(text, chat_id):
    parts = text.split()
    cmd = parts[0].lower().split("@")[0]
    args = " ".join(parts[1:])
    if cmd in ("/start", "/help", "/menu"):
        return HELP
    if cmd in ("/calc", "/c", "/calculate"):
        if not args:
            send_html(*calc.settings_panel())
            return None
        low = args.lower()
        if low.startswith("set") or low.startswith("设置") or low.startswith("小数"):
            tok = args.split()
            val = tok[1] if len(tok) > 1 else ""
            val = val.replace("位", "").strip()
            if not val.isdigit():
                return u"⚠️ 用法：<code>/calc set 4</code>（0~10）"
            try:
                return u"✅ 小数保留位数已设为 <b>%d</b> 位" % calc.set_decimals(int(val))
            except Exception as e:  # noqa: BLE001
                return u"⚠️ %s" % calc.esc(e)
        try:
            for t, _kb in calc.calc_msgs(args):
                send_html(t)
            return None
        except Exception as e:  # noqa: BLE001
            return u"⚠️ %s" % calc.esc(e)
    return None


def handle_message(msg):
    chat = msg.get("chat") or {}
    text = (msg.get("text") or "").strip()
    chat_id = str(chat.get("id"))
    if not text:
        return
    # 1. /00 手动退出连续计算
    if calc.is_cont_exit(text):
        send_html(calc.exit_cont())
        return
    # 2. 连续计算输入（+3 *2 /0 等），必须排在命令分支之前
    if calc.is_cont_input(text):
        try:
            for t, _kb in calc.calc_msgs(text):
                send_html(t)
        except Exception as e:  # noqa: BLE001
            send_html(u"⚠️ %s" % calc.esc(e))
        return
    # 3. 命令
    if text.startswith("/"):
        try:
            reply = handle_command(text, chat_id)
        except Exception as e:  # noqa: BLE001
            reply = u"❌ 命令执行出错：%s" % calc.esc(e)
        if reply:
            send_html(reply)
        return
    # 4. 普通算式
    if calc.looks_like_expr(text):
        try:
            for t, _kb in calc.calc_msgs(text):
                send_html(t)
        except Exception as e:  # noqa: BLE001
            send_html(u"⚠️ %s" % calc.esc(e))
        return
    # 5. 兜底：静默提示，120 秒内不重复打扰
    global _LAST_HINT
    if time.time() - _LAST_HINT > 120:
        _LAST_HINT = time.time()
        send_html(u"🧮 直接发算式就行，比如 <code>66*98</code>；<code>/calc</code> 打开设置。",
                  silent=True)


_LAST_HINT = 0.0


def handle_callback(cb):
    cb_id = cb.get("id")
    data = cb.get("data") or ""
    msg = cb.get("message") or {}
    chat_id = msg.get("chat", {}).get("id")
    message_id = msg.get("message_id")
    if not data.startswith("calcset:"):
        return
    try:
        r = calc.handle_cb(data)
    except Exception as e:  # noqa: BLE001
        answer_cb(cb_id, u"⚠️ %s" % e)
        return
    if r.get("close"):
        delete_message(chat_id, message_id)
        answer_cb(cb_id, u"已收起")
        return
    edit_message(chat_id, message_id, r["text"], r.get("kb"))
    answer_cb(cb_id, r.get("alert") or u"已更新")


# ---------------------------------------------------------------------------
# 轮询
# ---------------------------------------------------------------------------

def setup_commands():
    cmds = [
        {"command": "calc", "description": u"🧮 计算器设置"},
        {"command": "help", "description": u"❓ 使用说明"},
    ]
    tg_call("setMyCommands", {"commands": json.dumps(cmds, ensure_ascii=False)})
    tg_call("setMyDescription",
            {"description": u"计算器：直接发算式就出结果，支持中文读法与会计大写。/calc 打开设置。"})


def poll_loop():
    offset = 0
    sys.stderr.write("[calc-bot] polling started\n")
    while True:
        try:
            req = urllib.request.Request(
                "%s/getUpdates" % TELEGRAM_API,
                data=urllib.parse.urlencode(
                    {"timeout": 25, "offset": offset,
                     "allowed_updates": '["callback_query","message"]'}).encode(),
                method="POST")
            with urllib.request.urlopen(req, timeout=35) as resp:
                r = json.loads(resp.read().decode("utf-8"))
            for upd in (r.get("result") or []):
                offset = max(offset, int(upd.get("update_id", 0)) + 1)
                if "callback_query" in upd:
                    cb = upd["callback_query"]
                    sys.stderr.write("[calc-bot] callback: %s\n" % (cb.get("data") or ""))
                    threading.Thread(target=handle_callback, args=(cb,), daemon=True).start()
                    continue
                msg = upd.get("message") or {}
                chat = msg.get("chat") or {}
                text = (msg.get("text") or "").strip()
                if str(chat.get("id")) != str(CHAT_ID) or not text:
                    continue
                sys.stderr.write("[calc-bot] msg: %s\n" % text[:40])
                threading.Thread(target=handle_message, args=(msg,), daemon=True).start()
        except Exception as e:  # noqa: BLE001
            sys.stderr.write("[calc-bot] poll error: %s\n" % e)
            time.sleep(5)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def dry_run():
    """不联网自检：验证 calc 与消息分发链路可用。"""
    print("BASE_DIR        :", BASE_DIR)
    print("SETTINGS_FILE   :", calc.SETTINGS_FILE)
    print("settings        :", calc.get_settings())
    for expr in ["66*98", "1/3", "2^32", "sqrt(144)"]:
        for t, _kb in calc.calc_msgs(expr):
            print("  %-12s -> %s" % (expr, t.replace("\n", " | ")))
    t, kb = calc.settings_panel()
    print("panel rows      :", len(kb))
    print("OK: 核心可用（未联网）")


def main():
    if "--dry-run" in sys.argv:
        dry_run()
        return 0
    if not BOT_TOKEN or not CHAT_ID:
        sys.stderr.write("缺少 TG_BOT_TOKEN / TG_CHAT_ID\n")
        return 2
    setup_commands()
    threading.Thread(target=poll_loop, daemon=True).start()
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    sys.exit(main())
