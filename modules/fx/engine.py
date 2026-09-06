# -*- coding: utf-8 -*-
"""汇率换算核心 —— 不依赖框架，可单独跑自测（selftest_fx.py）。

数据源（都免费、无 key、汇率以 USD 为基准）：
  内置主源：open.er-api.com（160+ 币种，每日更新）
  内置备用：api.frankfurter.app（欧央行，主流币种）
  自定义：用户自己加的 API（地址里用 {base} 占位、可用 {key} 放密钥）
跨币换算：amount / rates[frm] * rates[to]（rates 里 USD=1）。

设计要点：
  - 别名表用「最长优先」替换（"美元" 必须先于 "元"，否则 100欧元 会变成 100欧+元）。
  - on_message 自动触发有门槛（见 fx/__init__.py）：纯三字码不带金额的不回，
    否则 "try again" 会被当成土耳其里拉。
  - 汇率缓存 1 小时（源本身一天才更新一次），按当前生效的 API 分开存。
  - 设置 v2：target（默认目标币）+ display（换算结果展示哪些货币）+
    apis（自定义源列表）+ active_api（当前生效的源，"" 表示内置）。
"""
import json
import os
import re
import time
import urllib.request

# ---------------------------------------------------------------- 常量
CACHE_TTL = 3600          # 汇率缓存 1 小时
PICKER_PAGE = 24          # 货币选择页每页个数（4 列 × 6 行，按钮不超宽）

# 内置汇率源（免费、无 key，用户可切换，默认 erapi）。
# parse 标记各自的 JSON 解析方式：erapi=顶层 rates；frankfurter=rates+补 USD=1；
# jsdelivr=usd 字段且小写键转大写。
BUILTIN_APIS = [
    {"id": "erapi", "name": "open.er-api.com", "parse": "erapi",
     "url": "https://open.er-api.com/v6/latest/USD",
     "desc": u"默认 · 160+ 币种 · 每日更新"},
    {"id": "frankfurter", "name": "frankfurter.app", "parse": "frankfurter",
     "url": "https://api.frankfurter.app/latest?from=USD",
     "desc": u"欧央行官方 · 30+ 主流币种"},
    {"id": "jsdelivr", "name": "currency-api", "parse": "jsdelivr",
     "url": "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json",
     "desc": u"CDN 加速 · 200+ 币种 · 每日更新"},
    {"id": "v4", "name": "exchangerate-api v4", "parse": "erapi",
     "url": "https://api.exchangerate-api.com/v4/latest/USD",
     "desc": u"exchangerate-api 免费版 · 160+ 币种"},
]
_DEFAULT_SOURCE = "erapi"

