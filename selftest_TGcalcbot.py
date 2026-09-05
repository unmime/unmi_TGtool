#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TGcalcbot.py 离线自测：mock 掉网络层，验证消息/命令/回调全链路。

不连真实 Telegram API —— 否则会和已运行的 bot 实例抢 getUpdates。
用法： python3 selftest_bot.py
"""
import json
import os
import sys
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import calc  # noqa: E402

# 用临时配置，绝不碰真实设置
_tmp = tempfile.mkdtemp(prefix="calcbotdry_")
calc.SETTINGS_FILE = os.path.join(_tmp, "calc_settings.json")

import TGcalcbot  # noqa: E402

CHAT = 123456789        # 占位 chat id（离线测试用，不连真实 API）
SENT = []          # 记录所有"发送"的动作


def fake_tg(method, params):
    SENT.append((method, params))
    return {"ok": True, "result": {"message_id": 999}}


TGcalcbot.tg_call = fake_tg          # 网络层全部走假实现
CALLS = []


def spy(fn):
    def _w(*a, **kw):
        return fn(*a, **kw)
    return _w


def run(text, cb_data=None):
    SENT.clear()
    if cb_data is not None:
        TGcalcbot.handle_callback({"id": "x", "data": cb_data,
                             "message": {"chat": {"id": CHAT}, "message_id": 123}})
    else:
        TGcalcbot.handle_message({"chat": {"id": CHAT}, "text": text})
    return [(m, p.get("text") or p.get("callback_data") or "") for m, p in SENT]


PASS, FAIL = [], []


def check(name, cond, extra=""):
    if cond:
        PASS.append(name)
    else:
        FAIL.append((name, extra))
        print("  FAIL %-40s %s" % (name, extra))


def main():
    calc.set_settings(decimals=2, fmt="paren", conv_on=True, conv_mode="both",
                      ans_on=False)
    calc.clear_ans()

    print("[1] 算式")
    out = run("66*98")
    check("发算式回 2 条", len(out) == 2, str(out))
    check("主结果正确", "6468" in out[0][1], str(out[0]))
    check("转换行正确", u"六千四百六十八" in (out[1][1] if len(out) > 1 else ""), str(out))

    print("[2] 命令")
    out = run("/start")
    check("/start 有回复", len(out) == 1 and u"计算器" in out[0][1], str(out))
    out = run("/calc")
    check("/calc 打开面板", len(out) == 1 and u"设置" in out[0][1], str(out))
    out = run("/calc set 4")
    check("/calc set 4 生效", u"4" in out[0][1], str(out))
    check("设置已落盘", calc.get_decimals() == 4, str(calc.get_settings()))
    run("/calc set 2")

    print("[3] 回调整链路")
    out = run(None, cb_data="calcset:dec:3")
    check("dec 回调编辑消息", any(m == "editMessageText" for m, _ in out), str(out))
    out = run(None, cb_data="calcset:close")
    check("close 回调删消息", any(m == "deleteMessage" for m, _ in out), str(out))
    out = run(None, cb_data="calcset:fmt:eq")
    check("fmt 回调生效", calc.get_settings()["fmt"] == "eq", str(calc.get_settings()))
    calc.set_settings(fmt="paren")

    print("[4] 连续计算（需先开开关）")
    calc.set_settings(ans_on=True)
    calc.clear_ans()
    run("3+3")
    out = run("+3")
    check("+3 生效", any("9" in t for _m, t in out), str(out))
    out = run("/00")
    check("/00 退出", any(u"已退出" in t for _m, t in out), str(out))
    calc.set_settings(ans_on=False)

    print("[5] 兜底提示")
    out = run("hello")
    check("非算式有提示", len(out) == 1 and u"算式" in out[0][1], str(out))
    out2 = run("world")
    check("120 秒内不重复提示", len(out2) == 0, str(out2))

    print("[6] dry-run 自检")
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        TGcalcbot.dry_run()
    check("dry-run 有输出", u"OK" in buf.getvalue(), buf.getvalue()[:80])

    print()
    print("=" * 50)
    print("通过 %d，失败 %d" % (len(PASS), len(FAIL)))
    if FAIL:
        for n, e in FAIL:
            print("  - %s: %s" % (n, e))
        return 1
    print("全部通过 ✅（未联网）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
