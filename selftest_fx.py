# -*- coding: utf-8 -*-
"""fx（汇率）模块自测 —— 离线跑，不打网络。

跑法：python3 selftest_fx.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules.fx import engine as fx  # noqa: E402
from modules import fx as fx_mod     # noqa: E402

# 假汇率（USD 基准）
RATES = {"USD": 1.0, "CNY": 7.12, "EUR": 0.92, "HKD": 7.81,
         "JPY": 149.3, "KRW": 1345.2, "GBP": 0.79, "TRY": 34.2}

_pass = 0
_fail = 0


def check(name, got, want):
    global _pass, _fail
    if got == want:
        _pass += 1
    else:
        _fail += 1
        print(u"  ✗ %s\n      得到 %r\n      期望 %r" % (name, got, want))


def check_true(name, cond):
    global _pass, _fail
    if cond:
        _pass += 1
    else:
        _fail += 1
        print(u"  ✗ %s（条件不成立）" % name)


print(u"── 1. 解析：中文/符号/代码")
check("100美元", fx.parse_query(u"100美元"), (100.0, "USD", None, True))
check("100美元 人民币", fx.parse_query(u"100美元 人民币"), (100.0, "USD", "CNY", True))
check("100欧元 换 人民币（欧元必须整词替换，不能拆成 欧+元）",
      fx.parse_query(u"100欧元 换 人民币"), (100.0, "EUR", "CNY", True))
check("$100", fx.parse_query(u"$100"), (100.0, "USD", None, True))
check("100 usd cny", fx.parse_query("100 usd cny"), (100.0, "USD", "CNY", True))
check("100usd", fx.parse_query("100usd"), (100.0, "USD", None, True))
check("100 USD（大写）", fx.parse_query("100 USD"), (100.0, "USD", None, True))
check("usd cny（无金额）", fx.parse_query("usd cny"), (1.0, "USD", "CNY", False))
check("全角数字", fx.parse_query(u"１００美元"), (100.0, "USD", None, True))
check("千分位", fx.parse_query("1,500 usd"), (1500.0, "USD", None, True))
check("国家名带金额", fx.parse_query(u"66新加坡"), (66.0, "SGD", None, True))
check("国家名带单位后缀", fx.parse_query(u"100新加坡元"), (100.0, "SGD", None, True))
check("日本带金额", fx.parse_query(u"100日本"), (100.0, "JPY", None, True))
check("澳大利亚带金额", fx.parse_query(u"100澳大利亚"), (100.0, "AUD", None, True))
# 国家名不带金额：解析得出结果但 used_alias=False，on_message 会保持沉默
_r = fx.parse_query(u"新加坡")
check_true("纯国家名 used_alias=False（守卫会拒）", _r is not None and _r[3] is False)
check("闲聊不误伤", fx.parse_query(u"我去新加坡"), None)
check("闲聊不误伤2", fx.parse_query(u"今天去日本"), None)

print(u"── 17. 拼音缩写")
check("100zgmg（中国→美国）", fx.parse_query("100zgmg"), (100.0, "CNY", "USD", True))
check("100zgrb（中国→日本）", fx.parse_query("100zgrb"), (100.0, "CNY", "JPY", True))
check("100myoy（美元→欧元）", fx.parse_query("100myoy"), (100.0, "USD", "EUR", True))
check("oz=欧洲", fx.parse_query("100oz"), (100.0, "EUR", None, True))
check("oz组合", fx.parse_query("100ozmg"), (100.0, "EUR", "USD", True))
check("意大利→欧元", fx.parse_query(u"100意大利"), (100.0, "EUR", None, True))
check("ydl=意大利", fx.parse_query("100ydl"), (100.0, "EUR", None, True))
check("克罗地亚→欧元", fx.parse_query(u"100克罗地亚"), (100.0, "EUR", None, True))
check("马耳他→欧元", fx.parse_query(u"100马耳他"), (100.0, "EUR", None, True))
check("卢森堡→欧元", fx.parse_query(u"100卢森堡"), (100.0, "EUR", None, True))
check("非欧元区不受影响（波兰）", fx.parse_query(u"100波兰"), (100.0, "PLN", None, True))
check("非欧元区不受影响（英国）", fx.parse_query(u"100英国"), (100.0, "GBP", None, True))
check("100adly（澳大利亚）", fx.parse_query("100adly"), (100.0, "AUD", None, True))
_r = fx.parse_query("zgmg")
check_true("拼音无金额 used_alias=False（守卫拒）", _r is not None and _r[3] is False)
check("recognize 拼音", fx.recognize("zg mg rb")[0], ["CNY", "USD", "JPY"])
check("recognize 拼音混合", fx.recognize("xjp 美金")[0], ["SGD", "USD"])
check("小数", fx.parse_query("99.5 美元"), (99.5, "USD", None, True))
check("美元→人民币", fx.parse_query(u"美元 人民币"), (1.0, "USD", "CNY", True))
check("ISO hk", fx.parse_query("100hk"), (100.0, "HKD", None, True))
check("ISO us", fx.parse_query("100us"), (100.0, "USD", None, True))
check("ISO 粘连 hk+cny", fx.parse_query("100hkcny"), (100.0, "HKD", "CNY", True))
check("gb 拼音优先=港币（ISO 让位）", fx.parse_query("100gb"), (100.0, "HKD", None, True))
check("hk$ 符号", fx.parse_query(u"500hk$"), (500.0, "HKD", None, True))
check("多目标 1mjrbxjpcny", fx.parse_query("1mjrbxjpcny"),
      (1.0, "USD", ["JPY", "SGD", "CNY"], True))
check("多目标中文", fx.parse_query(u"100美元 日本 新加坡"), (100.0, "USD", ["JPY", "SGD"], True))
check("多目标超 6 个拒", fx.parse_query("1usdcnyjpyeurgbphkdkrw"), None)

print(u"── 2. 解析：不该匹配的（返回 None，保持沉默）")
for bad in [u"hello", u"66*98", u"100", u"", u"你好", u"今天天气不错",
            u"我有一百块钱的预算但是不知道够不够用呢"]:
    check(u"不匹配 %r" % bad, fx.parse_query(bad), None)
# try again：ISO 码 in 会把 again 切开凑出假代码，但守卫（used_alias=False + 无金额）会拒
_r = fx.parse_query("try again")
check_true("try again 守卫会拒（used_alias=False + amount=1）",
           _r is None or (_r[3] is False and _r[0] == 1.0))

print(u"── 3. 换算数学")
check("100 USD→CNY", round(fx.convert(100, "USD", "CNY", RATES), 2), 712.0)
check("100 CNY→USD", round(fx.convert(100, "CNY", "USD", RATES), 4), 14.0449)
check("712 CNY→USD 还原", round(fx.convert(712, "CNY", "USD", RATES), 3), 100.0)
check("1 USD→JPY", fx.convert(1, "USD", "JPY", RATES), 149.3)
check("1000 JPY→CNY", round(fx.convert(1000, "JPY", "CNY", RATES), 2), 47.69)

print(u"── 4. 币种不存在 → KeyError")
try:
    fx.convert(1, "XXX", "CNY", RATES)
    check_true("未知币种抛 KeyError", False)
except KeyError:
    check_true("未知币种抛 KeyError", True)

print(u"── 5. 格式化")
check("fmt_amt 大数", fx.fmt_amt(71234.5678), "71,234.57")
check("fmt_amt 小数", fx.fmt_amt(712.0), "712.00")
check("fmt_rate 常规", fx.fmt_rate(7.123456), "7.1235")
check("fmt_rate 大汇率", fx.fmt_rate(149.32), "149.32")
check("fmt_rate 小汇率", fx.fmt_rate(0.00692), "0.00692")

print(u"── 6. 中文名")
check("USD", fx.cn_name("USD"), u"美元")
check("BRL（在表里）", fx.cn_name("BRL"), u"巴西雷亚尔")
check("XYZ（不在表里，回退代码）", fx.cn_name("XYZ"), "XYZ")

print(u"── 7. 缓存读写（临时目录）")
tmpd = tempfile.mkdtemp()
fx._CACHE_FILE = os.path.join(tmpd, "rates.json")
fake = {"rates": RATES, "ts": 1, "src": "test", "fetched_at": 10**12}   # fetched_at 在未来 → 永不过期
with open(fx._CACHE_FILE, "w") as f:
    json.dump(fake, f)
data = fx.load_rates()
check_true("命中缓存（不打网络）", data is not None and data["src"] == "test")
check("缓存里的汇率可用", round(data["rates"]["CNY"], 2), 7.12)

print(u"── 8. known_codes / 建议")
ks = fx.known_codes({"rates": RATES})
check_true("别名代码在集合里", "USD" in ks and "CNY" in ks)
check_true("API 代码也在集合里", "TRY" in ks)
sug = fx_mod._suggest("USDT", ks)
check_true("建议以相同字母开头", all(c.startswith("U") for c in sug))


print(u"── 9. 设置 v2（迁移与往返）")
tmpd = tempfile.mkdtemp()
fx.SETTINGS_FILE = os.path.join(tmpd, "fx_settings.json")
# v1 旧格式自动升级
with open(fx.SETTINGS_FILE, "w") as f:
    json.dump({"target": "CNY"}, f)
st = fx.get_settings()
check("v1→v2 target 保留", st["target"], "CNY")
check("v1→v2 display 缺省为空（用户自己勾选）", st["display"], [])
# 清空勾选必须保持空（之前 get_settings 会把空列表回退成默认值 —— 这正是用户报的 bug）
st["display"] = []
fx.save_settings(st)
check("清空后保持空", fx.get_settings()["display"], [])
st["display"] = ["USD", "JPY"]
check("v1→v2 apis 默认空", st["apis"], [])
check("v1→v2 active_api 默认内置", st["active_api"], "")
# 改后保存再读（往返）
st["display"] = ["USD", "JPY"]
st["apis"] = [{"id": "api1", "name": u"我的", "url": "https://x/{base}", "key": "K"}]
st["active_api"] = "api1"
fx.save_settings(st)
st2 = fx.get_settings()
check("display 往返", st2["display"], ["USD", "JPY"])
check("apis 往返", st2["apis"][0]["url"], "https://x/{base}")
check("active_api 往返", st2["active_api"], "api1")

print(u"── 10. new_api 校验")
try:
    fx.new_api(u"坏的", "https://x.com/latest")
    check_true("缺 {base} 必须报错", False)
except ValueError:
    check_true("缺 {base} 必须报错", True)
api = fx.new_api(u"我的", "https://x.com/latest/{base}?k={key}", "K9")
check("url 保留 {base}", "{base}" in api["url"], True)
check("key 保存", api["key"], "K9")

print(u"── 11. 自定义 API 拉取（mock urlopen）")
import unittest.mock as mock
fake_json = json.dumps({"rates": {"USD": 1.0, "CNY": 6.66, "EUR": 0.9}}).encode()
class FakeResp:
    def __init__(self, b): self._b = b
    def read(self): return self._b
    def __enter__(self): return self
    def __exit__(self, *a): return False
with mock.patch("urllib.request.urlopen", return_value=FakeResp(fake_json)) as m:
    out = fx.fetch_custom(api)
check_true("自定义 API 解析", out is not None and out["rates"]["CNY"] == 6.66)
check("src 用 API 名字", out["src"], u"我的")
with mock.patch("urllib.request.urlopen", side_effect=Exception("断网")):
    check("拉取失败返回 None", fx.fetch_custom(api), None)
# fastforex 用 results 字段而不是 rates
fake_ff = json.dumps({"base": "USD", "results": {"CNY": 6.66, "EUR": 0.9}}).encode()
with mock.patch("urllib.request.urlopen", return_value=FakeResp(fake_ff)):
    out = fx.fetch_custom(api)
check_true("fastforex results 字段也认", out is not None and out["rates"]["CNY"] == 6.66)

print(u"── 12. 分页与全量代码表")
codes = ["AAA", "BBB", "CCC"] * 12   # 36 个
page, total = fx.page_slice(codes, 0, 24)
check("第 1 页数量", len(page), 24)
check("总页数", total, 2)
page, total = fx.page_slice(codes, 99, 24)   # 越界夹回
check("越界夹回最后页", len(page), 12)
check("越界夹回页数", total, 2)
allc = fx.all_codes({"rates": RATES})
check_true("all_codes 含别名与API代码", "USD" in allc and "TRY" in allc)
check("all_codes 按流行度排（美元在前）", allc[:5], ["USD", "EUR", "GBP", "JPY", "CNY"])
check_true("流行表外的按字母", allc == sorted(allc, key=lambda c: (
    {x: i for i, x in enumerate(fx._POPULAR)}.get(c, 999), c)))

print(u"── 13. 多币种排版输出（_fmt_multi）")
tmpd = tempfile.mkdtemp()
fx.SETTINGS_FILE = os.path.join(tmpd, "fx_settings.json")
st = {"target": "CNY", "display": ["USD", "EUR", "JPY"], "apis": [], "active_api": ""}
with open(fx.SETTINGS_FILE, "w") as f:
    json.dump(st, f)
from modules import fx as fx_mod
text, multi = fx_mod._fmt_multi(22, "CNY", {"rates": RATES, "src": "test"})
check_true("返回多币种", multi)
check_true("含 1 个源金额 + 3 行换算", text.count("<code>") == 4)
check_true("含国旗", "🇺🇸" in text)
check_true("源币种不出现在展示里", "USD（CNY" not in text)
# 勾选的展示货币就是源币种 → 回落单出
st["display"] = ["CNY"]
with open(fx.SETTINGS_FILE, "w") as f:
    json.dump(st, f)
text2, multi2 = fx_mod._fmt_multi(22, "CNY", {"rates": RATES, "src": "test"})
check_true("源币=展示币时回落单出", not multi2)

print(u"── 14. 自定义源切换后 load_rates 用新源")
fx.SETTINGS_FILE = os.path.join(tmpd, "fx_settings.json")
fx._CACHE_FILE = os.path.join(tmpd, "fx_rates.json")
st = {"target": "CNY", "display": ["USD"], "active_api": "api1",
      "apis": [{"id": "api1", "name": u"我的", "url": "https://x/{base}", "key": ""}]}
with open(fx.SETTINGS_FILE, "w") as f:
    json.dump(st, f)
with mock.patch("urllib.request.urlopen", return_value=FakeResp(fake_json)):
    data = fx.load_rates(force=True)
check_true("走自定义源", data is not None and data.get("api") == "api1")
check("汇率来自自定义源", data["rates"]["CNY"], 6.66)

print(u"── 15. 货币识别（直接输入选择）")
check("美金人民币日元澳大利亚印度", fx.recognize(u"美金人民币日元澳大利亚印度")[0],
      ["USD", "CNY", "JPY", "AUD", "INR"])
check("usd 欧元 日本", fx.recognize(u"usd 欧元 日本")[0], ["USD", "EUR", "JPY"])
check("美利坚合众国 英国", fx.recognize(u"美利坚合众国 英国")[0], ["USD", "GBP"])
check("澳大利亚元（元是后缀不加 CNY）", fx.recognize(u"澳大利亚元"), (["AUD"], [], []))
check("国家名", fx.recognize(u"澳洲 新西兰")[0], ["AUD", "NZD"])
f, nf, _fz = fx.recognize(u"火星币 美元 xyz123")
check("识别+未识别分开", (f, sorted(nf)), (["USD"], sorted([u"火星币", "xyz123"])))
check("逗号分隔", fx.recognize("usd,eur,jpy")[0], ["USD", "EUR", "JPY"])
check("空串", fx.recognize(""), ([], [], []))

print(u"── 16. 模糊匹配与地区名")
check("新家坡（错别字）", fx.recognize(u"新家坡")[0], ["SGD"])
check("模糊命中记录", fx.recognize(u"新家坡")[2], [(u"新家坡", "SGD", u"新加坡")])
check("澳州（流行度决胜）", fx.recognize(u"澳州")[0], ["AUD"])
check("欧洲→欧元", fx.recognize(u"欧洲")[0], ["EUR"])
check("欧盟→欧元", fx.recognize(u"欧盟")[0], ["EUR"])
check("usdd（打错码）", fx.recognize("usdd")[0], ["USD"])
check("新家波（差 2 个字不认）", fx.recognize(u"新家波")[0], [])
check("火星币（真不认识）", fx.recognize(u"火星币")[0], [])

print(u"── 18. 计算器联动")
check("calc_value 1+1", fx.calc_value("1+1"), 2)
check("1+1mj", fx.parse_query_ex("1+1mj"),
      {"amount": 2.0, "frm": "USD", "to": None, "used_alias": True, "expr": "1+1"})
check("100*2usd eur", fx.parse_query_ex("100*2usd eur"),
      {"amount": 200.0, "frm": "USD", "to": "EUR", "used_alias": True, "expr": "100*2"})
check("(50+50)人民币", fx.parse_query_ex(u"(50+50)人民币"),
      {"amount": 100.0, "frm": "CNY", "to": None, "used_alias": True, "expr": "(50+50)"})
check("纯数字 expr=None", fx.parse_query_ex("100美元")["expr"], None)
check("坏算式不崩", fx.parse_query_ex("(1+usd"), None)

print()
print("=" * 50)

if _fail == 0:
    print(u"通过 %d，失败 0\n全部通过 ✅" % _pass)
    sys.exit(0)
print(u"通过 %d，失败 %d" % (_pass, _fail))
sys.exit(1)
