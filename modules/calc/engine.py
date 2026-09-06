# -*- coding: utf-8 -*-
"""安全算式求值器 —— 给 Telegram bot 用的计算器。

不碰 eval/exec。走 ast 解析 + 节点白名单：
  允许：数字常量、四则运算、括号、取模、整除、幂、正负号、白名单数学函数/常量
  禁止：变量、属性访问、下标、比较、赋值、lambda、推导式、调用非白名单函数
数值一律先转 Fraction 做精确运算，最后再格式化成整数 / 有限小数 / 近似小数。
"""

import ast
import json
import math
import os
import re
import threading
import time
import warnings
from fractions import Fraction

# 设置文件与主程序同目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(BASE_DIR, "calc_settings.json")
DEFAULT_DECIMALS = 2          # 默认保留 2 位小数

MAX_LEN = 120            # 输入最大字符数（归一化后）
CONT_TIMEOUT = 180       # 连续计算结果的有效期（秒），超时自动退出
MAX_NODES = 300          # AST 节点数上限
MAX_DIGITS = 200         # 中间/最终结果最大十进制位数，超限直接拒绝
MAX_POW_EXP = 100000     # 幂指数绝对值上限（整数幂；位数另有限制）
MAX_FACTORIAL = 4000     # 阶乘上限
MAX_DEPTH = 30           # 表达式嵌套深度上限
MAX_DECIMALS = 10        # 无限小数最多保留位数

# 全角 / 中文符号归一化
_TRANS = {
    ord(u"＋"): u"+", ord(u"－"): u"-", ord(u"﹣"): u"-", ord(u"－"): u"-",
    ord(u"＊"): u"*", ord(u"×"): u"*", ord(u"✕"): u"*", ord(u"⋅"): u"*",
    ord(u"·"): u"*", ord(u"／"): u"/", ord(u"÷"): u"/", ord(u"∕"): u"/",
    ord(u"％"): u"%", ord(u"＾"): u"^", ord(u"（"): u"(", ord(u"）"): u")",
    ord(u"【"): u"(", ord(u"】"): u")", ord(u"［"): u"(", ord(u"］"): u")",
    ord(u"｛"): u"(", ord(u"｝"): u")", ord(u"，"): u",", ord(u"、"): u",",
    ord(u"。"): u".", ord(u"．"): u".", ord(u"＝"): u"=", ord(u"？"): u"?",
    ord(u"＇"): u"'", ord(u"＂"): u'"', ord(u"　"): u" ", ord(u" "): u" ",
}

# 允许的字符集（归一化后），用于判断「这条消息像不像算式」
import string as _string

_EXPR_CHARS = set(u"0123456789+-*/^%().,") | set(_string.ascii_letters)
_OPERATORS = set(u"+-*/^%")

_IPV4_RE = re.compile(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}")

# 允许出现在算式里的标识符（函数 / 常量）
_TOKEN_RE = re.compile(r"[0-9A-Za-z._]+")
_SCI_RE = re.compile(r"^\d+(\.\d+)?[eE][+-]?\d+$")
# 写了一半的科学计数法：1e / 1e+ / 2.5e- —— 标准计算器一律报错。
# 前面排除 0x1e 这类十六进制（e 的左边紧挨着字母数字时不算），
# 后面排除真正的指数（e 后跟可带正负号的整数）。
_BAD_SCI_RE = re.compile(r"(?<![0-9A-Za-z_.])[0-9]+(?:\.[0-9]+)?[eE](?![+-]?[0-9])")
_RADIX_RE = re.compile(r"^0[xXoObB][0-9a-fA-F_]+$")

# 连续计算：以运算符开头、后面只跟一个数字 —— 如 +3 / *2 / -5 / ^2 / //2
# 注意 -5+3 不匹配（后面还有运算符），所以仍按普通表达式算成 -2
_CONT_RE = re.compile(r"^[+\-*/%^]+[0-9][0-9.eE]*$")


def _tokens_ok(s, allow_ans=False):
    """字母只能出现在白名单标识符 / 科学计数法 / 十六进制里，避免把人话当算式。

    allow_ans=True 时额外放行 ans（连续计算开关打开才传 True）。
    """
    for tok in _TOKEN_RE.findall(s):
        if re.match(r"^[0-9._]+$", tok):
            continue
        if tok.lower() in _WORDS:
            continue
        if allow_ans and tok.lower() == "ans":
            continue
        if _SCI_RE.match(tok) or _RADIX_RE.match(tok):
            continue
        return False
    return True


class CalcError(Exception):
    pass


def _insert_implicit_mul(s):
    """隐式乘法补乘号：数字/括号/常量直接相连时插入 *。

    例：10(1*2) → 10*(1*2)   2pi → 2*pi   (1+2)(3+4) → (1+2)*(3+4)   pi(2) → pi*(2)
    先把 0x/0b/0o 进制数与科学计数法 1e5 保护起来，避免被拆成 0*ff / 1*e5；
    函数名不受影响（sqrt(4) 的 t 是字母不是数字，sqrt 也不在常量表里）。
    """
    protected = []

    def _protect(m):                       # 把特殊数换成占位符，处理完再换回
        protected.append(m.group(0))
        return "\x00%d\x00" % (len(protected) - 1)

    s = re.sub(
        r"0[xX][0-9a-fA-F]+|0[bB][01]+|0[oO][0-7]+|\d+(?:\.\d+)?[eE][+-]?\d+",
        _protect, s)
    # 1. ) 后接 ( / 数字 / 字母：)→ )*
    s = re.sub(r"\)(?=[(\dA-Za-z])", ")*", s)
    # 2. 数字 后接 ( / 字母：数字 → 数字*（进制/科学计数法已保护，不会误伤）。
    #    但如果这个数字本身就是标识符的一部分（如 log10 末尾的 0），不能补 ——
    #    否则 log10(100) 会被拆成 log10*(100)，报「不支持的符号 log10」。
    #    判断：从匹配位置往前扫，若一路都是字母数字下划线且最前面是字母，
    #    说明它是标识符的一部分（log10 的 0 前面是 1、再往前是 log）。
    #    注意只往前看一位不够：log2 能过、log10 就漏了（0 前面是数字 1）。
    def _digit_mul(m):
        i = m.start()
        j = i
        while j > 0 and (s[j - 1].isalnum() or s[j - 1] == "_"):
            j -= 1
        if j < i and s[j].isalpha():
            return m.group(1)
        return m.group(1) + "*"

    s = re.sub(r"(\d)(?=[(A-Za-z])", _digit_mul, s)
    # 3. 常量名 后接 (：pi( e( tau( phi( → 加 *
    for cst in ("pi", "e", "tau", "phi"):
        s = re.sub(r"(?<![A-Za-z0-9_])" + cst + r"(?=\()", cst + "*", s)
    for i, p in enumerate(protected):      # 恢复被保护的特殊数
        s = s.replace("\x00%d\x00" % i, p)
    return s