# ISO 4217 全表：货币代码 → (国家码, 中文名)。
# 国旗按 ISO 3166 国家码自动生成（两位国家码 → 区域指示符），不用手维护。
# 国家码为 "" 的是区域性货币（欧元有 EU 算例外），不显示旗子。
_COUNTRY = {
    "AED": ("AE", u"阿联酋迪拉姆"), "AFN": ("AF", u"阿富汗尼"),
    "ALL": ("AL", u"阿尔巴尼亚列克"), "AMD": ("AM", u"亚美尼亚德拉姆"),
    "ANG": ("CW", u"荷属安的列斯盾"), "AOA": ("AO", u"安哥拉宽扎"),
    "ARS": ("AR", u"阿根廷比索"), "AUD": ("AU", u"澳元"),
    "AWG": ("AW", u"阿鲁巴盾"), "AZN": ("AZ", u"阿塞拜疆马纳特"),
    "BAM": ("BA", u"波黑马克"), "BBD": ("BB", u"巴巴多斯元"),
    "BDT": ("BD", u"孟加拉塔卡"), "BGN": ("BG", u"保加利亚列弗"),
    "BHD": ("BH", u"巴林第纳尔"), "BIF": ("BI", u"布隆迪法郎"),
    "BMD": ("BM", u"百慕大元"), "BND": ("BN", u"文莱元"),
    "BOB": ("BO", u"玻利维亚诺"), "BRL": ("BR", u"巴西雷亚尔"),
    "BSD": ("BS", u"巴哈马元"), "BTN": ("BT", u"不丹努扎姆"),
    "BWP": ("BW", u"博茨瓦纳普拉"), "BYN": ("BY", u"白俄罗斯卢布"),
    "BZD": ("BZ", u"伯利兹元"), "CAD": ("CA", u"加元"),
    "CDF": ("CD", u"刚果法郎"), "CHF": ("CH", u"瑞士法郎"),
    "CLP": ("CL", u"智利比索"), "CNY": ("CN", u"人民币"),
    "COP": ("CO", u"哥伦比亚比索"), "CRC": ("CR", u"哥斯达黎加科朗"),
    "CUP": ("CU", u"古巴比索"), "CVE": ("CV", u"佛得角埃斯库多"),
    "CLF": ("CL", u"智利发展单位"), "CNH": ("CN", u"离岸人民币"),
    "CZK": ("CZ", u"捷克克朗"), "DJF": ("DJ", u"吉布提法郎"),
    "DKK": ("DK", u"丹麦克朗"), "DOP": ("DO", u"多米尼加比索"),
    "DZD": ("DZ", u"阿尔及利亚第纳尔"), "EGP": ("EG", u"埃及镑"),
    "ERN": ("ER", u"厄立特里亚纳克法"), "ETB": ("ET", u"埃塞俄比亚比尔"),
    "EUR": ("EU", u"欧元"), "FJD": ("FJ", u"斐济元"),
    "FKP": ("FK", u"福克兰镑"), "FOK": ("FO", u"法罗群岛克朗"),
    "GBP": ("GB", u"英镑"), "GEL": ("GE", u"格鲁吉亚拉里"),
    "GGP": ("GG", u"根西岛镑"), "GHS": ("GH", u"加纳塞地"),
    "GIP": ("GI", u"直布罗陀镑"), "GMD": ("GM", u"冈比亚达拉西"),
    "GNF": ("GN", u"几内亚法郎"), "GTQ": ("GT", u"危地马拉格查尔"),
    "GYD": ("GY", u"圭亚那元"), "HKD": ("HK", u"港币"),
    "HNL": ("HN", u"洪都拉斯伦皮拉"), "HRK": ("HR", u"克罗地亚库纳"),
    "HTG": ("HT", u"海地古德"), "HUF": ("HU", u"匈牙利福林"),
    "IDR": ("ID", u"印尼盾"), "ILS": ("IL", u"以色列谢克尔"),
    "IMP": ("IM", u"马恩岛镑"), "INR": ("IN", u"印度卢比"),
    "IQD": ("IQ", u"伊拉克第纳尔"), "IRR": ("IR", u"伊朗里亚尔"),
    "ISK": ("IS", u"冰岛克朗"), "JEP": ("JE", u"泽西岛镑"),
    "JMD": ("JM", u"牙买加元"), "JOD": ("JO", u"约旦第纳尔"),
    "JPY": ("JP", u"日元"), "KES": ("KE", u"肯尼亚先令"),
    "KGS": ("KG", u"吉尔吉斯斯坦索姆"), "KHR": ("KH", u"柬埔寨瑞尔"),
    "KID": ("KI", u"基里巴斯元"), "KMF": ("KM", u"科摩罗法郎"),
    "KRW": ("KR", u"韩元"), "KWD": ("KW", u"科威特第纳尔"),
    "KYD": ("KY", u"开曼群岛元"), "KZT": ("KZ", u"哈萨克斯坦坚戈"),
    "LAK": ("LA", u"老挝基普"), "LBP": ("LB", u"黎巴嫩镑"),
    "LKR": ("LK", u"斯里兰卡卢比"), "LRD": ("LR", u"利比里亚元"),
    "LSL": ("LS", u"莱索托洛蒂"), "LYD": ("LY", u"利比亚第纳尔"),
    "MAD": ("MA", u"摩洛哥迪拉姆"), "MDL": ("MD", u"摩尔多瓦列伊"),
    "MGA": ("MG", u"马达加斯加阿里亚里"), "MKD": ("MK", u"北马其顿第纳尔"),
    "MMK": ("MM", u"缅甸缅元"), "MNT": ("MN", u"蒙古图格里克"),
    "MOP": ("MO", u"澳门元"), "MRU": ("MR", u"毛里塔尼亚乌吉亚"),
    "MUR": ("MU", u"毛里求斯卢比"), "MVR": ("MV", u"马尔代夫拉菲亚"),
    "MWK": ("MW", u"马拉维克瓦查"), "MXN": ("MX", u"墨西哥比索"),
    "MYR": ("MY", u"林吉特"), "MZN": ("MZ", u"莫桑比克梅蒂卡尔"),
    "NAD": ("NA", u"纳米比亚元"), "NGN": ("NG", u"尼日利亚奈拉"),
    "NIO": ("NI", u"尼加拉瓜科多巴"), "NOK": ("NO", u"挪威克朗"),
    "NPR": ("NP", u"尼泊尔卢比"), "NZD": ("NZ", u"新西兰元"),
    "OMR": ("OM", u"阿曼里亚尔"), "PAB": ("PA", u"巴拿马巴波亚"),
    "PEN": ("PE", u"秘鲁索尔"), "PGK": ("PG", u"巴布亚新几内亚基那"),
    "PHP": ("PH", u"菲律宾比索"), "PKR": ("PK", u"巴基斯坦卢比"),
    "PLN": ("PL", u"波兰兹罗提"), "PYG": ("PY", u"巴拉圭瓜拉尼"),
    "QAR": ("QA", u"卡塔尔里亚尔"), "RON": ("RO", u"罗马尼亚列伊"),
    "RSD": ("RS", u"塞尔维亚第纳尔"), "RUB": ("RU", u"卢布"),
    "RWF": ("RW", u"卢旺达法郎"), "SAR": ("SA", u"沙特里亚尔"),
    "SBD": ("SB", u"所罗门群岛元"), "SCR": ("SC", u"塞舌尔卢比"),
    "SDG": ("SD", u"苏丹镑"), "SEK": ("SE", u"瑞典克朗"),
    "SGD": ("SG", u"新加坡元"), "SHP": ("SH", u"圣赫勒拿镑"),
    "SLE": ("SL", u"塞拉利昂利昂"), "SLL": ("SL", u"塞拉利昂利昂"),
    "SOS": ("SO", u"索马里先令"), "SRD": ("SR", u"苏里南元"),
    "SSP": ("SS", u"南苏丹镑"), "STN": ("ST", u"圣多美多布拉"),
    "SYP": ("SY", u"叙利亚镑"), "SZL": ("SZ", u"斯威士兰里兰吉尼"),
    "THB": ("TH", u"泰铢"), "TJS": ("TJ", u"塔吉克斯坦索莫尼"),
    "TMT": ("TM", u"土库曼斯坦马纳特"), "TND": ("TN", u"突尼斯第纳尔"),
    "TOP": ("TO", u"汤加潘加"), "TRY": ("TR", u"土耳其里拉"),
    "TTD": ("TT", u"特立尼达和多巴哥元"), "TVD": ("TV", u"图瓦卢元"),
    "TWD": ("TW", u"新台币"), "TZS": ("TZ", u"坦桑尼亚先令"),
    "UAH": ("UA", u"乌克兰格里夫纳"), "UGX": ("UG", u"乌干达先令"),
    "USD": ("US", u"美元"), "UYU": ("UY", u"乌拉圭比索"),
    "UZS": ("UZ", u"乌兹别克斯坦苏姆"), "VES": ("VE", u"委内瑞拉玻利瓦尔"),
    "VND": ("VN", u"越南盾"), "VUV": ("VU", u"瓦努阿图瓦图"),
    "WST": ("WS", u"萨摩亚塔拉"), "XAF": ("", u"中非法郎"),
    "XCD": ("", u"东加勒比元"), "XCG": ("CW", u"加勒比盾"),
    "XDR": ("", u"特别提款权"), "XOF": ("", u"西非法郎"),
    "XPF": ("PF", u"太平洋法郎"), "YER": ("YE", u"也门里亚尔"),
    "ZAR": ("ZA", u"南非兰特"), "ZMW": ("ZM", u"赞比亚克瓦查"),
    "ZWG": ("ZW", u"津巴布韦ZiG"), "ZWL": ("ZW", u"津巴布韦元(旧)"),
}

