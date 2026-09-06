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
from core.registry import Registry, discover  # noqa: E402
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
    reg = Registry(ctx)
    mods = reg.load(cfg.enabled)
    reg.start()
    disp = main.Dispatcher(cfg, ctx, reg)

    print("[1] 开箱默认：全新环境只装计算器（fx 用 /modules 启用）")
    check("默认只加载 calc", [m.name for m in mods], ["calc"])

    print("[2] 计算器")
    check("66*98 有结果", any("6468" in t for t in run("66*98")), True)
    check("/calc 打开面板", any(u"设置" in t for t in run("/calc")), True)

    print("[3] /help 框架兜底（无专用 help 模块时 main 兜底列出模块）")
    out = run("/help")
    check("/help 有响应", any(u"工具集" in t for t in out), True)
    check("/help 列出 calc 模块", any("calc" in t for t in out), True)

    print("[4] 连续计算")
    from modules.calc import engine as c
    c.set_settings(ans_on=True)
    c.clear_ans()
    run("3+3")
    check("+3 = 9", any("9" in t for t in run("+3")), True)

    print("[5] 未知命令有兜底")
    check("未知命令提示", any(u"未知命令" in t for t in run("/xyz")), True)

    print("[6] 普通聊天兜底")
    main._LAST_HINT["t"] = 0.0
    check("非算式保持沉默（兜底提示已按用户要求删除）", run("hello"), [])

    print("[8] 模块注册表：坏模块 / 依赖 / 重名 都要被拦住")
    reg2 = Registry(ctx)
    reg2.load(["calc", "calc", "nonexistent_module"])
    check("重复加载只生效一次", len(reg2.modules), 1)
    check("不存在的模块被记进 skipped", any("nonexistent" in i for i, _w in reg2.skipped), True)
    check("坏模块不影响已加载的", reg2.modules[0].name, "calc")

    # 依赖未满足：造一个依赖 demo 的模块，但 enabled 里 demo 排在后面
    class _Needy(mods[0].__class__):
        name = "needy"
        version = "0.0.1"
        description = "测试用"
        requires = ["demo"]

    import types
    fake_mod = types.ModuleType("modules._fake_needy")
    fake_mod.Plugin = _Needy
    sys.modules["modules._fake_needy"] = fake_mod
    reg3 = Registry(ctx)
    reg3.load(["_fake_needy"])
    check("依赖未满足时跳过", len(reg3.modules), 0)
    reg4 = Registry(ctx)
    reg4.load(["demo", "_fake_needy"])
    check("依赖在前则正常加载", [m.name for m in reg4.modules], ["demo", "needy"])
    sys.modules.pop("modules._fake_needy", None)

    print("[9] 模块独立配置（原子写）")
    m0 = mods[0]
    m0.save_config({"x": 1})
    check("配置写读一致", m0.load_config().get("x"), 1)
    check("配置文件名 = 模块名", os.path.basename(m0.config_path), "calc.json")
    # 写坏的文件不能让模块起不来
    open(m0.config_path, "w").write("{ 坏掉的 json")
    check("配置损坏时回退默认值", m0.load_config({"fallback": True}), {"fallback": True})
    m0.save_config({})

    print("[10] 发现机制")
    found = {r["id"]: r for r in discover()}
    check("能发现 calc", found.get("calc", {}).get("ok"), True)
    check("能发现 demo", found.get("demo", {}).get("ok"), True)
    check("calc 声明了 /calc 命令",
          any(c.get("command") == "calc" for c in found.get("calc", {}).get("commands", [])), True)

    print("[7] 热插拔 demo")
    import modules.demo as demo_mod
    reg2 = Registry(ctx)
    reg2.modules = mods + [demo_mod.Plugin(ctx)]
    reg2.by_name = {m.name: m for m in reg2.modules}
    disp2 = main.Dispatcher(cfg, ctx, reg2)
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