def _pre_normalize(text):
    """归一化，但不补隐式乘法。

    畸形输入检测必须看这一层：`1e` 一旦被补成 `1*e`，就看不出它是残缺的科学计数法了。
    """
    s = str(text or "").translate(_TRANS)
    # 方括号/花括号一律当小括号 —— 用户常写 {[(2+3)]} 这种分层括号，
    # 原来这几种字符不在字符白名单里，整条式子会被当成普通聊天不计算
    s = re.sub(r"[\[\{]", "(", s)
    s = re.sub(r"[\]\}]", ")", s)
    s = re.sub(r"\s+", "", s)
    # 去掉结尾的 = ? 等
    s = s.rstrip(u"=?？＝")
    # 千分位逗号：只删「数字,数字数字数字」这种
    while True:
        s2 = re.sub(r"(?<=\d),(?=\d\d\d(\D|$))", "", s)
        if s2 == s:
            break
        s = s2
    return s


def _normalize(text):
    return _insert_implicit_mul(_pre_normalize(text))


def is_cont_input(text):
    """连续计算输入判定（含斜杠除法 /0 /5，供主程序在命令分支之前调用）。

    调用方在 try 之外用它，所以这里不能抛异常：任何畸形输入一律当「不是连续计算」。
    """
    try:
        return _is_cont_input(text)
    except Exception:  # noqa: BLE001
        return False


def _is_cont_input(text):
    """连续计算输入的实际判定（异常由 is_cont_input 兜掉）。

    开启 ans_on 时：+3 *2 -5 ^2 //5 %7 /0 以及单独的 ans 都算连续计算输入。
    /menu /calc 这类「斜杠+字母」不算，仍走命令。
    """
    s = _normalize(text)
    if not s:
        return False
    if not bool(get_settings().get("ans_on")):
        return False
    if is_cont_exit(s):                         # /00 是退出，不是算式
        return False
    if s.lower() == "ans":
        return True
    if _CONT_RE.match(s):
        return True
    if re.match(r"^/[0-9.]+$", s):              # /0 /5 —— 斜杠除法
        return True
    return False


def looks_like_expr(text):
    """判断这条消息是否应当被当作算式处理。保守判定，避免误伤 IP、普通聊天。"""
    s = _normalize(text)
    if not s or len(s) < 3 or len(s) > MAX_LEN:
        return False
    if _IPV4_RE.search(s) or ":" in s:          # 别把 1.2.3.0/24 或 IPv6 当算式
        return False
    if s.replace(",", "").replace(".", "").isdigit():
        return True                             # 纯数字（44 / 1,500 / 3.14）也算算式
    if any(c not in _EXPR_CHARS for c in s):
        return False
    ans_on = bool(get_settings().get("ans_on"))
    if ans_on and s.lower() == "ans":           # 单独发 ans = 查看上一次结果
        return True
    if ans_on and _CONT_RE.match(s):            # 连续计算：+3 / *2 / -5
        return True
    toks = _TOKEN_RE.findall(s)
    has_num = any(c.isdigit() for c in s)
    has_const = any(t.lower() in CONSTS for t in toks)
    if not (has_num or has_const):   # 纯字母词组不是算式
        return False
    if not _tokens_ok(s, allow_ans=ans_on):
        return False
    core = s.lstrip(u"+-")
    return any(c in _OPERATORS or c in u"()" for c in core)


# ---------------------------------------------------------------------------
# 白名单常量与函数
# ---------------------------------------------------------------------------

def _f(x):
    """任意数值 -> Fraction（float 走 str，避免二进制误差）。"""
    if isinstance(x, Fraction):
        return x
    if isinstance(x, bool):
        raise CalcError("不支持布尔值")
    if isinstance(x, int):
        return Fraction(x)
    if isinstance(x, float):
        if math.isnan(x) or math.isinf(x):
            raise CalcError("结果不是有限数")
        return Fraction(str(x))
    raise CalcError("不支持的数值类型")


MAX_BITS = 700          # 整数二进制位数上限（约 210 位十进制），够用且不触发 str 限制


def _chk(x):
    """检查数值规模，防止爆内存。用 bit_length 估算，避免对超大整数调用 str()。"""
    if isinstance(x, Fraction):
        if abs(x.numerator).bit_length() > MAX_BITS or x.denominator.bit_length() > MAX_BITS:
            raise CalcError("数字太大，算不动")
    return x


CONSTS = {
    "pi": Fraction(str(math.pi)),
    "e": Fraction(str(math.e)),
    "tau": Fraction(str(math.tau)),
    "phi": Fraction(str((1 + math.sqrt(5)) / 2)),
}