# 兼容旧接口名（别名表等还在用 CN_NAMES）
CN_NAMES = {c: n for c, (cc, n) in _COUNTRY.items()}

# 按钮短名：全名太长放不下时用它（货币本体名），没列到的按全名截断。
BUTTON_SHORT = {
    "USD": u"美元", "CNY": u"人民币", "EUR": u"欧元", "GBP": u"英镑",
    "JPY": u"日元", "HKD": u"港币", "KRW": u"韩元", "SGD": u"新元",
    "TWD": u"台币", "AUD": u"澳元", "CAD": u"加元", "CHF": u"瑞郎",
    "THB": u"泰铢", "RUB": u"卢布", "INR": u"卢比", "VND": u"越盾",
    "MYR": u"林吉特", "PHP": u"比索", "NZD": u"纽元", "SEK": u"克朗",
    "NOK": u"克朗", "DKK": u"克朗", "MXN": u"比索", "BRL": u"雷亚尔",
    "ZAR": u"兰特", "AED": u"迪拉姆", "SAR": u"里亚尔", "TRY": u"里拉",
    "IDR": u"印尼盾", "PKR": u"卢比", "ILS": u"谢克尔", "PLN": u"兹罗提",
    "MOP": u"澳门元", "AED": u"迪拉姆", "AFN": u"阿富汗尼", "ALL": u"列克",
    "AMD": u"德拉姆", "ANG": u"安的盾", "AOA": u"宽扎", "ARS": u"比索",
    "AZN": u"马纳特", "BAM": u"马克", "BDT": u"塔卡", "BGN": u"列弗",
    "BHD": u"第纳尔", "BWP": u"普拉", "BYN": u"卢布", "CDF": u"法郎",
    "CLP": u"比索", "COP": u"比索", "CRC": u"科朗", "CZK": u"克朗",
    "DZD": u"第纳尔", "EGP": u"埃及镑", "ETB": u"比尔", "GEL": u"拉里",
    "GHS": u"塞地", "GTQ": u"格查尔", "HNL": u"伦皮拉", "HRK": u"库纳",
    "HUF": u"福林", "IQD": u"第纳尔", "IRR": u"里亚尔", "ISK": u"克朗",
    "JOD": u"第纳尔", "KES": u"先令", "KGS": u"索姆", "KHR": u"瑞尔",
    "KWD": u"第纳尔", "KZT": u"坚戈", "LAK": u"基普", "LBP": u"镑",
    "LKR": u"卢比", "LYD": u"第纳尔", "MAD": u"迪拉姆", "MDL": u"列伊",
    "MGA": u"阿里亚", "MKD": u"第纳尔", "MMK": u"缅元", "MNT": u"图格里",
    "MRU": u"乌吉亚", "MUR": u"卢比", "MVR": u"拉菲亚", "MWK": u"瓦查",
    "MZN": u"梅蒂卡", "NAD": u"纳元", "NGN": u"奈拉", "NIO": u"科多巴",
    "NPR": u"卢比", "OMR": u"里亚尔", "PAB": u"巴波亚", "PEN": u"索尔",
    "PGK": u"基那", "PYG": u"瓜拉尼", "QAR": u"里亚尔", "RON": u"列伊",
    "RSD": u"第纳尔", "RWF": u"法郎", "SDG": u"苏丹镑", "SOS": u"先令",
    "SRD": u"苏里南", "SSP": u"南苏丹", "STN": u"多布拉", "SYP": u"叙镑",
    "SZL": u"里兰吉", "TJS": u"索莫尼", "TMT": u"马纳特", "TND": u"第纳尔",
    "TOP": u"潘加", "TTD": u"特元", "TZS": u"先令", "UAH": u"格里夫",
    "UGX": u"先令", "UYU": u"比索", "UZS": u"苏姆", "VES": u"玻利瓦",
    "VUV": u"瓦图", "WST": u"塔拉", "XAF": u"中非法郎", "XCD": u"东加元",
    "XCG": u"加勒比", "XDR": u"提款权", "XOF": u"西非法郎", "XPF": u"太平洋",
    "YER": u"里亚尔", "ZMW": u"克瓦查", "ZWG": u"ZiG",
}
FLAGS = {}


def _flag_from_cc(cc):
    """两位国家码 → 国旗 emoji（区域指示符）。"""
    if len(cc) != 2:
        return ""
    try:
        return "".join(chr(0x1F1E6 + ord(ch) - ord("A")) for ch in cc)
    except Exception:                       # noqa: BLE001
        return ""


FLAGS = {c: _flag_from_cc(cc) for c, (cc, n) in _COUNTRY.items()}

# 输入别名：写法 → 标准代码。小写键；符号和中文都收。
# 注意 "$" 单独指美元（港元/澳元/加元都有带前缀的写法，放前面先替换）。
_ALIASES = {
    "us$": "USD", "$": "USD", u"美元": "USD", u"美金": "USD", u"刀": "USD", "dollar": "USD",
    u"人民币": "CNY", "rmb": "CNY", u"元": "CNY", u"块": "CNY",
    u"欧元": "EUR", u"€": "EUR",
    u"英镑": "GBP", u"£": "GBP",
    u"日元": "JPY", u"日圆": "JPY", u"円": "JPY",
    u"港币": "HKD", u"港纸": "HKD", "hk$": "HKD",
    u"韩元": "KRW", u"韩币": "KRW",
    u"泰铢": "THB", u"฿": "THB",
    u"卢布": "RUB", u"₽": "RUB",
    u"新台币": "TWD", u"台币": "TWD",
    u"澳元": "AUD", u"澳币": "AUD", "a$": "AUD",
    u"加元": "CAD", "c$": "CAD",
    u"新加坡元": "SGD", u"新币": "SGD",
    u"瑞士法郎": "CHF", u"法郎": "CHF", u"瑞郎": "CHF",
    u"新西兰元": "NZD", u"纽币": "NZD", u"纽元": "NZD",
    u"印度卢比": "INR", u"卢比": "INR",
    u"越南盾": "VND", u"林吉特": "MYR", u"迪拉姆": "AED", u"里拉": "TRY",
}
# 最长优先：替换时先长后短（美元/欧元 都含 "元"，必须先吃掉长的）
_ALIAS_SORTED = sorted(_ALIASES, key=len, reverse=True)

