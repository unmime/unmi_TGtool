#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""unmi_TGtool 主程序 —— 唯一入口。

职责：初始化、配置加载、模块注册与调度。**不包含任何具体业务逻辑。**

调度规则：
  消息   按 enabled 顺序逐个问每个模块 on_message，第一个返回 True 的接管
  命令   按顺序逐个问 on_command，第一个不返回 PASS 的接管
  回调   按顺序逐个问 on_callback，第一个返回 True 的接管
  报告   main.py --report <kind>，逐个问 on_report

模块间隔离：每个模块的每个方法调用都被 try/except 包裹，
某个模块抛异常只记日志，不影响其他模块和整条消息流。
"""
import importlib
import os
import sys
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from core import log as _log          # noqa: E402
from core.base import PASS            # noqa: E402
from core.config import Config        # noqa: E402
from core.tg import BotContext        # noqa: E402

_LOG = _log.get("main")
REPORT_KINDS = ("daily", "weekly", "monthly", "yearly")

_LAST_HINT = {"t": 0.0}                # 兜底提示限流（120 秒一次）


# ---------------------------------------------------------------------------
# 模块加载
# ---------------------------------------------------------------------------

def load_modules(cfg, ctx):
    """按 enabled 列表加载模块，加载失败只记日志跳过，不拖垮整个启动。"""
    out = []
    for name in cfg.enabled:
        try:
            mod = importlib.import_module("modules.%s" % name)
            cls = getattr(mod, "Plugin")
            out.append(cls(ctx))
            _LOG.info("模块加载: %s v%s（%s）",
                      name, getattr(cls, "version", "?"),
                      getattr(cls, "description", ""))
        except Exception as e:  # noqa: BLE001
            _LOG.error("模块 %s 加载失败（%s），跳过", name, e)
    return out


def _call(mod, meth, *a):
    """调用模块方法并隔离异常。返回 (成功?, 结果)。"""
    try:
        return True, getattr(mod, meth)(*a)
    except Exception as e:  # noqa: BLE001
        _LOG.error("模块 %s.%s 异常: %s", mod.name, meth, e)
        return False, None


# ---------------------------------------------------------------------------
# 调度
# ---------------------------------------------------------------------------

class Dispatcher(object):
    def __init__(self, cfg, ctx, modules):
        self.cfg = cfg
        self.ctx = ctx
        self.modules = modules

    # ------------------------------------------------------------- 消息
    def handle_message(self, msg):
        chat = msg.get("chat") or {}
        text = (msg.get("text") or "").strip()
        chat_id = str(chat.get("id"))
        if not text or chat_id != self.ctx.chat_id:
            return
        _LOG.info("msg: %s", text[:40])

        if text.startswith("/"):
            self._command(text, chat_id)
            return
        # 非命令：按序问每个模块
        for m in self.modules:
            ok, handled = _call(m, "on_message", text, chat_id)
            if ok and handled:
                return
        self._fallback()

    def _command(self, text, chat_id):
        parts = text.split()
        cmd = parts[0].lower().split("@")[0][1:]   # 去掉 / 和 @botname
        args = " ".join(parts[1:])
        for m in self.modules:
            ok, reply = _call(m, "on_command", cmd, args, chat_id)
            if not ok:
                continue
            if reply is PASS:
                continue                            # 不归这个模块管
            if isinstance(reply, str) and reply:
                self.ctx.send(reply)
            return
        # 所有模块都不接：/help /start /menu 给框架级兜底（列出已加载模块），
        # 其余按未知命令处理。若装了处理这三个命令的模块会先接管，到不了这里。
        if cmd in ("help", "start", "menu"):
            self._builtin_help()
        else:
            self.ctx.send("🧭 未知命令：%s，发 /help 看用法。" % text, silent=True)

    def _builtin_help(self):
        """没有任何模块接管 /help 时的框架级帮助：列出已加载模块。"""
        lines = ["🧰 <b>unmi_TGtool 工具集</b>", ""]
        lines.append("已加载模块（按优先级）：")
        for m in self.modules:
            lines.append("  · <b>%s</b> v%s — %s" % (m.name, m.version, m.description))
        lines.append("")
        lines.append("直接发算式就能算，<code>/calc</code> 打开计算器设置。")
        lines.append("在 <code>data/modules.json</code> 的 enabled 里增减模块。")
        self.ctx.send("\n".join(lines))

    # ------------------------------------------------------------- 回调
    def handle_callback(self, cb):
        data = cb.get("data") or ""
        _LOG.info("callback: %s", data)
        for m in self.modules:
            ok, handled = _call(m, "on_callback",
                                data, cb.get("id"), cb.get("message") or {})
            if ok and handled:
                return
        self.ctx.answer(cb.get("id"), "")

    # ------------------------------------------------------------- 兜底
    def _fallback(self):
        if time.time() - _LAST_HINT["t"] > 120:
            _LAST_HINT["t"] = time.time()
            self.ctx.send(
                "🧭 直接发算式就能算，/help 看命令，/calc 打开设置。", silent=True)

    # ------------------------------------------------------------- 报告
    def run_report(self, kind):
        for m in self.modules:
            _call(m, "on_report", kind)


# ---------------------------------------------------------------------------
# 轮询
# ---------------------------------------------------------------------------

def poll_loop(disp):
    offset = 0
    ctx = disp.ctx
    _LOG.info("polling started，模块: %s",
              ", ".join(m.name for m in disp.modules) or "（无）")
    while True:
        try:
            r = ctx.get_updates(offset)
            for upd in (r.get("result") or []):
                offset = max(offset, int(upd.get("update_id", 0)) + 1)
                if "callback_query" in upd:
                    threading.Thread(
                        target=disp.handle_callback,
                        args=(upd["callback_query"],), daemon=True).start()
                    continue
                msg = upd.get("message") or {}
                if str((msg.get("chat") or {}).get("id")) != ctx.chat_id:
                    continue
                threading.Thread(
                    target=disp.handle_message, args=(msg,), daemon=True).start()
        except Exception as e:  # noqa: BLE001
            _LOG.error("poll error: %s", e)
            time.sleep(5)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def build(cfg):
    os.makedirs(cfg.data_dir, exist_ok=True)
    ctx = BotContext(cfg.token, cfg.chat_id, cfg.data_dir)
    modules = load_modules(cfg, ctx)
    for m in modules:
        _call(m, "on_start")
    return ctx, modules, Dispatcher(cfg, ctx, modules)


def main():
    cfg = Config(BASE_DIR)
    errs = cfg.check()
    if errs:
        for e in errs:
            _LOG.error(e)
        _LOG.error("缺少必要配置，退出。参考 install.sh 生成 /etc/unmi_TGtool.env")
        return 2

    # --report <kind>：由 systemd timer 触发，发完报告就退出
    if len(sys.argv) >= 3 and sys.argv[1] == "--report":
        kind = sys.argv[2]
        if kind not in REPORT_KINDS:
            _LOG.error("usage: main.py --report %s", "|".join(REPORT_KINDS))
            return 2
        _ctx, _mods, disp = build(cfg)
        disp.run_report(kind)
        _LOG.info("report %s done", kind)
        return 0

    if "--dry-run" in sys.argv:
        _ctx, mods, _disp = build(cfg)
        print("加载模块 %d 个：" % len(mods))
        for m in mods:
            print("  - %s v%s  %s" % (m.name, m.version, m.description))
        print("OK（未开始轮询）")
        return 0

    _ctx, _mods, disp = build(cfg)
    # 注意：与 CrowdSec relay 共用同一 bot token，setMyCommands 是全量覆盖，
    # 这里必须注册完整命令列表，否则会把 /crowdsec、/qinglong 顶掉。
    _ctx.setup_commands(
        [{"command": "crowdsec", "description": "🛡 CrowdSec 安全守护"},
         {"command": "qinglong", "description": "🐉 青龙面板"},
         {"command": "calc", "description": "🧮 计算器设置"},
         {"command": "help", "description": "❓ 使用说明"}],
        "服务器安全守护（CrowdSec 集群）、青龙面板与自动化通知。/crowdsec 主菜单，直接发算式就能算。")
    threading.Thread(target=poll_loop, args=(disp,), daemon=True).start()
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    sys.exit(main())