def _fn_sqrt(x):
    x = float(x)
    if x < 0:
        raise CalcError("负数不能开平方")
    return _f(math.sqrt(x))


def _fn_log(x, base=None):
    x = float(x)
    if x <= 0:
        raise CalcError("对数真数必须大于 0")
    if base is None:
        return _f(math.log(x))
    b = float(base)
    if b <= 0 or b == 1:
        raise CalcError("对数底数必须大于 0 且不等于 1")
    return _f(math.log(x, b))


def _fn_factorial(x):
    if x.denominator != 1 or x < 0:
        raise CalcError("阶乘只接受非负整数")
    n = int(x)
    if n > MAX_FACTORIAL:
        raise CalcError("阶乘上限 %d" % MAX_FACTORIAL)
    if n > 10 and n * math.log10(n) > MAX_DIGITS:
        raise CalcError("阶乘结果位数过大")
    return Fraction(math.factorial(n))


def _fn_round(x, n=None):
    if n is None:
        return Fraction(math.floor(float(x) + 0.5)) if x >= 0 else Fraction(math.ceil(float(x) - 0.5))
    if n.denominator != 1:
        raise CalcError("round 的位数必须是整数")
    return _f(round(float(x), int(n)))


def _fn_gcd(*args):
    vals = [int(a) for a in args if a.denominator == 1]
    if len(vals) != len(args):
        raise CalcError("gcd 只接受整数")
    r = 0
    for v in vals:
        r = math.gcd(r, abs(v))
    return Fraction(r)


def _fn_lcm(*args):
    vals = [int(a) for a in args if a.denominator == 1]
    if len(vals) != len(args):
        raise CalcError("lcm 只接受整数")
    r = 1
    for v in vals:
        r = r * abs(v) // math.gcd(r, abs(v))
    return Fraction(r)


def _int_args(name, *args):
    """校验全是非负整数，返回 int 列表；否则报错。"""
    out = []
    for a in args:
        if a.denominator != 1 or a < 0:
            raise CalcError("%s 只接受非负整数" % name)
        out.append(int(a))
    return out


def _fn_comb(n, k):
    """组合数 C(n,k)。用 Fraction 递推，精确且不依赖 math.comb（3.8 才有）。"""
    n, k = _int_args("comb", n, k)
    if k > n:
        return Fraction(0)
    if n > 100000:
        raise CalcError("comb 的 n 太大（上限 100000）")
    k = min(k, n - k)
    r = Fraction(1)
    for i in range(1, k + 1):
        r = r * (n - k + i) / i
    return r


def _fn_perm(n, k):
    """排列数 P(n,k) = n!/(n-k)!。"""
    n, k = _int_args("perm", n, k)
    if k > n:
        return Fraction(0)
    if n > 100000:
        raise CalcError("perm 的 n 太大（上限 100000）")
    r = Fraction(1)
    for i in range(n - k + 1, n + 1):
        r *= i
    return r


def _fn_nthroot(x, n):
    """n 次方根。奇次根允许负数，偶次根要求非负。"""
    if n == 0:
        raise CalcError("0 次方根无意义")
    if x < 0:
        if n.denominator == 1 and int(n) % 2 == 1:
            return -_safe_pow(-x, Fraction(1) / n)
        raise CalcError("负数不能开偶次方根")
    return _safe_pow(x, Fraction(1) / n)


def _fn_gamma(x):
    try:
        return _f(math.gamma(float(x)))
    except (OverflowError, ValueError):
        raise CalcError("gamma 溢出或无定义")


def _fn_hypot(*args):
    return _f(math.hypot(*[float(a) for a in args]))


def _trig(fn, name):
    def _inner(x):
        return _f(fn(float(x)))
    _inner.__name__ = name
    return _inner


def _atrig(fn, name):
    def _inner(x):
        v = float(x)
        if name in ("asin", "acos") and not (-1 <= v <= 1):
            raise CalcError("%s 的参数必须在 -1 ~ 1 之间" % name)
        return _f(fn(v))
    _inner.__name__ = name
    return _inner


FUNCS = {
    "sqrt": (1, 1, _fn_sqrt), "cbrt": (1, 1, lambda x: _f(math.copysign(abs(float(x)) ** (1.0 / 3), float(x)))),
    "abs": (1, 1, lambda x: abs(x)), "fabs": (1, 1, lambda x: abs(x)),
    "floor": (1, 1, lambda x: Fraction(math.floor(x))), "ceil": (1, 1, lambda x: Fraction(math.ceil(x))),
    "round": (1, 2, _fn_round), "trunc": (1, 1, lambda x: Fraction(math.trunc(x))),
    "ln": (1, 1, lambda x: _fn_log(x)), "log": (1, 2, _fn_log),
    "log10": (1, 1, lambda x: _fn_log(x, 10)), "log2": (1, 1, lambda x: _fn_log(x, 2)),
    "lg": (1, 1, lambda x: _fn_log(x, 10)),
    "exp": (1, 1, lambda x: _f(math.exp(min(float(x), 700)))),
    "sin": (1, 1, _trig(math.sin, "sin")), "cos": (1, 1, _trig(math.cos, "cos")),
    "tan": (1, 1, _trig(math.tan, "tan")),
    "asin": (1, 1, _atrig(math.asin, "asin")), "acos": (1, 1, _atrig(math.acos, "acos")),
    "atan": (1, 1, _atrig(math.atan, "atan")),
    "sinh": (1, 1, _trig(math.sinh, "sinh")), "cosh": (1, 1, _trig(math.cosh, "cosh")),
    "tanh": (1, 1, _trig(math.tanh, "tanh")),
    "degrees": (1, 1, lambda x: _f(math.degrees(float(x)))),
    "radians": (1, 1, lambda x: _f(math.radians(float(x)))),
    "rad": (1, 1, lambda x: _f(math.radians(float(x)))),
    "deg": (1, 1, lambda x: _f(math.degrees(float(x)))),
    "factorial": (1, 1, _fn_factorial), "fact": (1, 1, _fn_factorial),
    "pow": (2, 2, lambda x, y: _safe_pow(x, y)),
    "gcd": (2, 6, _fn_gcd), "lcm": (2, 6, _fn_lcm),
    "max": (2, 8, lambda *a: max(a)), "min": (2, 8, lambda *a: min(a)),
    "hypot": (2, 8, _fn_hypot),                      # 直角三角形斜边 / 欧几里得范数
    "sign": (1, 1, lambda x: Fraction((x > 0) - (x < 0))),
    "comb": (2, 2, _fn_comb), "ncr": (2, 2, _fn_comb),     # 组合数 C(n,k)
    "perm": (2, 2, _fn_perm), "npr": (2, 2, _fn_perm),     # 排列数 P(n,k)
    "gamma": (1, 1, _fn_gamma), "lgamma": (1, 1, lambda x: _f(math.lgamma(float(x)))),
    "nthroot": (2, 2, _fn_nthroot),                  # n 次方根
    "avg": (2, 8, lambda *a: sum(a) / len(a)), "mean": (2, 8, lambda *a: sum(a) / len(a)),
    "sum": (2, 8, lambda *a: sum(a)),
}