# 静态已知代码 = 别名目标的并集（用于无金额时判断要不要响应）
_ALIAS_CODES = set(_ALIASES.values())

_FULLWIDTH = {ord(f): ord(t) for f, t in zip(u"０１２３４５６７８９．，", u"0123456789.,")}
_SEP_RE = re.compile(u"[换到至→= ]+")         # 分隔词统一当空格（/ 除外：除法要用）
# / 和 ／ 只在独立成 token 时当分隔符（"usd/cny"），夹数字里的是除法（"66*9/8"）

_CACHE_FILE = ""          # 由框架侧指向 DATA_DIR/fx_rates.json
SETTINGS_FILE = ""        # 由框架侧指向 DATA_DIR/fx_settings.json

_DEFAULT_TARGET = "CNY"
_DEFAULT_DISPLAY = ["USD", "EUR", "HKD", "JPY", "KRW"]


# ---------------------------------------------------------------- 设置 v2
def _read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:                       # noqa: BLE001
        return None


def get_settings():
    """读全部设置；缺的项补默认值（v1 的 {"target": ...} 自动升级成 v2）。

    v2 结构：
      target     默认目标币（字符串）
      display    换算结果展示哪些货币（列表；不含时按 target 单出）
      apis       自定义汇率源列表 [{id,name,url,key}]
      active_api 当前生效的源 id（"" 表示内置）
    """
    d = _read_json(SETTINGS_FILE) or {}
    # display 要用「键是否存在」判断：空列表是用户刻意清空的，不能回退成默认值
    return {
        "target": d.get("target", _DEFAULT_TARGET),
        "display": d["display"] if "display" in d else [],
        # 内置源 id（v3）。旧的自定义 apis/active_api 模型已废弃，忽略。
        "source": d.get("source", _DEFAULT_SOURCE),
    }


def save_settings(st):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(st, f, ensure_ascii=False)
    except Exception:                       # noqa: BLE001
        pass


# ---------------------------------------------------------------- 汇率获取
def _fetch_source(api):
    """按内置源拉汇率，按各自的 JSON 结构解析。失败返回 None。"""
    try:
        with urllib.request.urlopen(api["url"], timeout=10) as r:
            d = json.load(r)
    except Exception:                       # noqa: BLE001
        return None
    kind = api["parse"]
    if kind == "erapi":
        rates = d.get("rates")
        if isinstance(rates, dict) and rates:
            return {"rates": rates,
                    "ts": int(d.get("time_last_update_unix", 0) or time.time()),
                    "src": api["name"]}
    elif kind == "frankfurter":
        rates = d.get("rates")
        if isinstance(rates, dict) and rates:
            rates = dict(rates)
            rates["USD"] = 1.0
            return {"rates": rates, "ts": int(time.time()), "src": api["name"]}
    elif kind == "jsdelivr":
        raw = d.get("usd")
        if isinstance(raw, dict) and raw:
            rates = {k.upper(): v for k, v in raw.items()}
            return {"rates": rates, "ts": int(time.time()), "src": api["name"]}
    return None


def fetch_rates():
    """按当前生效的内置源拉汇率；失败按源顺序挨个回落。"""
    cur = get_settings()["source"]
    apis = sorted(BUILTIN_APIS, key=lambda a: 0 if a["id"] == cur else 1)
    for api in apis:
        data = _fetch_source(api)
        if data:
            return data
    return None


# ---------------------------------------------------------------- 缓存
def load_rates(force=False):
    """带缓存的汇率读取：同一源 1 小时内直接用缓存；换源或过期重新拉。"""
    st = get_settings()
    cur_api = st["source"]
    data = None
    if not force and os.path.isfile(_CACHE_FILE):
        data = _read_json(_CACHE_FILE)
    if data and isinstance(data.get("rates"), dict) and \
            data.get("api", "") == cur_api and \
            time.time() - data.get("fetched_at", 0) < CACHE_TTL:
        return data
    fresh = fetch_rates()
    if fresh:
        fresh["fetched_at"] = int(time.time())
        fresh["api"] = cur_api
        try:
            with open(_CACHE_FILE, "w") as f:
                json.dump(fresh, f)
        except Exception:                   # noqa: BLE001  写不进缓存不影响本次使用
            pass
        return fresh
    # 拉不到就用过期的顶着（同一源的过期数据 > 换源的旧数据）
    if data:
        return data
    return None


# ---------------------------------------------------------------- 解析
def normalize(text):
    """最长优先分词：货币代码/别名/国家名/拼音/ISO码 → " code "，其余原样。

    单趟扫描，不会把刚替换进去的代码再拆坏（旧实现逐别名 replace 会出现
    「cn」撞上「cny」、「dk」撞上「hkd」这类连环错配）。
    """
    t = text.strip().lower().translate(_FULLWIDTH)
    out = []
    i = 0
    n = len(t)
    while i < n:
        for pat, code in _TOKEN_PATTERNS:
            if t.startswith(pat, i):
                out.append(" %s " % code.lower())
                i += len(pat)
                break
        else:
            out.append(t[i])
            i += 1
    return "".join(out)


# ---------------------------------------------------------------- 计算器联动
def calc_value(raw):
    """用计算器的 AST 白名单求值拿数值（联动 calc 模块）。出错返回 None。"""
    try:
        import ast
        from modules.calc import engine as _c
        expr = _c._normalize(raw).replace("^", "**")
        tree = ast.parse(expr, mode="eval")
        return _c._eval(tree, 0)
    except Exception:                       # noqa: BLE001  算不出就当它不是算式
        return None


