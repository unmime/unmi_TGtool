# -*- coding: utf-8 -*-
"""模块接口规范。

每个功能模块都是一个 Python 文件，放在 modules/ 目录下，导出一个名为 Plugin 的类。
新增一个模块，就是新增一个这样的类，再把它加进配置里的 enabled 列表。

主程序不认识任何具体模块，只跟这个接口打交道。
"""

PASS = NotImplemented       # on_command 返回它，表示「这个命令不归我管，让下一个模块试试」


class Module(object):
    """功能模块基类。

    生命周期与调度规则（全部由主程序调用，模块不用关心顺序）：

        启动  __init__(ctx) -> on_start()
        消息  on_message() / on_command() / on_callback()   —— 每个事件按 enabled 顺序逐个问
        报告  on_report()                                    —— 由定时器触发（日/周/月/年）
        停止  on_stop()

    模块间的隔离：主程序调用任何一个方法时都会 try/except，
    某个模块抛异常只会记进日志，不会让整条消息流或别的模块崩掉。
    """

    name = ""                 # 模块唯一标识（用于日志、配置）
    version = "0.0.0"
    description = ""

    def __init__(self, ctx):
        """ctx 是 BotContext（见 core/tg.py），提供 Telegram API、配置、日志。"""
        self.ctx = ctx

    # ------------------------------------------------------------------ 事件
    def on_message(self, text, chat_id):
        """收到非命令文本消息。

        返回 True 表示「这条消息我处理了，别再往下传」；
        返回 False 让下一个模块继续尝试。
        """
        return False

    def on_command(self, cmd, args, chat_id):
        """收到 /命令（cmd 已去掉前导 /，args 是剩余部分）。

        返回 PASS（NotImplemented）表示不归我管，交给下一个模块；
        返回字符串 -> 主程序原样发给用户（模块处理完了）；
        返回 None  -> 模块处理完了但不需要回复。
        """
        return PASS

    def on_callback(self, data, cb_id, message):
        """收到内联按钮回调（callback_query）。data 是 callback_data。

        返回 True 表示已处理，False 让下一个模块尝试。
        """
        return False

    def on_report(self, kind):
        """定时报告。kind ∈ {"daily", "weekly", "monthly", "yearly"}。

        有内容就通过 ctx.send 发出去，没有就直接返回。
        异常由主程序兜底，模块不用自己 try。
        """
        pass

    # ------------------------------------------------------------------ 钩子
    def on_start(self):
        """所有模块加载完成后调用。可以在这里起后台线程、做初始化。"""
        pass

    def on_stop(self):
        """服务退出前调用（目前用不上，留作扩展点）。"""
        pass


def esc(s):
    """HTML 转义（所有模块共用的最小工具函数）。"""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