# 字母白名单直接由函数表 + 常量表推导。
# 之前这里是手写的一份列表，和 FUNCS 各维护各的，迟早漂移 —— 推导出来就不会再不同步。
_WORDS = set(FUNCS) | set(CONSTS)


def _safe_pow(base, exp):
    """整数幂走精确计算并预估规模；非整数幂转 float。"""
    if base.denominator == 1 and exp.denominator == 1 and exp >= 0:
        b, e = int(base), int(exp)
        if abs(e) > MAX_POW_EXP:
            raise CalcError("幂指数超出上限（%d）" % MAX_POW_EXP)
        if abs(b) > 1 and e * math.log10(abs(b)) + 1 > MAX_DIGITS:
            raise CalcError("幂结果位数过大")
        return Fraction(b ** e)
    if base < 0 and exp.denominator != 1:
        raise CalcError("负数不能做分数次幂")
    if base == 0 and exp < 0:
        raise CalcError("0 不能做负次幂")
    b, e = float(base), float(exp)
    if abs(b) > 1 and abs(e) * math.log10(abs(b)) > MAX_DIGITS:
        raise CalcError("幂结果位数过大")
    try:
        r = b ** e
    except (OverflowError, ValueError):
        raise CalcError("幂运算溢出")
    if math.isnan(r) or math.isinf(r):
        raise CalcError("幂运算溢出")
    return _f(r)


# ---------------------------------------------------------------------------
# AST 求值
# ---------------------------------------------------------------------------

_BINOPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b if b != 0 else _zero_div(),
    ast.FloorDiv: lambda a, b: a // b if b != 0 else _zero_div(),
    ast.Mod: lambda a, b: a % b if b != 0 else _zero_div(),
    ast.Pow: lambda a, b: _safe_pow(a, b),
}

_UNARYOPS = {ast.UAdd: lambda a: a, ast.USub: lambda a: -a}


def _zero_div():
    raise CalcError("除数不能为 0")


def _eval(node, depth):
    if depth > MAX_DEPTH:
        raise CalcError("表达式嵌套太深")
    if isinstance(node, ast.Expression):
        return _eval(node.body, depth + 1)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise CalcError("只支持数字")
        return _chk(_f(node.value))
    if isinstance(node, ast.BinOp):
        op = _BINOPS.get(type(node.op))
        if op is None:
            raise CalcError("不支持的运算符")
        return _chk(op(_eval(node.left, depth + 1), _eval(node.right, depth + 1)))
    if isinstance(node, ast.UnaryOp):
        op = _UNARYOPS.get(type(node.op))
        if op is None:
            raise CalcError("不支持的运算符")
        return _chk(op(_eval(node.operand, depth + 1)))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise CalcError("不支持的调用")
        name = node.func.id.lower()
        spec = FUNCS.get(name)
        if spec is None:
            raise CalcError("不支持的函数 %s" % name)
        lo, hi, fn = spec
        if not (lo <= len(node.args) <= hi) or node.keywords:
            raise CalcError("%s 参数数量不对" % name)
        args = [_eval(a, depth + 1) for a in node.args]
        return _chk(_f(fn(*args)))
    if isinstance(node, ast.Name):
        key = node.id.lower()
        if key == "ans":
            if not get_settings().get("ans_on"):
                raise CalcError("连续计算未开启（/calc 里可打开）")
            prev = get_ans()
            if prev is None:
                raise CalcError(_ans_missing_hint())
            return _chk(prev)
        if key in CONSTS and CONSTS[key] is not None:
            return CONSTS[key]
        raise CalcError("不支持的符号：%s" % node.id)
    raise CalcError("表达式里有不支持的内容")


# ---------------------------------------------------------------------------
# 结果格式化
# ---------------------------------------------------------------------------



DEFAULT_SETTINGS = {"decimals": DEFAULT_DECIMALS, "fmt": "paren",
                    "conv_on": True, "conv_mode": "both",
                    "ans_on": True, "ans": None, "ans_ts": 0}   # 连续计算默认开启
DECIMAL_CHOICES = [1, 2, 3, 4, 5, 6]
FMT_LABEL = {"result": u"仅结果", "eq": u"算式+结果", "paren": u"算式+结果（结果）"}
FMT_ORDER = ["result", "eq", "paren"]
CONV_LABEL = {"read": u"自然读法", "acct": u"会计大写", "both": u"两种都显示"}
CONV_ORDER = ["read", "acct", "both"]