def _eval_amount(tok):
    """金额 token：纯数字 → (float, None)；算式（如 1+1）→ 求值 (float, 算式原文)。"""
    if re.fullmatch(r"[0-9][0-9,]*(?:\.[0-9]+)?", tok):
        return float(tok.replace(",", "")), None
    if re.fullmatch(r"[0-9(][0-9,+\-*/^%().]*", tok) and re.search(r"[+\-*/^%]", tok):
        v = calc_value(tok)
        if v is not None:
            return float(v), tok
    return None


def parse_query_ex(text):
    """解析一条换算请求（完整版，返回 dict）。

    返回 (amount, frm, to, used_alias) 或 None：
      amount     数额（无数字时为 1.0）
      frm        源币种（三字码）
      to         目标币种：None=按设置展示 / 三字码=单目标 / 列表=多目标
      used_alias 输入里用了中文/符号别名（而不是裸三字码）
    解析失败的（比如 "try again"）返回 None，调用方保持沉默。
    """
    t = normalize(text)
    if not t:
        return None
    t = _SEP_RE.sub(" ", t)
    # 数字和三字码粘在一起的写法（"100usd" / "usd100"）在空格切分前先断开
    t = re.sub(r"(?<=[0-9])(?=[a-z])", " ", t)
    t = re.sub(r"(?<=[a-z])(?=[0-9])", " ", t)
    # 逐 token 扫描：数字出现一次，三字码出现 1~2 次（$100 别名替换后是 "usd 100"，
    # 所以数字可能在代码后面，不能只从行首抓）
    number = None
    expr = None                             # 算式原文（1+1mj 里的 "1+1"）
    codes = []
    for tok in t.split():
        amt = _eval_amount(tok)
        if amt is not None:
            if number is not None:
                return None                 # 两个数字（如 "100 200"）不是换算
            number, expr = amt
        elif re.fullmatch(r"[a-z]{3}", tok):
            codes.append(tok.upper())
        elif tok in (u"元", u"圆"):
            continue                        # 「新加坡元」里剩下的单位后缀
        elif tok in ("/", u"／"):
            continue                        # 独立分隔符（usd/cny）；除法在算式 token 里不受影响
        else:
            return None                     # 4+ 字母的词（如 again）→ 不是汇率查询
    amount = number if number is not None else 1.0
    if not codes or len(codes) > 6:
        return None                         # 光一个数字归计算器管；超 6 个币种太多
    # used_alias：用了货币别名（美元/人民币…）直接算；
    # 只用了国家名（新加坡/澳大利亚…）则必须带金额才算 ——
    # 否则「我去新加坡」会被当成查汇率。
    low = text.strip().lower()
    cur_hit = any(a in low for a in _ALIAS_SORTED)
    country_hit = any(c in low for c in _COUNTRY_NAME)
    pinyin_hit = any(p in low for p in _PINYIN)
    iso_hit = any(p in low for p in _ISO_CC)
    used_alias = cur_hit or ((country_hit or pinyin_hit or iso_hit)
                             and number is not None)
    # 多币种：第 1 个是源，其余全是目标（"1mjrbxjpcny" → 1 USD → JPY/SGD/CNY）
    frm = codes[0]
    if len(codes) == 1:
        to = None
    elif len(codes) == 2:
        to = codes[1]
    else:
        to = codes[1:]
    return {"amount": amount, "frm": frm, "to": to,
            "used_alias": used_alias, "expr": expr}


def parse_query(text):
    """兼容旧接口：返回 (amount, frm, to, used_alias) 或 None。"""
    r = parse_query_ex(text)
    if not r:
        return None
    return (r["amount"], r["frm"], r["to"], r["used_alias"])


