# -*- coding: utf-8 -*-
"""计算器模块 —— 包装 TGcalc_bot 核心。

识别算式（直接发就计算）、设置面板、连续计算（+3 / /00 退出）。
核心逻辑在 TGcalc_bot.py，这里只做接口适配。
"""
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import TGcalc_bot as c                      # noqa: E402  计算器核心
from core.base import Module, PASS          # noqa: E402

c.SETTINGS_FILE = os.path.join(
    os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data")),
    "calc_settings.json")

_NUM_CMD = re.compile(r"^[0-9.]+$")         # /0 /5 /2.5 —— 连续计算的斜杠除法


class Plugin(Module):
    name = "calc"
    version = "1.1.0"
    description = "计算器（AST 白名单求值 + 中文读法 + 会计大写）"

    def on_start(self):
        # 启动时预热一次设置，顺带把 settings 文件建出来
        c.get_settings()

    # ----------------------------------------------------------------- 消息
    def on_message(self, text, chat_id):
        # is_cont_input 识别连续计算（+3 *2 /0，长度可能只有 2 位），
        # looks_like_expr 识别普通算式（要求长度 ≥3），两者都要查。
        # 只用 looks_like_expr 会把 +3 这类短输入漏掉 —— 它的长度检查在前面。
        if not (c.is_cont_input(text) or c.looks_like_expr(text)):
            return False
        try:
            for t, _kb in c.calc_msgs(text):
                self.ctx.send(t)
        except Exception as e:  # noqa: BLE001
            self.ctx.send(u"⚠️ %s" % c.esc(e))
        return True

    # ----------------------------------------------------------------- 命令
    def on_command(self, cmd, args, chat_id):
        # /00 —— 手动退出连续计算
        if re.match(r"^0{2,}$", cmd):
            if c.is_cont_exit("/" + cmd):
                self.ctx.send(c.exit_cont())
                return None
            return PASS
        # /0 /5 —— 连续计算的斜杠除法（开启时才识别）
        if _NUM_CMD.match(cmd) and c.is_cont_input("/" + cmd):
            try:
                for t, _kb in c.calc_msgs("/" + cmd):
                    self.ctx.send(t)
            except Exception as e:  # noqa: BLE001
                self.ctx.send(u"⚠️ %s" % c.esc(e))
            return None
        # /calc /c /calculate
        if cmd in ("calc", "c", "calculate"):
            if not args:
                self.ctx.send(*c.settings_panel())
                return None
            low = args.lower()
            if low.startswith("set") or low.startswith("设置") or low.startswith("小数"):
                tok = args.split()
                val = tok[1] if len(tok) > 1 else ""
                val = val.replace("位", "").strip()
                if not val.isdigit():
                    return u"⚠️ 用法：<code>/calc set 4</code>（0~10）"
                try:
                    return u"✅ 小数保留位数已设为 <b>%d</b> 位" % c.set_decimals(int(val))
                except Exception as e:  # noqa: BLE001
                    return u"⚠️ %s" % c.esc(e)
            try:
                for t, _kb in c.calc_msgs(args):
                    self.ctx.send(t)
                return None
            except Exception as e:  # noqa: BLE001
                return u"⚠️ %s" % c.esc(e)
        return PASS

    # ----------------------------------------------------------------- 回调
    def on_callback(self, data, cb_id, message):
        if not data.startswith("calcset:"):
            return False
        chat_id = message.get("chat", {}).get("id")
        message_id = message.get("message_id")
        try:
            r = c.handle_cb(data)
        except Exception as e:  # noqa: BLE001
            self.ctx.answer(cb_id, u"⚠️ %s" % e)
            return True
        if r.get("close"):
            self.ctx.delete(chat_id, message_id)
            self.ctx.answer(cb_id, u"已收起")
            return True
        self.ctx.edit(chat_id, message_id, r["text"], r.get("kb"))
        self.ctx.answer(cb_id, r.get("alert") or u"已更新")
        return True