_SETTINGS_CACHE = None


def get_settings():
    """读全部设置；缺的项补默认值。

    进程内缓存，避免一次计算反复读文件（实测原本每次算题读 3 次）。
    设置只由本进程写入（set_settings 会清缓存），所以不存在跨进程失效问题。
    """
    global _SETTINGS_CACHE
    if _SETTINGS_CACHE is not None:
        return _SETTINGS_CACHE
    s = dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as fh:
            for k, v in (json.load(fh) or {}).items():
                if k in s:
                    s[k] = v
    except Exception:  # noqa: BLE001
        pass
    try:
        s["decimals"] = int(s["decimals"])
    except Exception:  # noqa: BLE001
        s["decimals"] = DEFAULT_DECIMALS
    if s["fmt"] not in FMT_ORDER:
        s["fmt"] = "paren"
    s["conv_on"] = bool(s.get("conv_on", True))
    if s["conv_mode"] not in CONV_ORDER:
        s["conv_mode"] = "both"
    _SETTINGS_CACHE = s
    return s


_SETTINGS_LOCK = threading.Lock()


def _read_raw():
    """读原始设置字典（不做校验，供写操作使用）。"""
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh) or {}
    except Exception:  # noqa: BLE001
        return {}


def _update_settings(kv):
    """设置文件的唯一写入口：加锁 + 原子替换。

    两个必须同时做的保护：
    1. 加锁 —— bot 是多线程处理消息的，并发「读-改-写」会互相覆盖导致设置项丢失
    2. 原子替换 —— 直接 open(w) 会在写入途中把文件截断成空文件，
                   此时另一个线程读到空内容，用户的设置就全没了。
       改成写临时文件 + os.replace（同分区内是原子操作）。
    """
    global _SETTINGS_CACHE
    with _SETTINGS_LOCK:
        data = _read_raw()
        data.update(kv)
        tmp = SETTINGS_FILE + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, SETTINGS_FILE)
        except Exception:  # noqa: BLE001
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:  # noqa: BLE001
                pass
        _SETTINGS_CACHE = None           # 写后失效，下次读重新加载
    return get_settings()


def set_settings(**kv):
    """合并写入设置，返回生效后的完整设置。"""
    return _update_settings(kv)


def get_decimals():
    """当前保留小数位数。"""
    return get_settings()["decimals"]


# ---------------------------------------------------------------------------
# ans：连续计算（上一次结果）
# ---------------------------------------------------------------------------

def cont_expired():
    """上次结果是否已超过 CONT_TIMEOUT 秒（自动退出）。"""
    st = get_settings()
    if not st.get("ans"):
        return False
    try:
        ts = float(st.get("ans_ts") or 0)
    except Exception:  # noqa: BLE001
        ts = 0
    if ts <= 0:
        # 没有时间戳 = 旧版本留下的记录，无法判断时效，按过期处理强制重新起算
        return True
    return (time.time() - ts) > CONT_TIMEOUT


def get_ans():
    """上一次结果（Fraction 或 None）；超过 3 分钟自动失效。"""
    raw = get_settings().get("ans")
    if not raw or cont_expired():
        return None
    try:
        return Fraction(str(raw))
    except Exception:  # noqa: BLE001
        return None


def set_ans(value):
    """记录本次结果，供下次 ans 引用。以分数字符串落盘，精度不丢。

    走 _update_settings（加锁 + 原子写），避免并发覆盖掉其它设置项。
    """
    _update_settings({"ans": str(value), "ans_ts": time.time()})
    return value


def clear_ans():
    """清除连续计算记录（/00 或关闭开关时调用）。"""
    _update_settings({"ans": None, "ans_ts": 0})