# ---------------------------------------------------------------- 国家名识别
# 国家名 → 货币代码（用户在「直接输入」里说国家也能认出来）
_COUNTRY_NAME = {
    u"美利坚合众国": "USD", u"美利坚": "USD", u"美国": "USD",
    u"日本": "JPY", u"韩国": "KRW", u"南韩": "KRW", u"朝鲜": "KPW",
    u"中国": "CNY", u"香港": "HKD", u"澳门": "MOP", u"台湾": "TWD",
    u"英国": "GBP", u"澳大利亚": "AUD", u"澳洲": "AUD", u"加拿大": "CAD",
    u"新西兰": "NZD", u"新加坡": "SGD", u"瑞士": "CHF", u"泰国": "THB",
    u"俄罗斯": "RUB", u"印度": "INR", u"印度尼西亚": "IDR", u"印尼": "IDR",
    u"越南": "VND", u"马来西亚": "MYR", u"菲律宾": "PHP", u"巴西": "BRL",
    u"墨西哥": "MXN", u"南非": "ZAR", u"土耳其": "TRY", u"沙特": "SAR",
    u"阿联酋": "AED", u"以色列": "ILS", u"波兰": "PLN", u"瑞典": "SEK",
    u"挪威": "NOK", u"丹麦": "DKK", u"阿根廷": "ARS", u"智利": "CLP",
    u"哥伦比亚": "COP", u"秘鲁": "PEN", u"乌克兰": "UAH", u"埃及": "EGP",
    u"尼日利亚": "NGN", u"巴基斯坦": "PKR", u"孟加拉": "BDT", u"伊朗": "IRR",
    u"伊拉克": "IQD", u"科威特": "KWD", u"卡塔尔": "QAR", u"约旦": "JOD",
    u"黎巴嫩": "LBP", u"摩洛哥": "MAD", u"阿尔及利亚": "DZD", u"突尼斯": "TND",
    u"利比亚": "LYD", u"古巴": "CUP", u"牙买加": "JMD", u"巴拿马": "PAB",
    u"乌拉圭": "UYU", u"巴拉圭": "PYG", u"玻利维亚": "BOB", u"委内瑞拉": "VES",
    u"冰岛": "ISK", u"格鲁吉亚": "GEL", u"亚美尼亚": "AMD", u"阿塞拜疆": "AZN",
    u"哈萨克斯坦": "KZT", u"乌兹别克斯坦": "UZS", u"吉尔吉斯斯坦": "KGS",
    u"塔吉克斯坦": "TJS", u"土库曼斯坦": "TMT", u"蒙古": "MNT", u"缅甸": "MMK",
    u"柬埔寨": "KHR", u"老挝": "LAK", u"尼泊尔": "NPR", u"斯里兰卡": "LKR",
    u"阿富汗": "AFN", u"也门": "YER", u"叙利亚": "SYP", u"巴林": "BHD",
    u"阿曼": "OMR", u"毛里求斯": "MUR", u"肯尼亚": "KES", u"坦桑尼亚": "TZS",
    u"乌干达": "UGX", u"卢旺达": "RWF", u"埃塞俄比亚": "ETB", u"加纳": "GHS",
    u"罗马尼亚": "RON", u"保加利亚": "BGN", u"克罗地亚": "HRK",
    u"塞尔维亚": "RSD", u"北马其顿": "MKD", u"阿尔巴尼亚": "ALL",
    u"波黑": "BAM", u"摩尔多瓦": "MDL", u"白俄罗斯": "BYN", u"捷克": "CZK",
    u"匈牙利": "HUF",
    u"欧洲": "EUR", u"欧盟": "EUR", u"欧元区": "EUR",
    u"德国": "EUR", u"法国": "EUR",
    u"卢森堡": "EUR", u"塞浦路斯": "EUR", u"爱沙尼亚": "EUR", u"拉脱维亚": "EUR",
    u"立陶宛": "EUR", u"马耳他": "EUR", u"斯洛伐克": "EUR", u"斯洛文尼亚": "EUR",
    u"克罗地亚": "EUR", u"摩纳哥": "EUR", u"梵蒂冈": "EUR", u"圣马力诺": "EUR",
    u"安道尔": "EUR",
    u"意大利": "EUR", u"西班牙": "EUR", u"荷兰": "EUR", u"比利时": "EUR",
    u"奥地利": "EUR", u"葡萄牙": "EUR", u"爱尔兰": "EUR", u"希腊": "EUR",
    u"芬兰": "EUR",
}


# ---------------------------------------------------------------- 模糊匹配
def _edit1(a, b):
    """编辑距离是否恰好为 1（增/删/换一个字符）。用于错别字容错。"""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(1 for x, y in zip(a, b) if x != y) == 1
    if len(a) > len(b):
        a, b = b, a
    i = j = 0
    skipped = False
    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            i += 1
            j += 1
        elif not skipped:
            j += 1
            skipped = True
        else:
            return False
    return True


_FUZZY_MAP = None


def _fuzzy_map():
    """候选写法 → 货币代码（用于错别字模糊匹配）。懒加载。"""
    global _FUZZY_MAP
    if _FUZZY_MAP is None:
        m = {}
        for a, c in _ALIASES.items():
            if len(a) >= 2:
                m.setdefault(a, c)
        for n_, c in _COUNTRY_NAME.items():
            m.setdefault(n_, c)
        for p, c in _PINYIN.items():
            m.setdefault(p, c)
        for p, c in _ISO_CC.items():
            m.setdefault(p, c)
        for c, n_ in CN_NAMES.items():
            m.setdefault(n_, c)
        for c, sh in BUTTON_SHORT.items():
            m.setdefault(sh, c)
        for c in CN_NAMES:                       # 三字码本身也允许打错一个字母
            m.setdefault(c.lower(), c)
        _FUZZY_MAP = m
    return _FUZZY_MAP


def _fuzzy_code(tok):
    """对一个没认出来的 token 做模糊匹配。

    只在候选收敛到「唯一代码」时才认（避免歧义乱配）。
    返回 (code, 匹配到的写法) 或 None。
    """
    if len(tok) < 2:
        return None
    hits = {}
    for pat, code in _fuzzy_map().items():
        if _edit1(tok, pat):
            hits.setdefault(code, []).append(pat)
    if len(hits) == 1:
        code = next(iter(hits))
        return code, hits[code][0]
    if len(hits) > 1:
        # 多候选（如「澳州」既像澳洲又像澳门）→ 用流行度决胜，
        # 结果会标注为模糊匹配展示给用户，错配也看得见
        pop = {c: i for i, c in enumerate(_POPULAR)}
        code = min(hits, key=lambda c: pop.get(c, 999))
        return code, hits[code][0]
    return None


# 拼音缩写：首字母 → 货币代码（zg=中国 mg=美国…）。
# 规则：只收录不与三字码冲突的；触发要求带金额（同国家名，防 "omg" 之类误伤）。
_PINYIN = {
    # 货币名
    "my": "USD", "mj": "USD", "oy": "EUR", "yb": "GBP", "ry": "JPY", "hb": "HKD",
    "gb": "HKD", "sgb": "SGD",
    "hw": "KRW", "tz": "THB", "lb": "RUB", "ady": "AUD", "jy": "CAD",
    "fy": "CHF", "xby": "SGD", "tb": "TWD",
    # 国家名
    "zg": "CNY", "mg": "USD", "rb": "JPY", "hg": "KRW", "yg": "GBP",
    "dg": "EUR", "fg": "EUR", "el": "RUB", "yd": "INR", "ydnxy": "IDR",
    "adly": "AUD", "az": "AUD", "jnd": "CAD", "xxl": "NZD", "xjp": "SGD",
    "rs": "CHF", "tg": "THB", "mlsy": "MYR", "flb": "PHP", "bn": "BRL",
    "mxg": "MXN", "nf": "ZAR", "teq": "TRY", "ysl": "ILS", "alq": "AED",
    "st": "SAR", "rd": "SEK", "nw": "NOK", "dm": "DKK", "bl": "PLN",
    "xg": "HKD", "am": "MOP", "tw": "TWD",
    # 欧洲区（都用欧元）
    "oz": "EUR", "ydl": "EUR", "hl": "EUR", "bls": "EUR", "als": "EUR",
    "xl": "EUR", "fl": "EUR", "lsb": "EUR", "pty": "EUR", "odl": "EUR",
    "slfk": "EUR", "slwn": "EUR", "kld": "EUR", "mte": "EUR",
}

