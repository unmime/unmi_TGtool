#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""unmi_TGtool 发布版自测：框架 + 计算器 + demo（离线 mock）。

用法： python3 selftest_public.py
"""
import os
import sys
import tempfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

_tmp = tempfile.mkdtemp(prefix="unmitool_pub_")
os.environ["DATA_DIR"] = _tmp
os.environ["TG_BOT_TOKEN"] = "dummy"
os.environ["TG_CHAT_ID"] = "12345"

from core.config import Config              # noqa: E402
from core.tg import BotContext              # noqa: E402
import main                                 # noqa: E402

SENT = []
CHAT = "12345"


class FakeCtx(BotContext):
    def api(self, method, params):
        SENT.append((method, params))
        return {"ok": True, "result": {"message_id": 1}}

    def get_updates(self, offset, timeout=25):
        return {"ok": True, "result": []}


PASS_N, FAIL = [], []


def check(name, got, expect):
    if got == expect:
        PASS_N.append(name)
    else:
        FAIL.append((name, got, expect))
        print("  FAIL %-36s 得到 %r 期望 %r" % (name, got, expect))


def texts():
    return [p.get("text", "") for _m, p in SENT]


def run(text):
    SENT.clear()
    disp.handle_message({"chat": {"id": CHAT}, "text": text})
    return texts()


def main_test():
    global disp
    cfg = Config(BASE_DIR)
    ctx = FakeCtx(cfg.token, cfg.chat_id, cfg.data_dir)
    mods = main.load_modules(cfg, ctx)
    for m in mods:
        try:
            m.on_start()
        except Exception:  # noqa: BLE001
            pass
    disp = main.Dispatcher(cfg, ctx, mods)

    print("[1] 开箱默认：只装计算器")
    check("默认只加载 calc", [m.name for m in mods], ["calc"])

    print("[2] 计算器")
    check("66*98 有结果", any("6468" in t for t in run("66*98")), True)
    check("/calc 打开面板", any(u"设置" in t for t in run("/calc")), True)

    print("[3] /help 框架兜底（无 crowdsec 时 main 兜底列出模块）")
    out = run("/help")
    check("/help 有响应", any(u"工具集" in t for t in out), True)
    check("/help 列出 calc 模块", any("calc" in t for t in out), True)

    print("[4] 连续计算")
    import TGcalc_bot as c
    c.set_settings(ans_on=True)
    c.clear_ans()
    run("3+3")
    check("+3 = 9", any("9" in t for t in run("+3")), True)

    print("[5] 未知命令有兜底")
    check("未知命令提示", any(u"未知命令" in t for t in run("/xyz")), True)

    print("[6] 普通聊天兜底")
    main._LAST_HINT["t"] = 0.0
    check("非算式提示", any(u"算式" in t for t in run("hello")), True)

    print("[7] 热插拔 demo")
    import modules.demo as demo_mod
    disp2 = main.Dispatcher(cfg, ctx, mods + [demo_mod.Plugin(ctx)])
    SENT.clear()
    disp2.handle_message({"chat": {"id": CHAT}, "text": "/ping"})
    check("demo /ping", any("pong" in t for t in texts()), True)

    print()
    print("=" * 50)
    print("通过 %d，失败 %d" % (len(PASS_N), len(FAIL)))
    if FAIL:
        for n, g, e in FAIL:
            print("  - %s: 得到 %r 期望 %r" % (n, g, e))
        return 1
    print("全部通过 ✅（未联网）")
    return 0


if __name__ == "__main__":
    sys.exit(main_test())
