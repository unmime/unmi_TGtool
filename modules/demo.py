# -*- coding: utf-8 -*-
"""示例模块 —— 演示如何新增一个功能。

把它加进 data/modules.json 的 enabled 列表（或环境变量 ENABLED_MODULES），
重启服务就能用：

    {"enabled": ["calc", "demo"]}

它会：
  - 响应 /ping → pong
  - 响应 /echo xxx → 原样回显
  - 收到包含 "你好" 的消息 → 打招呼
  - 不碰任何其他模块的逻辑，抛异常也不会影响别人
"""
from core.base import Module, PASS


class Plugin(Module):
    name = "demo"
    version = "1.0.0"
    description = "示例模块（/ping /echo）"

    def on_start(self):
        self.ctx.log.info("demo 模块已启动")

    def on_command(self, cmd, args, chat_id):
        if cmd == "ping":
            return "pong 🏓"
        if cmd == "echo":
            return "你说：<code>%s</code>" % (args or "（空）")
        return PASS                     # 不归我管，交给下一个模块

    def on_message(self, text, chat_id):
        if "你好" in text:
            self.ctx.send("你好！我是 demo 模块 👋")
            return True
        return False