# ISO 3166 两位国家/地区码（hk 香港 us 美国 cn 中国…）。
# 与 _PINYIN 冲突的 3 个不收（my/am/tz 保留拼音优先：美元/澳门/泰铢）。
_ISO_CC = {
    "hk": "HKD", "us": "USD", "cn": "CNY", "jp": "JPY", "kr": "KRW",
    "au": "AUD", "ca": "CAD", "nz": "NZD", "sg": "SGD",
    "ch": "CHF", "th": "THB", "ru": "RUB", "in": "INR", "vn": "VND",
    "ph": "PHP", "tw": "TWD", "mo": "MOP", "de": "EUR", "fr": "EUR",
    "it": "EUR", "es": "EUR", "nl": "EUR", "be": "EUR", "at": "EUR",
    "pt": "EUR", "ie": "EUR", "gr": "EUR", "fi": "EUR", "lu": "EUR",
    "cy": "EUR", "ee": "EUR", "lv": "EUR", "lt": "EUR", "mt": "EUR",
    "sk": "EUR", "si": "EUR", "hr": "EUR", "eu": "EUR",
    "ae": "AED", "sa": "SAR", "tr": "TRY", "il": "ILS", "id": "IDR",
    "pk": "PKR", "br": "BRL", "mx": "MXN", "za": "ZAR", "se": "SEK",
    "no": "NOK", "dk": "DKK", "pl": "PLN", "ua": "UAH", "eg": "EGP",
    "ng": "NGN", "bd": "BDT", "ir": "IRR", "iq": "IQD", "kw": "KWD",
    "qa": "QAR", "jo": "JOD", "lb": "LBP", "ma": "MAD", "dz": "DZD",
    "tn": "TND", "ly": "LYD", "cu": "CUP", "jm": "JMD", "pa": "PAB",
    "uy": "UYU", "py": "PYG", "bo": "BOB", "ve": "VES", "is": "ISK",
    "ge": "GEL", "az": "AZN", "kz": "KZT", "uz": "UZS", "kg": "KGS",
    "tj": "TJS", "tm": "TMT", "mn": "MNT", "mm": "MMK", "kh": "KHR",
    "la": "LAK", "np": "NPR", "lk": "LKR", "af": "AFN", "ye": "YER",
    "sy": "SYP", "bh": "BHD", "om": "OMR", "ke": "KES", "ug": "UGX",
    "rw": "RWF", "et": "ETB", "gh": "GHS", "ro": "RON", "bg": "BGN",
    "rs": "RSD", "mk": "MKD", "al": "ALL", "ba": "BAM", "md": "MDL",
    "by": "BYN", "cz": "CZK", "hu": "HUF",
}


# 合并替换表：货币别名 + 国家名（统一最长优先），normalize() 运行时使用。
# 国家名也接进换算（"66新加坡" → SGD），但触发要见 parse_query 的 used_alias 规则。
_ALL_MATCH = sorted(list(_ALIASES.items()) + list(_COUNTRY_NAME.items())
                    + list(_PINYIN.items()) + list(_ISO_CC.items()),
                    key=lambda kv: -len(kv[0]))

# 分词候选 = 三字货币代码 + 全部别名表，按长度降序。
# 三字码必须在两字母 ISO/拼音之前试（不然 "hkcny" 会被拆成 hk+cn+y）。
_CODE3 = {c.lower(): c for c in CN_NAMES}
_TOKEN_PATTERNS = sorted(list(_CODE3.items()) + _ALL_MATCH,
                         key=lambda kv: -len(kv[0]))


def recognize(text):
    """自由文本里识别货币（「直接输入」选择用）。

    输入例：「美金人民币日元澳大利亚印度」「usd 欧元 日本」
    返回 (found_codes, not_found_tokens)：
      found_codes 按出现顺序去重；not_found 是认不出来的片段。
    规则：别名 / 中文货币名 / 国家名 / 三字码，最长优先贪心扫描。
    单字符别名（元 块 刀 $ 等）不参与 —— 否则「澳大利亚元」会误加一个 CNY。
    """
    low = text.strip().lower()
    if not low:
        return [], [], []
    cands = []                                   # (写法小写, 代码)
    for a, c in _ALIASES.items():
        if len(a) >= 2:
            cands.append((a, c))
    for n, c in _COUNTRY_NAME.items():
        cands.append((n.lower(), c))
    for p, c in _PINYIN.items():
        cands.append((p, c))
    for p, c in _ISO_CC.items():
        cands.append((p, c))
    for c in CN_NAMES:
        cands.append((CN_NAMES[c].lower(), c))
        cands.append((c.lower(), c))             # 三字码本身
    for c in BUTTON_SHORT:
        cands.append((BUTTON_SHORT[c].lower(), c))
    cands.sort(key=lambda x: -len(x[0]))         # 长的先匹配（美元 > 美 等）

    marks = []                                   # (start, end, code)
    for pat, code in cands:
        pos = 0
        while True:
            idx = low.find(pat, pos)
            if idx < 0:
                break
            end = idx + len(pat)
            # 只接受未被已有命中覆盖的区域（不重叠取最长）
            if not any(s < end and idx < e for s, e, _ in marks):
                marks.append((idx, end, code))
            pos = idx + 1
    marks.sort()
    found, seen = [], set()
    for _s, _e, c in marks:
        if c not in seen:
            found.append(c)
            seen.add(c)
    # 没命中的片段 → not_found
    leftovers, prev = [], 0
    for s_, e_, _c in marks:
        if s_ > prev:
            leftovers.append(text[prev:s_])
        prev = e_
    if prev < len(text):
        leftovers.append(text[prev:])
    not_found = []
    for lf in leftovers:
        for tok in re.split(r"[,，、;；\s]+", lf.strip(u" ,，、;；.")):
            if not tok:
                continue
            # 货币单位后缀（元/圆/块/钱）不报未识别 —— 「澳大利亚元」里剩的「元」是后缀
            if tok in (u"元", u"圆", u"块", u"钱"):
                continue
            if len(tok) == 1:
                continue                    # 单字符碎片（usdd 剩的 d 之类）没意义
            not_found.append(tok)
    # 没认出来的再过一遍错别字模糊匹配（新家坡→新加坡元；收敛到唯一代码才认）
    fuzzy_hits = []
    still = []
    for tok in not_found:
        r = _fuzzy_code(tok.lower())
        if r and r[0] not in seen:
            found.append(r[0])
            seen.add(r[0])
            fuzzy_hits.append((tok, r[0], r[1]))
        elif r:
            fuzzy_hits.append((tok, r[0], r[1]))   # 已勾选过的也算命中
        else:
            still.append(tok)
    return found, still, fuzzy_hits


