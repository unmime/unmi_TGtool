#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""calc.py 回归自测。

用法：
    python3 selftest_calc.py            # 跑全部用例
    python3 selftest_calc.py -v         # 显示每条结果

设计原则：
- 不碰真实的 calc_settings.json（用临时目录）
- 断言失败会打印「期望 vs 实际」，退出码非 0
- 新增功能时，顺手把用例加进对应的 CASE 列表
"""
import os
import sys
import tempfile
from fractions import Fraction as F

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules.calc import engine as calc      # noqa: E402

VERBOSE = "-v" in sys.argv
PASS, FAIL = [], []


def check(name, got, expect):
    if got == expect:
        PASS.append(name)
        if VERBOSE:
            print("  OK   %-34s %s" % (name, got))
    else:
        FAIL.append((name, got, expect))
        print("  FAIL %-34s 得到 %r  期望 %r" % (name, got, expect))


def expect_err(name, fn, *a):
    """断言只抛 CalcError（其它异常算失败）。"""
    try:
        r = fn(*a)
    except calc.CalcError:
        PASS.append(name)
        if VERBOSE:
            print("  OK   %-34s CalcError" % name)
        return
    except Exception as e:  # noqa: BLE001
        FAIL.append((name, "%s: %s" % (type(e).__name__, e), "CalcError"))
        print("  FAIL %-34s 抛了 %s: %s" % (name, type(e).__name__, e))
        return
    FAIL.append((name, r, "CalcError"))
    print("  FAIL %-34s 没有报错，返回 %r" % (name, r))


def main():
    tmp = tempfile.mkdtemp(prefix="calc_selftest_")
    calc.SETTINGS_FILE = os.path.join(tmp, "calc_settings.json")
    calc.set_settings(decimals=2, fmt="paren", conv_on=True, conv_mode="both")

    # ---------------------------------------------------------------- 基础运算
    print("[1] 基础运算与精度")
    check("0.1+0.2 精确", calc.format_value(F(1, 10) + F(2, 10))[0], "0.3")
    check("0.07*100", calc.format_result("0.07*100").split("\n")[0],
          "<code>0.07*100=7</code>｜<code>7</code>｜")
    check("1/3*3 精确为 1", calc.format_value(F(1, 3) * 3)[0], "1")
    check("大数不失小数", calc.format_result("123456789+0.005").split("\n")[0],
          "<code>123456789+0.005=123456789.01</code>｜<code>123456789.01</code>｜")
    check("2^64 精确保全", calc.format_value(F(2) ** 64)[0], "18446744073709551616")
    check("2^100 精确保全", calc.format_value(F(2) ** 100)[0],
          "1267650600228229401496703205376")
    check("科学计数法", calc.format_value(F(1, 10 ** 20))[0], "1e-20")

    # ------------------------------------------------------------ 央行规范对照
    print("[2] 会计大写（央行《正确填写票据和结算凭证的基本规定》）")
    for v, expect in [
        (1409.50, u"壹仟肆佰零玖元伍角"),
        (1680.32, u"壹仟陆佰捌拾元叁角贰分"),
        (0.14, u"壹角肆分"),
        (0.05, u"伍分"),
        (0, u"零元整"),
        (1001, u"壹仟零壹元整"),
        (10001, u"壹万零壹元整"),
        (1000000, u"壹佰万元整"),
        (100000000, u"壹亿元整"),
        (16.40, u"壹拾陆元肆角"),
        (325.04, u"叁佰贰拾伍元零肆分"),
        (6762, u"陆仟柒佰陆拾贰元整"),
        (-6762, u"负陆仟柒佰陆拾贰元整"),
    ]:
        check(u"大写 %s" % v, calc.cn_accounting(F(str(v))), expect)

    # ------------------------------------------------------------------ 中文读法
    print("[3] 中文自然读法")
    for v, expect in [
        (6762, u"六千七百六十二"), (0, u"零"), (10, u"十"), (12, u"十二"),
        (10003, u"一万零三"), (10000, u"一万"), (100300, u"十万零三百"),
        (123456789, u"一亿二千三百四十五万六千七百八十九"),
        (10 ** 12, u"一兆"), (10 ** 18, u"一百京"), (-6762, u"负六千七百六十二"),
    ]:
        check(u"读法 %s" % v, calc.cn_reading(F(v)), expect)
    check(u"读法 2^64 不为空", bool(calc.cn_reading(F(2) ** 64)), True)

    # ---------------------------------------------------------------------- 安全
    print("[4] 安全：逃逸必须全部拒绝")
    for payload in [
        "().__class__", "[].__class__", "(1).__class__",
        "().__class__.__bases__[0].__subclasses__()",
        # 注：{1} / [1] 现在按「花括号/方括号当小括号」处理，等价 (1)，不再算逃逸；
        #     [1,2] 转成 (1,2) 是元组，仍被求值器拒绝；{1:2} 直接语法错误
        "lambda:1", "1 if 1 else 2", "[1,2]", "{1:2}",
        "1;2", "print(1)", "eval('1')", "exec('1')", "__import__('os')",
        "globals()", "locals()", "vars()", "dir()", "getattr(1,'real')",
        "().__doc__", "1j", "open('/etc/passwd').read()",
        "os.system('id')", "__builtins__", "1 .real",
    ]:
        expect_err(u"拒绝 %s" % payload[:28], calc.format_result, payload)

    # ------------------------------------------------------------------ 异常输入
    print("[5] 畸形输入只抛 CalcError，不崩溃")
    for bad in ["()", "(((", "1+", "*5", "1/0", "5%0", "5//0", "2**", "1e",
                "0x", "0b", "", "   ", "1" * 200, "1+" * 70,
                "sqrt(-1)", "log(0)", "log(1,1)", "factorial(-1)",
                "factorial(3.5)", "asin(2)", "pow(0,-1)", "9^9^9",
                "9999999999**999999",                 "((((((((((1+2))))))))))*",
                "sqrt(", "(1+2))"]:
        expect_err(u"畸形 %r" % bad[:24], calc.format_result, bad)

    print("[5b] 看似畸形但数学上合法，应正常求值")
    check(u"--5 = 5", calc.format_result("--5").split("\n")[0],
          "<code>--5=5</code>｜<code>5</code>｜")
    check(u"1+++2 = 3", calc.format_result("1+++2").split("\n")[0],
          "<code>1+++2=3</code>｜<code>3</code>｜")
    check(u"深嵌套括号 = 6", calc.format_result("((((((((((1+2))))))))))*2").split("\n")[0],
          "<code>((((((((((1+2))))))))))*2=6</code>｜<code>6</code>｜")
    # 归一化会忽略空白（为了支持「1 000 + 1」），代价是 "1 2" 会被当成 12
    # 实际 bot 里 looks_like_expr 会因长度 <3 先拦掉，不会走到求值
    check(u"空白被忽略", calc.format_result("1 2").split("\n")[0],
          "<code>12=12</code>｜<code>12</code>｜")

    # ---------------------------------------------------------------- 识别边界
    print("[6] 算式识别：不该误伤的")
    for t in ["1.2.3.0/24", "8.8.8.8", "hello", "hello+1", "restart now",
              "2001:db8::1", "1.2.3.4", "abc(1)", "ok"]:
        check(u"不算算式 %r" % t, calc.looks_like_expr(t), False)
    for t in ["66*98", "1+1", "(1+2)*3", "2^32", "sqrt(144)", "pi*2", "1e3*2",
              "0xff+1", "1,000*3", u"66×98", u"100-（3+4）", "10//3"]:
        check(u"算算式 %r" % t, calc.looks_like_expr(t), True)

    # ------------------------------------------------------------------ 设置项
    print("[7] 设置与面板")
    calc.set_settings(decimals=4)
    check("设 4 位生效", calc.get_decimals(), 4)
    check("4 位输出", calc.format_result("1/3").split("\n")[0],
          "<code>1/3=0.3333</code>｜<code>0.3333</code>｜")
    calc.set_settings(decimals=0)
    check("0 位输出", calc.format_result("100/7").split("\n")[0],
          "<code>100/7=14</code>｜<code>14</code>｜")
    calc.set_settings(decimals=2)
    expect_err("设 11 位被拒", calc.set_decimals, 11)
    calc.set_settings(conv_on=False)
    check("转换关闭无第二行", len(calc.calc_msgs("66*98")), 1)
    calc.set_settings(conv_on=True, conv_mode="read")
    msgs = calc.calc_msgs("66*98")
    check("仅读法 -> 两条", len(msgs), 2)
    check("仅读法内容", msgs[1][0], u"自然读法：<code>六千四百六十八</code>")
    calc.set_settings(conv_mode="acct")
    check("仅大写内容", calc.calc_msgs("66*98")[1][0],
          u"会计大写：<code>陆仟肆佰陆拾捌元整</code>")
    calc.set_settings(conv_mode="both")
    # 读法和会计大写之间空一行（3 行），分隔更清楚
    check("两种都显示", len(calc.calc_msgs("66*98")[1][0].split("\n")), 3)
    check("两种都显示中间有空行",
          "\n\n" in calc.calc_msgs("66*98")[1][0], True)
    for f in ["result", "eq", "paren"]:
        calc.set_settings(fmt=f)
        check("格式 %s 可渲染" % f, bool(calc.calc_msgs("1+1")), True)
    calc.set_settings(fmt="paren")

    # 面板：选中标记与布局
    calc.set_settings(decimals=2, conv_mode="both", conv_on=True)
    _t, kb = calc.settings_panel()
    flat = [b["text"] for row in kb for b in row]
    check("小数位勾选", u"2 位 🟢" in flat, True)
    check("格式勾选", u"算式+结果（结果） 🟢" in flat, True)
    check("两种都显示时双绿点",
          (u"自然读法 🟢" in flat) and (u"会计大写 🟢" in flat), True)
    widest = max(u"".join(btn["text"] for btn in row) for row in kb)
    check("每行按钮不超宽(<12字)", len(widest) < 12, True)
    for cb_data in ["calcset:dec:3", "calcset:fmt:eq", "calcset:conv:toggle",
                    "calcset:cmode:acct", "calcset:open"]:
        check(u"回调 %s" % cb_data, bool(calc.handle_cb(cb_data)), True)

    # ------------------------------------------------- 括号写法 / 函数名带数字
    print("[13] 括号写法与函数名解析")
    def first(expr):
        # 取「=右边的值」，去掉 </code> 尾巴
        return calc.format_result(expr).split("\n")[0].split("=")[1].replace("</code>", "")

    # 花括号/方括号一律当小括号 —— 之前这几种字符不在字符白名单里，
    # 整条式子会被当成普通聊天不计算
    check(u"花括号", calc.format_result("9856+9952/{(695*6523)-9854}*9").split("\n")[0].split("=")[0],
          "<code>9856+9952/((695*6523)-9854)*9")
    check(u"花括号可算", first("9856+9952/{(695*6523)-9854}*9"),
          first("9856+9952/((695*6523)-9854)*9"))
    check(u"方括号", calc.format_result("2*[3+4]").split("\n")[0].split("=")[0], "<code>2*(3+4)")
    check(u"三层混用", first("{(2+3)*[4-1]}"), "15")
    check(u"全角花括号", first("｛2+3｝"), "5")

    # 函数名以数字结尾的（log2 / log10）曾被隐式乘法拆坏成 log2*(8)
    for fn, expr, want in [
        ("log2", "log2(8)", "3"),
        ("log10", "log10(100)", "2"),
        ("log10 复合", "log10(1000)/log10(10)", "3"),
        ("log2 复合", "2*log2(8)+log10(100)", "8"),
    ]:
        got = first(expr)
        check(u"函数名带数字 %s" % fn, got, want)

    # 普通隐式乘法不能被上面的修复误伤
    for expr, want in [("2(3)", "6"), ("10(3)", "30"), ("2sqrt(4)", "4"),
                       ("3(4+5)", "27"), ("2pi", None), ("100(2)", "200")]:
        got = first(expr)
        check(u"隐式乘法 %s" % expr, got, want if want else got)

    # ------------------------------------------------- 新增函数
    print("[14] 新增函数")
    cases = [
        ("hypot(3,4)", "5"), ("sign(-5)", "-1"), ("sign(0)", "0"), ("sign(3.7)", "1"),
        ("comb(5,2)", "10"), ("ncr(49,6)", "13983816"), ("perm(5,2)", "20"),
        ("npr(10,3)", "720"), ("gamma(5)", "24"), ("nthroot(27,3)", "3"),
        ("nthroot(-27,3)", "-3"), ("nthroot(16,4)", "2"),
        ("avg(1,2,3,4)", "2.5"), ("mean(10,20)", "15"), ("sum(1,2,3,4,5)", "15"),
    ]
    for expr, want in cases:
        check(u"函数 %s" % expr, first(expr), want)
    # 边界与报错
    expect_err("comb 负数", calc.format_result, "comb(-1,1)")
    check("comb(2,5)=0（k>n 不报错）", first("comb(2,5)"), "0")
    expect_err("nthroot 偶次根负数", calc.format_result, "nthroot(-16,4)")
    expect_err("nthroot 0 次根", calc.format_result, "nthroot(8,0)")
    check("收起回调", calc.handle_cb("calcset:close").get("close"), True)
    expect_err("未知回调被拒", calc.handle_cb, "calcset:bogus:1")

    # ---------------------------------------------------------------- 连续计算
    print("[8] 连续计算 ans（默认关闭）")
    calc.set_settings(ans_on=False, fmt="paren")   # 上一组回调测过 fmt:eq，这里显式复位
    calc.clear_ans()
    check("默认关闭", calc.get_settings()["ans_on"], False)
    check("关闭时不识别 ans*2", calc.looks_like_expr("ans*2"), False)
    check("关闭时不识别 ans", calc.looks_like_expr("ans"), False)
    expect_err("关闭时用 ans 报错", calc.format_result, "ans*2")
    calc.set_settings(ans_on=True)
    check("开启后识别 ans*2", calc.looks_like_expr("ans*2"), True)
    check("开启后识别 ans", calc.looks_like_expr("ans"), True)
    expect_err("无记录时用 ans 报错", calc.format_result, "ans+1")
    calc.set_settings(conv_on=False)          # 关掉转换，只看主结果
    check("记录上次结果", calc.format_result("66*98").split("\n")[0],
          "<code>66*98=6468</code>｜<code>6468</code>｜")
    check("ans 已记录", calc.get_ans(), F(6468))
    check("ans*2", calc.format_result("ans*2").split("\n")[0],
          "<code>ans*2=12936</code>｜<code>12936</code>｜")
    check("ans+1", calc.format_result("ans+1").split("\n")[0],
          "<code>ans+1=12937</code>｜<code>12937</code>｜")
    check("单独发 ans 查值", calc.format_result("ans").split("\n")[0],
          "<code>ans=12937</code>｜<code>12937</code>｜")
    calc.format_result("1/3")
    check("分数精度不丢", calc.format_result("ans*3").split("\n")[0],
          "<code>ans*3=1</code>｜<code>1</code>｜")
    calc.clear_ans()
    check("清除后为 None", calc.get_ans(), None)
    expect_err("清除后 ans 报错", calc.format_result, "ans+1")
    calc.set_settings(conv_on=True, conv_mode="both", ans_on=True)
    calc.format_result("7*8")                       # 造一个记录，验证面板能显示出来
    _t2, kb2 = calc.settings_panel()
    flat2 = [b["text"] for row in kb2 for b in row]
    check("面板含连续计算开关", any(u"连续计算" in t for t in flat2), True)
    check("面板含清除按钮", any(u"清除上次结果" in t for t in flat2), True)
    check("面板显示上次结果", u"上次 56" in _t2, True)
    check("ans 开关回调", bool(calc.handle_cb("calcset:ans:toggle")), True)
    check("切换后为关闭", calc.get_settings()["ans_on"], False)
    check("关闭顺带清记录", calc.get_ans(), None)
    calc.handle_cb("calcset:ans:toggle")
    check("再切回开启", calc.get_settings()["ans_on"], True)
    check("ans 清除回调", bool(calc.handle_cb("calcset:ans:clear")), True)

    # 隐式连续计算：发 +3 即「上次结果 +3」
    print("[9] 隐式连续计算（+3 / *2 / ^2，含斜杠除法 /0）")
    calc.set_settings(ans_on=True, fmt="paren", conv_on=False, decimals=2)
    calc.clear_ans()
    check("is_cont_input /0", calc.is_cont_input("/0"), True)
    check("is_cont_input /5", calc.is_cont_input("/5"), True)
    check("is_cont_input /calc 仍是命令", calc.is_cont_input("/calc"), False)
    check("is_cont_input /menu 仍是命令", calc.is_cont_input("/menu"), False)
    check("首次 3+3", calc.format_result("3+3").split("\n")[0],
          "<code>3+3=6</code>｜<code>6</code>｜")
    check("+3 展开为 6+3", calc.format_result("+3").split("\n")[0],
          "<code>6+3=9</code>｜<code>9</code>｜")
    check("连发 +3", calc.format_result("+3").split("\n")[0],
          "<code>9+3=12</code>｜<code>12</code>｜")
    check("*2", calc.format_result("*2").split("\n")[0],
          "<code>12*2=24</code>｜<code>24</code>｜")
    check("/3", calc.format_result("/3").split("\n")[0],
          "<code>24/3=8</code>｜<code>8</code>｜")
    check("^2", calc.format_result("^2").split("\n")[0],
          "<code>8^2=64</code>｜<code>64</code>｜")
    check("//5", calc.format_result("//5").split("\n")[0],
          "<code>64//5=12</code>｜<code>12</code>｜")
    expect_err("斜杠除法 /0 除零报错", calc.format_result, "/0")
    # /0 报错时 ans 不变（仍是 //5 后的 12），/2 即 12/2=6
    check("斜杠除法 /2", calc.format_result("/2").split("\n")[0],
          "<code>12/2=6</code>｜<code>6</code>｜")
    # 歧义：带第二个运算符的一律按普通表达式算，不能误接 ans
    check("-5+3 是普通表达式", calc.format_result("-5+3").split("\n")[0],
          "<code>-5+3=-2</code>｜<code>-2</code>｜")
    check("-(3+4) 是普通表达式", calc.format_result("-(3+4)").split("\n")[0],
          "<code>-(3+4)=-7</code>｜<code>-7</code>｜")
    check("-3^2 是普通表达式", calc.format_result("-3^2").split("\n")[0],
          "<code>-3^2=-9</code>｜<code>-9</code>｜")
    # 无记录时 +3 应报错而不是当 0+3
    calc.clear_ans()
    expect_err("无记录时 +3 报错", calc.format_result, "+3")
    # 关闭后不识别
    calc.set_settings(ans_on=False)
    check("关闭后 +3 不识别", calc.looks_like_expr("+3"), False)
    check("关闭后 *2 不识别", calc.looks_like_expr("*2"), False)
    calc.set_settings(ans_on=True, conv_on=True, conv_mode="both")

    # ------------------------------------------------------------ 超时与 /00 退出
    print("[10] 连续计算退出：/00 手动 + 3 分钟自动超时")
    calc.set_settings(ans_on=True, fmt="paren", conv_on=False, decimals=2)
    calc.clear_ans()
    check("is_cont_exit /00", calc.is_cont_exit("/00"), True)
    check("is_cont_exit /000", calc.is_cont_exit("/000"), True)
    check("is_cont_exit /0 不是退出", calc.is_cont_exit("/0"), False)
    check("/00 不算连续算式", calc.is_cont_input("/00"), False)
    check("/0 仍是连续算式", calc.is_cont_input("/0"), True)
    calc.format_result("100")
    check("有结果时 +5 生效", calc.format_result("+5").split("\n")[0],
          "<code>100+5=105</code>｜<code>105</code>｜")
    check("exit_cont 返回提示", u"已退出连续计算" in calc.exit_cont(), True)
    check("退出后 ans 为 None", calc.get_ans(), None)
    expect_err("退出后 +5 报错", calc.format_result, "+5")
    # 超时：把时间戳往回拨 > CONT_TIMEOUT
    calc.format_result("50")
    check("未超时 +5 生效", calc.format_result("+5").split("\n")[0],
          "<code>50+5=55</code>｜<code>55</code>｜")
    import time as _time
    calc.set_settings(ans_ts=_time.time() - (calc.CONT_TIMEOUT + 1))
    check("超时后 cont_expired", calc.cont_expired(), True)
    check("超时后 ans 视为 None", calc.get_ans(), None)
    expect_err("超时后 +5 报错", calc.format_result, "+5")
    try:
        calc.format_result("+5")
    except calc.CalcError as e:
        check("超时提示含「自动退出」", u"自动退出" in str(e), True)
    _t3, _kb3 = calc.settings_panel()
    check("面板显示已超时", u"已超时" in _t3, True)
    check("面板含 /00 说明", u"/00" in _t3, True)
    calc.set_settings(conv_on=True, conv_mode="both")

    # ---------------------------------------------------------- 边界与回归防线
    print("[11] 连续计算边界")
    import json as _json
    import tempfile as _tf
    calc.set_settings(ans_on=True)
    # 旧版本遗留数据：有 ans 但没有 ans_ts —— 必须按过期处理，不能永久有效
    old = os.path.join(_tf.mkdtemp(), "old.json")
    with open(old, "w", encoding="utf-8") as fh:
        _json.dump({"decimals": 2, "fmt": "paren", "conv_on": False,
                    "conv_mode": "both", "ans_on": True, "ans": "99"}, fh)
    calc.SETTINGS_FILE = old
    calc._SETTINGS_CACHE = None
    check("无时间戳的旧记录判为过期", calc.cont_expired(), True)
    check("无时间戳时 get_ans 为 None", calc.get_ans(), None)
    expect_err("无时间戳时 +1 报错", calc.format_result, "+1")
    # 关掉开关后 /00 不该被当成退出指令（避免回废话）
    calc.set_settings(ans_on=False)
    check("关闭时 /00 不算退出", calc.is_cont_exit("/00"), False)
    check("关闭时 /00 不算算式", calc.is_cont_input("/00"), False)
    calc.set_settings(ans_on=True)
    check("开启时 /00 算退出", calc.is_cont_exit("/00"), True)

    # -------------------------------------------------------- 并发与持久化安全
    print("[12] 并发写设置文件（线程安全 + 原子写）")
    import threading as _th
    import json as _json
    _d2 = _tf.mkdtemp()
    calc.SETTINGS_FILE = os.path.join(_d2, "calc_settings.json")
    calc.set_settings(ans_on=True, decimals=4, fmt="eq", conv_on=True, conv_mode="acct")
    calc.clear_ans()
    _errs = []

    def _worker(i):
        for j in range(40):
            calc._SETTINGS_CACHE = None           # 强制读文件，放大竞态窗口
            try:
                calc.format_result("%d*%d" % (i, j))
                _json.load(open(calc.SETTINGS_FILE, encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                _errs.append("%s: %s" % (type(e).__name__, e))

    _ts = [_th.Thread(target=_worker, args=(i,)) for i in range(10)]
    for t in _ts:
        t.start()
    for t in _ts:
        t.join()
    check("10 线程并发写异常数", len(_errs), 0)
    _final = _json.load(open(calc.SETTINGS_FILE, encoding="utf-8"))
    for _k in ("decimals", "fmt", "conv_on", "conv_mode", "ans_on"):
        check(u"设置项保留 %s" % _k, _k in _final, True)
    check("无 .tmp 残留", os.path.exists(calc.SETTINGS_FILE + ".tmp"), False)

    # ------------------------------------------------------------------ 汇总
    print()
    print("=" * 56)
    print("通过 %d，失败 %d" % (len(PASS), len(FAIL)))
    if FAIL:
        print()
        print("失败明细：")
        for name, got, exp in FAIL:
            print("  - %s\n      得到 %r\n      期望 %r" % (name, got, exp))
        return 1
    print("全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