def _ans_missing_hint():
    """ans 不可用时区分「从未有过」和「已超时」。"""
    if get_settings().get("ans") and cont_expired():
        return u"上次结果已超过 %d 分钟未使用，已自动退出" % (CONT_TIMEOUT // 60)
    return u"还没有上一次结果，先算一个式子"


def is_cont_exit(text):
    """/00（两个以上 0）—— 手动退出连续计算。/0 仍是除以零。

    只在连续计算开启时才算退出指令，否则不当算式也不当命令，避免回废话。
    """
    if not bool(get_settings().get("ans_on")):
        return False
    return bool(re.match(r"^/0{2,}$", _normalize(text)))


def exit_cont():
    """退出连续计算：清掉上次结果，返回提示文本。"""
    clear_ans()
    return (u"👋 已退出连续计算，下次结果重新起算。\n"
            u"<i>连续计算开启时，3 分钟没操作也会自动退出。</i>")


def set_decimals(n):
    """设置保留小数位数，0~10。返回实际生效值。"""
    n = int(n)
    if not (0 <= n <= 10):
        raise CalcError("保留位数只能是 0~10")
    return set_settings(decimals=n)["decimals"]


def _round_frac(fr, nd):
    """把 Fraction 四舍五入到 nd 位小数，返回 (缩放整数, 是否发生舍入)。

    全整数运算，不经过 float —— 这是大数不失真的关键。
    """
    scale = 10 ** nd
    n, d = fr.numerator, fr.denominator
    if nd:
        n, d = n * scale, d
    q, r = divmod(abs(n), d)          # Python divmod 向下取整，先取绝对值再补符号
    if r * 2 >= d:                    # 四舍五入（含 .5 进位）
        q += 1
    if n < 0:
        q = -q
    return q, (q * d != n) if nd else (q * d != n)


def _frac_to_str(fr, nd):
    """Fraction -> 十进制字符串（四舍五入到 nd 位，末尾 0 去掉）。"""
    q, _changed = _round_frac(fr, nd)
    neg = q < 0
    digits = str(abs(q))
    if nd:
        digits = digits.rjust(nd + 1, "0")
        ip, fp = digits[:-nd], digits[-nd:]
        fp = fp.rstrip("0")
        s = ip + ("." + fp if fp else "")
    else:
        s = digits
    return ("-" + s) if (neg and s.strip("0.")) else s


def _sci_str(fr, digits=6):
    """精确科学计数法：Fraction -> 字符串，不经过 float。"""
    a = abs(fr)
    if a == 0:
        return "0"
    # 用 float 只估算数量级，随后用整数比较校正，保证结果精确
    e = int(math.floor(math.log10(float(a)))) if a >= 1 else int(math.floor(math.log10(float(a))))
    while a >= Fraction(10) ** (e + 1):
        e += 1
    while a < Fraction(10) ** e:
        e -= 1
    m = a / (Fraction(10) ** e)                  # 1 <= m < 10，精确
    mi, _ = _round_frac(m, digits)
    if mi >= 10 ** (digits + 1):                 # 进位溢出（如 9.999999 -> 10）
        mi //= 10
        e += 1
    s = str(mi).rjust(digits + 1, "0")
    mant = (s[0] + "." + s[1:]).rstrip("0").rstrip(".")
    out = "%se%s%d" % (mant, "+" if e >= 0 else "-", abs(e))
    return ("-" + out) if fr < 0 else out


def format_value(fr):
    """Fraction -> (数字字符串, 近似类型)

    一律输出纯数字（不带千分位），保证从 Telegram 复制出去可以直接粘贴使用。
    小数位数由 get_decimals() 决定。全程整数/Fraction 运算，大数不失真。

    第二个返回值："" 精确 / "round" 定点四舍五入 / "sci" 科学计数法。
    科学计数法不是「保留 N 位小数」，必须让调用方能区分，文案才说得准。
    """
    nd = get_decimals()
    if fr.denominator == 1:
        return str(fr.numerator), ""
    # 超大 / 超小走科学计数法（nd 位定点表示不出来时）
    a = abs(fr)
    if fr != 0 and (a >= Fraction(10) ** 15 or a <= Fraction(1, 10 ** 12)):
        return _sci_str(fr), "sci"
    s = _frac_to_str(fr, nd)
    if s in ("", "-", "-0", "0"):
        s = "0"
    # 是否近似：四舍五入后的值与原值不相等
    q, _ = _round_frac(fr, nd)
    approx = (Fraction(q, 10 ** nd) if nd else Fraction(q)) != fr
    return s, ("round" if approx else "")


# ---------------------------------------------------------------------------
# 中文读法 / 会计大写金额
# ---------------------------------------------------------------------------

CN_NUM = u"零一二三四五六七八九"
CN_UNIT = [u"", u"十", u"百", u"千"]
# 中文节位：万(10^4) 亿(10^8) 兆(10^12) 京(10^16) 垓(10^20) 秭(10^24) 穰(10^28) 沟(10^32)
CN_SEC = [u"", u"万", u"亿", u"兆", u"京", u"垓", u"秭", u"穰", u"沟"]

UP_NUM = u"零壹贰叁肆伍陆柒捌玖"
UP_UNIT = [u"", u"拾", u"佰", u"仟"]
UP_SEC = [u"", u"万", u"亿", u"兆", u"京", u"垓", u"秭", u"穰", u"沟"]


def _cn_group(n, digits, units):
    """把 0~9999 转成中文（不带节位），返回列表。"""
    out = []
    zero = False
    for i in range(3, -1, -1):
        d = (n // (10 ** i)) % 10
        if d == 0:
            if out:
                zero = True
            continue
        if zero:
            out.append(digits[0])
            zero = False
        out.append(digits[d] + units[i])
    return out


def _cn_int(n, digits, units, secs, one_lead=True):
    """整数 -> 中文字符串。

    one_lead=False 时 10~19 读作「十二」而不是「一十二」（自然读法）；
    会计大写必须 one_lead=True，规范写法是「壹拾贰」。
    """
    if n == 0:
        return digits[0]
    if n < 0:
        return u"负" + _cn_int(-n, digits, units, secs, one_lead)
    parts = []
    sec = 0
    need_zero = False      # 低位组不足四位 -> 本组后面要补「零」
    while n > 0:
        if sec >= len(secs):
            raise CalcError("数字超出可转换范围（最大 %s）" % secs[-1])
        g = n % 10000
        n //= 10000
        if g:
            gp = _cn_group(g, digits, units)
            grp = u"".join(gp) + secs[sec]
            if need_zero:
                grp += digits[0]                 # 一万「零」三 / 一亿「零」三百
            parts.insert(0, grp)
            need_zero = (g < 1000)
        else:
            need_zero = bool(parts)              # 整组为零且已有高位 -> 补零
        sec += 1
    s = u"".join(parts)
    if not one_lead and s.startswith(digits[1] + units[1]):
        s = s[len(digits[1]):]                   # 一十二 -> 十二
    return s


def cn_reading(fr):
    """数值 -> 中文读法，如 6762 -> 六千七百六十二。

    整数部分与小数部分都用 Fraction 整除/取余，大数不失真。
    """
    nd = get_decimals()
    neg = fr < 0
    a = abs(fr)
    ip = a.numerator // a.denominator          # 精确整数部分
    fp = a - ip                                # 精确小数部分
    s = _cn_int(ip, CN_NUM, CN_UNIT, CN_SEC, one_lead=False)
    if fp > 0 and nd:
        q, _ = _round_frac(fp, nd)             # 缩放后的小数整数（已四舍五入）
        dec = str(q).rjust(nd, "0").rstrip("0")
        if dec:
            s += u"点" + u"".join(CN_NUM[int(c)] for c in dec)
    return (u"负" + s) if neg else s


def cn_accounting(fr):
    """数值 -> 会计大写金额，如 6762 -> 陆仟柒佰陆拾贰元整。

    遵循央行《正确填写票据和结算凭证的基本规定》：
    - 元位是「零」时不写「零元」（0.14 -> 壹角肆分）
    - 元位非零、角位为零而分位不为零时写「零」（3.05 -> 叁元零伍分）
    - 分位四舍五入，整数运算，大数不失真
    """
    neg = fr < 0
    a = abs(fr)
    ip = a.numerator // a.denominator
    frac = a - ip
    cents, _ = _round_frac(frac, 2)            # 精确到分（四舍五入）
    if cents >= 100:                           # 进位到元
        ip += 1
        cents -= 100
    jiao, fen = cents // 10, cents % 10
    if ip == 0:
        # 零元：省略「零元」，直接从角/分起写
        if jiao == 0 and fen == 0:
            return u"零元整"
        body = u""
        if jiao:
            body += UP_NUM[jiao] + u"角"
        if fen:
            body += UP_NUM[fen] + u"分"
    else:
        body = _cn_int(ip, UP_NUM, UP_UNIT, UP_SEC, one_lead=True) + u"元"
        if jiao == 0 and fen == 0:
            body += u"整"
        else:
            if jiao:
                body += UP_NUM[jiao] + u"角"
            elif fen:
                body += UP_NUM[0]              # 角位为零补「零」
            if fen:
                body += UP_NUM[fen] + u"分"
    return (u"负" + body) if neg else body


def calc_msgs(raw):
    """计算结果拆成多条消息 -> [(文本, 按钮或None), ...]。

    第 1 条：主结果（不带按钮，设置走 /calc 菜单）；
    第 2 条（可选）：自然读法 / 会计大写。
    """
    # 必须在补隐式乘法之前判：_normalize 会把 1e 补成 1*e，
    # 洗白成「1×自然常数」算出一个莫名其妙的结果，而不是报「写法不完整」。
    if _BAD_SCI_RE.search(_pre_normalize(raw)):
        raise CalcError("科学计数法缺指数：e 后面要跟数字，例如 1e5、2.5e-3")
    expr = _normalize(raw)
    if not looks_like_expr(raw) and not expr:
        raise CalcError("这不是一个算式")
    if len(expr) > MAX_LEN:                    # 绕过 looks_like_expr 时也要卡长度
        raise CalcError("表达式太长（上限 %d 字符）" % MAX_LEN)
    # 连续计算：以运算符开头时自动接上上次结果（+3 -> ans+3）
    st0 = get_settings()
    cont = bool(st0.get("ans_on")) and bool(_CONT_RE.match(expr))
    if cont:
        prev = get_ans()
        if prev is None:
            raise CalcError(_ans_missing_hint())
        shown = format_value(prev)[0] + expr   # 展示时把上次结果展开，如 6+3
        expr = "ans" + expr
    else:
        shown = _normalize(raw)
    # ^ 视作幂
    expr = expr.replace("^", "**")
    try:
        # 抑制 Python 对 1_0 之类字面量的 SyntaxWarning，避免污染 bot 日志
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        raise CalcError("表达式看不懂，检查一下括号")
    node_count = sum(1 for _ in ast.walk(tree))
    if node_count > MAX_NODES:
        raise CalcError("表达式太长了")
    value = _eval(tree, 0)
    text, approx = format_value(value)
    st = get_settings()
    set_ans(value)                  # 始终记录（汇率模块的「算式后补币种」联动依赖；
                                    #   ans_on 只控制 +3 这类连续计算输入是否生效）
    # 结果主体：三种显示格式（都做成可点击复制的独立 code 区块）
    fmt = st["fmt"]
    if fmt == "result":                          # 仅显示结果
        line = "<code>%s</code>" % esc(text)
    elif fmt == "eq":                            # 算式=结果
        line = "<code>%s=%s</code>" % (esc(shown), esc(text))
    else:                                        # 算式=结果｜结果｜（竖线在 code 外，只复制数字）
        line = "<code>%s=%s</code>｜<code>%s</code>｜" % (esc(shown), esc(text), esc(text))
    if approx == "sci":
        line += "\n<i>≈ 数值过大或过小，已用科学计数法表示</i>"
    elif approx:
        line += "\n<i>≈ 已四舍五入到 %d 位小数</i>" % st["decimals"]
    msgs = [(line, None)]   # 结果不带按钮，设置走 /calc 菜单
    # 结果转换单独发一条，「前缀」写在 code 外面，点击只复制内容本身
    if st["conv_on"]:
        tail = []
        try:
            if st["conv_mode"] in ("read", "both"):
                tail.append(u"自然读法：<code>%s</code>" % esc(cn_reading(value)))
            if st["conv_mode"] in ("acct", "both"):
                tail.append(u"会计大写：<code>%s</code>" % esc(cn_accounting(value)))
        except Exception:  # noqa: BLE001  中文转换出错不能影响主结果
            pass
        if tail:
            # 两条之间空一行：紧挨着的时候读法和会计大写容易看串（用户反馈）
            msgs.append(("\n\n".join(tail), None))
    return msgs


def format_result(raw):
    """兼容旧接口：把所有消息拼成一段文本。"""
    return "\n".join(t for t, _kb in calc_msgs(raw))


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def calc(raw):
    """返回给用户的一行结果；出错抛 CalcError。"""
    return format_result(raw)


# ---------------------------------------------------------------------------
# 设置面板（Telegram 内联按钮版）
# ---------------------------------------------------------------------------

def _tag(label, selected):
    """选中的选项后面挂一个绿色圆点 🟢。"""
    return u"%s 🟢" % label if selected else label


def settings_panel():
    """设置面板 -> (HTML 文本, 内联键盘)。"""
    s = get_settings()
    conv_txt = u"开启" if s["conv_on"] else u"关闭"
    ans_on = bool(s.get("ans_on"))
    prev = get_ans()
    if not ans_on:
        ans_txt = u"关闭"
    elif prev is None:
        ans_txt = (u"开启（暂无记录 · /00 退出）" if not s.get("ans")
                   else u"开启（已超时 · /00 退出）")
    else:
        ans_txt = u"开启 · 上次 %s · /00 退出" % format_value(prev)[0]
    text = (
        u"⚙️ <b>计算器设置</b>\n\n"
        u"1️⃣ <b>小数位保留</b>（当前 <b>%d</b> 位）\n"
        u"2️⃣ <b>结果显示格式</b>（当前：%s）\n"
        u"3️⃣ <b>结果转换</b>（%s · %s）\n"
        u"4️⃣ <b>连续计算</b>（%s）\n\n"
        u"<i>点选项立即生效并保存；点「收起」关闭面板。</i>"
        % (s["decimals"], FMT_LABEL[s["fmt"]], conv_txt, CONV_LABEL[s["conv_mode"]],
           ans_txt)
    )
    kb = [
        # 小数位 6 档拆两行（3+3），否则勾选标记会把按钮挤到被 Telegram 截断
        [{"text": _tag(u"%d 位" % d, s["decimals"] == d),
          "callback_data": "calcset:dec:%d" % d} for d in DECIMAL_CHOICES[:3]],
        [{"text": _tag(u"%d 位" % d, s["decimals"] == d),
          "callback_data": "calcset:dec:%d" % d} for d in DECIMAL_CHOICES[3:]],
        # 显示格式拆两行：长短按钮分开排，长选项独占一行
        [{"text": _tag(FMT_LABEL[f], s["fmt"] == f),
          "callback_data": "calcset:fmt:%s" % f} for f in FMT_ORDER[:2]],
        [{"text": _tag(FMT_LABEL[f], s["fmt"] == f),
          "callback_data": "calcset:fmt:%s" % f} for f in FMT_ORDER[2:]],
        [{"text": _tag(u"转换：开", s["conv_on"]) if s["conv_on"] else u"转换：关",
          "callback_data": "calcset:conv:toggle"}],
    ]
    if s["conv_on"]:
        # 「两种都显示」时自然读法和会计大写都算选中
        _both = (s["conv_mode"] == "both")
        kb.append([{"text": _tag(CONV_LABEL[m], _both or s["conv_mode"] == m),
                    "callback_data": "calcset:cmode:%s" % m} for m in CONV_ORDER[:2]])
        kb.append([{"text": _tag(CONV_LABEL[m], _both or s["conv_mode"] == m),
                    "callback_data": "calcset:cmode:%s" % m} for m in CONV_ORDER[2:]])
    # 连续计算：开关一行，开启时多一行「清除记录」
    kb.append([{"text": _tag(u"连续计算：开", ans_on) if ans_on else u"连续计算：关",
                "callback_data": "calcset:ans:toggle"}])
    if ans_on:
        kb.append([{"text": u"🧹 清除上次结果", "callback_data": "calcset:ans:clear"}])
    kb.append([{"text": u"❌ 收起", "callback_data": "calcset:close"}])
    return text, kb


def handle_cb(data):
    """处理 calcset:* 回调 -> {"text","kb","alert"} 或 {"close":True}。"""
    parts = data.split(":")
    s = get_settings()
    if len(parts) >= 2 and parts[1] == "close":
        return {"close": True}
    if len(parts) >= 2 and parts[1] == "open":
        return dict(zip(("text", "kb"), settings_panel()))
    if len(parts) >= 3 and parts[1] == "dec":
        n = int(parts[2])
        if n not in DECIMAL_CHOICES:
            raise CalcError("只支持 1~6 位")
        s = set_settings(decimals=n)
        alert = u"小数保留 %d 位" % n
    elif len(parts) >= 3 and parts[1] == "fmt":
        m = parts[2]
        if m not in FMT_ORDER:
            raise CalcError("未知格式")
        s = set_settings(fmt=m)
        alert = u"格式：%s" % FMT_LABEL[m]
    elif len(parts) >= 3 and parts[1] == "conv" and parts[2] == "toggle":
        s = set_settings(conv_on=(not s["conv_on"]))
        alert = u"转换已%s" % (u"开启" if s["conv_on"] else u"关闭")
    elif len(parts) >= 3 and parts[1] == "cmode":
        m = parts[2]
        if m not in CONV_ORDER:
            raise CalcError("未知转换方式")
        s = set_settings(conv_mode=m, conv_on=True)
        alert = u"转换：%s" % CONV_LABEL[m]
    elif len(parts) >= 3 and parts[1] == "ans" and parts[2] == "toggle":
        new_on = not bool(s.get("ans_on"))
        s = set_settings(ans_on=new_on)
        if not new_on:
            clear_ans()                       # 关掉时顺手清掉记录
        alert = u"连续计算已%s" % (u"开启，发 +3 即上次结果+3" if new_on else u"关闭")
    elif len(parts) >= 3 and parts[1] == "ans" and parts[2] == "clear":
        clear_ans()
        alert = u"已清除上次结果"
    else:
        raise CalcError("未知设置操作")
    text, kb = settings_panel()
    return {"text": text, "kb": kb, "alert": alert}


if __name__ == "__main__":
    import sys
    for line in (sys.argv[1:] or ["66*98"]):
        try:
            print(line, "->", calc(line))
        except CalcError as e:
            print(line, "-> ERR:", e)