# ---------------------------------------------------------------- 换算与展示
# 欧元区国家名集合（用于「这个国家用欧元」的提示；欧洲/欧盟/欧元区本身不需要提示）
_EUROZONE_NAMES = sorted(
    (n for n, c in _COUNTRY_NAME.items()
     if c == "EUR" and n not in (u"欧洲", u"欧盟", u"欧元区")),
    key=len, reverse=True)


def euro_country_hint(text):
    """输入里提到某个欧元区国家名 → 返回提示文本；否则 None。

    例：「100意大利」→ 「ℹ️ 意大利 使用欧元（EUR）」
    """
    low = text.strip().lower()
    for n in _EUROZONE_NAMES:
        if n in low:
            return u"ℹ️ %s 使用欧元（EUR）" % n
    return None


def convert(amount, frm, to, rates):
    """跨币换算。返回 float；币种不存在抛 KeyError（调用方给友好提示）。"""
    return amount / rates[frm] * rates[to]


def known_codes(rates):
    s = set(_ALIAS_CODES)
    if rates:
        s |= set(rates["rates"].keys())
    return s


# 货币流行度（全球支付/结算量从高到低，参考 SWIFT 排名和实际使用频率）。
# 不在表里的长尾币种按字母排在其后。
_POPULAR = [
    "USD", "EUR", "GBP", "JPY", "CNY", "CAD", "AUD", "HKD", "CHF", "SGD",
    "KRW", "SEK", "NOK", "THB", "INR", "RUB", "MXN", "TWD", "NZD", "ZAR",
    "BRL", "DKK", "PLN", "TRY", "ILS", "AED", "SAR", "CZK", "HUF", "IDR",
    "PHP", "MYR", "VND", "CLP", "COP", "PEN", "RON", "UAH", "EGP", "NGN",
    "PKR", "QAR", "KWD", "BDT", "LKR", "NPR", "MMK", "KHR", "LAK", "MOP",
    "ARS", "GHS", "KES", "TZS", "UGX", "RWF", "ETB", "DZD", "MAD", "TND",
    "LYD", "IQD", "IRR", "YER", "SYP", "LBP", "JOD", "BHD", "OMR", "KZT",
    "UZS", "KGS", "TJS", "TMT", "MNT", "GEL", "AMD", "AZN", "BYN", "MDL",
    "ALL", "BAM", "MKD", "RSD", "BGN", "HRK", "LSL", "MUR", "JMD", "PAB",
    "UYU", "PYG", "BOB", "VES", "GYD", "SRD", "TVD", "FJD", "WST", "PGK",
    "SBD", "VUV", "KID", "XAF", "XOF", "XCD", "XPF", "XCG", "ANG", "XDR",
]


def all_codes(data):
    """货币选择页的完整列表：已知名字 + 汇率表里的全部代码，按流行度排序。

    主流的在前（美元/欧元/英镑/日元/人民币…），长尾按字母排在其后。
    """
    s = set(CN_NAMES)
    if data:
        s |= set(data["rates"].keys())
    idx = {c: i for i, c in enumerate(_POPULAR)}
    return sorted(s, key=lambda c: (idx.get(c, 999), c))


def page_slice(items, page, per=PICKER_PAGE):
    """第 page 页（0 起）的切片 + 总页数。page 越界自动夹回。"""
    total = max(1, (len(items) + per - 1) // per)
    page = max(0, min(page, total - 1))
    return items[page * per:(page + 1) * per], total


# 常见货币的符号/单位（金额后缀；没有的就不加，代码本来就在前面）
_UNITS = {
    "USD": "$", "EUR": "€", "GBP": "£", "JPY": u"円", "CNY": u"¥",
    "HKD": "HK$", "KRW": "₩", "SGD": "S$", "TWD": "NT$", "AUD": "A$",
    "CAD": "C$", "CHF": "Fr.", "THB": "฿", "RUB": "₽", "INR": "₹",
    "VND": "₫", "MYR": "RM", "PHP": "₱", "NZD": "NZ$", "MXN": "$",
    "BRL": "R$", "ZAR": "R", "SEK": "kr", "NOK": "kr", "DKK": "kr",
    "PLN": u"zł", "TRY": "₺", "ILS": "₪", "IDR": "Rp", "PKR": "₨",
}


def unit(code):
    """金额后缀：' €' / ' ¥' / ' 元'…；没收录的返回 ''。"""
    u = _UNITS.get(code)
    return u" " + u if u else ""


def cn_name(code):
    return CN_NAMES.get(code, code)


def flag(code):
    return FLAGS.get(code, "")


def fmt_amt(x):
    """金额展示：大数带千分位，小数最多 2 位；汇率展示用 fmt_rate。"""
    if x >= 1000:
        return "{:,.2f}".format(x)
    s = "{:.2f}".format(x)
    return s


def fmt_rate(x):
    if x >= 100:
        return "{:,.2f}".format(x)
    if x >= 1:
        return "{:.4f}".format(x)
    return "{:.6f}".format(x).rstrip("0").rstrip(".")


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
