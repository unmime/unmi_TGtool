#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""unmi_TGtool 主程序 —— 唯一入口。

职责：初始化、配置加载、模块注册与调度。**不包含任何具体业务逻辑。**

模块接入全部走 core/registry.py：主程序不认识任何具体模块，
只按 enabled 列表让注册表去发现、校验、实例化、驱动生命周期。

调度规则：
  消息   按 enabled 顺序逐个问每个模块 on_message，第一个返回 True 的接管
  命令   按顺序逐个问 on_command，第一个不返回 PASS 的接管
  回调   按顺序逐个问 on_callback，第一个返回 True 的接管
  报告   main.py --report <kind>，逐个问 on_report

模块间隔离：每个模块的每个方法调用都被 try/except 包裹，
某个模块抛异常只记日志，不影响其他模块和整条消息流。
"""
import os
import signal
import sys
import glob
import shutil
import threading
import urllib.request
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from core import log as _log          # noqa: E402
from core.base import PASS            # noqa: E402
from core.config import Config        # noqa: E402
from core.registry import Registry, discover   # noqa: E402
from core.tg import BotContext        # noqa: E402

_LOG = _log.get("main")
REPORT_KINDS = ("daily", "weekly", "monthly", "yearly")

_LAST_HINT = {"t": 0.0}                # 兜底提示限流（120 秒一次）


# ---------------------------------------------------------------------------
# 模块加载
# ---------------------------------------------------------------------------

def install_signals(registry):
    """收到 SIGTERM / SIGINT 时先让模块优雅收尾（on_stop），再退出。

    systemd restart / stop 发的就是 SIGTERM；不接的话 on_stop 永远不会被调用。
    """
    def _handler(signum, _frame):
        _LOG.info("收到信号 %s，停止中…", signum)
        try:
            registry.stop()
        finally:
            sys.exit(0)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _handler)
        except (ValueError, OSError):
            pass                       # 非主线程里装信号会失败，忽略即可


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

# ---------------------------------------------------------------------------
# 模块目录（可安装/卸载的模块清单 + 各自的文件列表）
# ---------------------------------------------------------------------------
# 安装 = 从公开仓库按文件列表拉取到本地；卸载 = 删除代码 + __pycache__ + 数据。
# 目录是静态的（不依赖模块是否已装），这样卸载后模块仍出现在菜单里可重装。
_REPO_RAW = "https://raw.githubusercontent.com/unmime/unmi_TGtool/main/"

_MODULE_CATALOG = {
    "calc": {
        "title": u"计算器",
        "files": ["modules/calc/__init__.py", "modules/calc/engine.py"],
    },
    "fx": {
        "title": u"汇率换算",
        "files": ["modules/fx/__init__.py", "modules/fx/engine.py"],
    },
    "demo": {
        "title": u"示例模块",
        "files": ["modules/demo.py"],
    },
    "ip": {
        "title": u"IP 归属查询",
        "files": ["modules/ip/__init__.py", "modules/ip/engine.py"],
    },
}


def _mod_installed(mid):
    """模块代码是否在本地。"""
    return os.path.isdir(os.path.join(BASE_DIR, "modules", mid)) or \
        os.path.isfile(os.path.join(BASE_DIR, "modules", mid + ".py"))


def _download_module(mid):
    """从公开仓库拉取模块文件到本地。成功返回 None，失败返回错误说明。"""
    meta = _MODULE_CATALOG.get(mid)
    if not meta:
        return u"目录里没有这个模块"
    for rel in meta["files"]:
        url = _REPO_RAW + rel
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                body = r.read()
        except Exception as e:                       # noqa: BLE001
            return u"下载失败（%s）：%s" % (rel, e)
        if not body or len(body) < 20:
            return u"下载内容异常（%s）" % rel
        dest = os.path.join(BASE_DIR, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(body)
    return None


def _remove_module(mid):
    """彻底删除模块：代码目录/文件 + __pycache__ + 该模块的数据文件。"""
    removed = []
    for path in (os.path.join(BASE_DIR, "modules", mid),
                 os.path.join(BASE_DIR, "modules", mid + ".py")):
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
            removed.append(os.path.basename(path))
        elif os.path.isfile(path):
            try:
                os.remove(path)
                removed.append(os.path.basename(path))
            except OSError:
                pass
    for pc in glob.glob(os.path.join(BASE_DIR, "modules", "__pycache__", mid + "*")):
        try:
            os.remove(pc)
        except OSError:
            pass
    # 数据文件（fx_settings.json / calc_settings.json / fx_rates.json 这类 <id>_*）
    data_dir = os.path.join(BASE_DIR, "data")
    for f in glob.glob(os.path.join(data_dir, mid + "_*.json")):
        try:
            os.remove(f)
            removed.append(os.path.basename(f))
        except OSError:
            pass
    return removed


class Dispatcher(object):
    def __init__(self, cfg, ctx, registry):
        self.cfg = cfg
        self.ctx = ctx
        self.registry = registry
        self.modules = registry.modules

    def _reload_modules(self):
        """热重载：停掉全部模块，按最新 enabled 列表重新装载。
        单个模块出问题只跳过它（registry 的隔离机制），不影响其它模块。"""
        self.registry.stop()
        self.registry = Registry(self.ctx)
        self.registry.load(self.cfg.enabled)
        self.registry.start()
        self.modules = self.registry.modules
        _LOG.info("模块已热重载: %s",
                  ", ".join(m.name for m in self.modules) or "（无）")

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
        elif cmd == "modules":
            self._modules_menu()
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
        lines.append("模块开关：<code>/modules</code>（或在 data/modules.json 里改）。")
        self.ctx.send("\n".join(lines))

    # ------------------------------------------------------------- 回调
    def handle_callback(self, cb):
        data = cb.get("data") or ""
        # 回调也要认人：按钮只出现在自己那台 bot 的会话里，别人的会话点了不处理
        msg = cb.get("message") or {}
        cb_chat = str((msg.get("chat") or {}).get("id", ""))
        if cb_chat and cb_chat != self.ctx.chat_id:
            _LOG.warn("忽略非授权会话的回调：%s", cb_chat)
            self.ctx.answer(cb.get("id"), "")
            return
        _LOG.info("callback: %s", data)
        if data.startswith("modmgr:"):
            self._modmgr_callback(data, cb.get("id"), msg)
            return
        for m in self.modules:
            ok, handled = _call(m, "on_callback", data, cb.get("id"), msg)
            if ok and handled:
                return
        self.ctx.answer(cb.get("id"), "")

    # ------------------------------------------------------------- 模块管理
    def _modules_kb(self):
        """模块管理按钮：点名字=暂停/启用，➕➖=安装/卸载。"""
        kb = []
        for mid, meta in _MODULE_CATALOG.items():
            installed = _mod_installed(mid)
            enabled = installed and mid in self.cfg.enabled
            if installed:
                mark = u"🟢" if enabled else u"⏸"
                name_cb = "modmgr:toggle:%s" % mid       # 点名字 = 暂停/启用
                act = {"text": u"➖ 卸载", "callback_data": "modmgr:askun:%s" % mid}
            else:
                mark = u"🔴"
                name_cb = "modmgr:info:%s" % mid
                act = {"text": u"➕ 安装", "callback_data": "modmgr:install:%s" % mid}
            kb.append([{"text": u"%s %s" % (mark, meta["title"]),
                        "callback_data": name_cb}, act])
        kb.append([{"text": u"❌ 收起", "callback_data": "modmgr:close"}])
        return kb


    def _modules_menu(self):
        """/modules —— 模块安装/卸载面板。"""
        text = (u"🧩 <b>模块管理</b>\n\n"
                u"🟢 在用 · ⏸ 暂停 · 🔴 未安装\n"
                u"点模块名 暂停/启用 · ➕➖ 安装/卸载（卸载删代码和配置）。")
        self.ctx.send(text, buttons=self._modules_kb())

    def _modmgr_callback(self, data, cb_id, message):
        chat_id = str((message.get("chat") or {}).get("id", ""))
        message_id = message.get("message_id")
        parts = data.split(":")
        action = parts[1] if len(parts) > 1 else ""
        mid = parts[2] if len(parts) > 2 else ""
        meta = _MODULE_CATALOG.get(mid, {})

        if action == "close":
            self.ctx.delete(chat_id, message_id)
            self.ctx.answer(cb_id, u"已收起")
            return

        if action == "open":
            text = (u"🧩 <b>模块管理</b>\n\n"
                    u"🟢 在用 · ⏸ 暂停 · 🔴 未安装\n"
                    u"点模块名 暂停/启用 · ➕➖ 安装/卸载（卸载删代码和配置）。")
            self.ctx.edit(chat_id, message_id, text, self._modules_kb())
            self.ctx.answer(cb_id, "")
            return

        if action == "info":
            for r in discover():
                if r["id"] == mid:
                    self.ctx.answer(cb_id, u"%s v%s · %s" % (
                        r["name"], r["version"], r["description"] or u"（无描述）"))
                    return
            self.ctx.answer(cb_id, u"%s（未安装）" % meta.get("title", mid))
            return

        if action == "toggle":
            if not _mod_installed(mid):
                self.ctx.answer(cb_id, u"未安装，点 ➕ 安装")
                return
            enabled = list(self.cfg.enabled)
            if mid in enabled:
                enabled.remove(mid)
                note = u"⏸ 已暂停「%s」" % meta.get("title", mid)
            else:
                enabled.append(mid)
                note = u"🟢 已启用「%s」" % meta.get("title", mid)
            self.cfg.save_enabled(enabled)
            self._reload_modules()
            text = (u"🧩 <b>模块管理</b>\n\n"
                    u"🟢 在用 · ⏸ 暂停 · 🔴 未安装\n"
                    u"点模块名 暂停/启用 · ➕➖ 安装/卸载（卸载删代码和配置）。")
            self.ctx.edit(chat_id, message_id, text, self._modules_kb())
            self.ctx.answer(cb_id, note)
            return

        if action == "askun":
            # 卸载是破坏性操作，先确认
            text = u"🗑 <b>确认卸载「%s」？</b>\n\n会删掉代码、缓存和配置，之后用 /modules 可重新安装。" % meta.get("title", mid)
            kb = [[{"text": u"✅ 确认卸载", "callback_data": "modmgr:uninstall:%s" % mid}],
                  [{"text": u"‹ 返回", "callback_data": "modmgr:open"}]]
            self.ctx.edit(chat_id, message_id, text, kb)
            self.ctx.answer(cb_id, "")
            return

        if action == "uninstall":
            removed = _remove_module(mid)
            enabled = [m for m in self.cfg.enabled if m != mid]
            self.cfg.save_enabled(enabled)
            self._reload_modules()
            text = u"✅ 已卸载「%s」（删掉 %d 项）" % (meta.get("title", mid), len(removed))
            self.ctx.edit(chat_id, message_id, text, self._modules_kb())
            self.ctx.answer(cb_id, u"🗑 已卸载")
            return

        if action == "install":
            if not _mod_installed(mid):
                self.ctx.answer(cb_id, u"⬇ 正在从仓库拉取…")
                err = _download_module(mid)
                if err:
                    self.ctx.answer(cb_id, u"⚠️ 安装失败")
                    self.ctx.send(u"⚠️ 安装「%s」失败：%s" % (meta.get("title", mid), err))
                    return
            if mid not in self.cfg.enabled:
                self.cfg.save_enabled(self.cfg.enabled + [mid])
            self._reload_modules()
            self.ctx.edit(chat_id, message_id,
                          u"✅ 已启用「%s」" % meta.get("title", mid),
                          self._modules_kb())
            self.ctx.answer(cb_id, u"✅ 已启用")
            return

        self.ctx.answer(cb_id, u"未知操作")

    # ------------------------------------------------------------- 兜底
    def _fallback(self):
        # 没有任何模块认领的消息：保持沉默，不再打扰用户（用户明确要求删掉提示）。
        return

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
    """按配置装配出一整套运行时：上下文 + 模块 + 调度器。"""
    os.makedirs(cfg.data_dir, exist_ok=True)
    ctx = BotContext(cfg.token, cfg.chat_id, cfg.data_dir)

    registry = Registry(ctx)
    registry.load(cfg.enabled)
    registry.start()

    if registry.skipped:
        _LOG.error("有 %d 个模块没加载成（见上面的原因）", len(registry.skipped))
    return ctx, registry, Dispatcher(cfg, ctx, registry)


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
        _ctx, reg, disp = build(cfg)
        disp.run_report(kind)
        reg.stop()
        _LOG.info("report %s done", kind)
        return 0

    if "--modules" in sys.argv:
        rows = discover()
        print("modules/ 下发现 %d 个模块：" % len(rows))
        for r in rows:
            if r["ok"]:
                dep = ("（依赖：%s）" % "、".join(r["requires"])) if r["requires"] else ""
                print("  [✓] %-10s v%-8s %s%s" % (r["id"], r["version"], r["description"], dep))
            else:
                print("  [✗] %-10s %s" % (r["id"], r["error"]))
        return 0

    if "--dry-run" in sys.argv:
        _ctx, reg, _disp = build(cfg)
        print("加载模块 %d 个：" % len(reg.modules))
        for m in reg.modules:
            print("  - %s v%s  %s" % (m.name, m.version, m.description))
        for mid, why in reg.skipped:
            print("  ! %s 未加载：%s" % (mid, why))
        reg.stop()
        print("OK（未开始轮询）")
        return 0

    _ctx, reg, disp = build(cfg)
    install_signals(reg)          # 退出前给模块一个收尾的机会
    # 命令菜单由已启用模块自己声明（Module.commands），主程序只负责汇总。
    # setMyCommands 是全量覆盖，绝不能在这里硬编码部分命令——
    # 否则会把别的模块的命令（如 /crowdsec、/qinglong）从菜单顶掉。
    cmds = []
    for m in reg.modules:
        cmds.extend(getattr(m, "commands", None) or [])
    cmds.append({"command": "modules", "description": "🧩 模块管理（开关/卸载）"})
    cmds.append({"command": "help", "description": "❓ 使用说明"})
    _ctx.setup_commands(
        cmds,
        "unmi_TGtool 工具集：/help 查看全部命令与使用说明。")
    threading.Thread(target=poll_loop, args=(disp,), daemon=True).start()
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    sys.exit(main())
