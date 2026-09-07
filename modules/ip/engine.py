# -*- coding: utf-8 -*-
"""IP 查询引擎 —— 纯函数，不依赖框架。可独立跑自测。

数据源（免费、免登录）：
  主源  ip-api.com   JSON 字段最全、支持 lang=zh 中文返回（免费档仅 HTTP，服务端调用无影响）
  备源  ipwho.is     HTTPS、无 key（主源失败/超时自动降级）

缓存：同 IP 10 分钟内直接用缓存，防止重复查询浪费免费配额。
"""

import json
import re
import time
import urllib.request

CACHE_FILE = ""            # 由 __init__.py 注入 DATA_DIR/ip_cache.json
CACHE_TTL = 600            # 10 分钟
_TIMEOUT = 8

# ---------------------------------------------------------------- IP 识别
_IPV4_RE = re.compile(
    r"^(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
    r"(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}$")
_IPV6_RE = re.compile(
    r"^([0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}$"
    r"|^([0-9A-Fa-f]{1,4}:){1,7}:"            # 1::      1:::1 结尾省略
    r"|^([0-9A-Fa-f]{1,4}:){1,6}:[0-9A-Fa-f]{1,4}$"
    r"|^([0-9A-Fa-f]{1,4}:){1,5}(:[0-9A-Fa-f]{1,4}){1,2}$"
    r"|^([0-9A-Fa-f]{1,4}:){1,4}(:[0-9A-Fa-f]{1,4}){1,3}$"
    r"|^([0-9A-Fa-f]{1,4}:){1,3}(:[0-9A-Fa-f]{1,4}){1,4}$"
    r"|^([0-9A-Fa-f]{1,4}:){1,2}(:[0-9A-Fa-f]{1,4}){1,5}$"
    r"|^[0-9A-Fa-f]{1,4}:((:[0-9A-Fa-f]{1,4}){1,6})$"
    r"|^:((:[0-9A-Fa-f]{1,4}){1,7}|:)$"
    r"|^::(FFFF|ffff(:0{1,4})?):((25[0-5]|(2[0-4]|1?[0-9])?[0-9])\.){3}"
    r"(25[0-5]|(2[0-4]|1?[0-9])?[0-9])$")     # ::ffff:1.2.3.4 映射地址
_PORT_RE = re.compile(r"^(.+?)(?::\d{1,5})$")  # 尾部 :端口（IPv6 冒号多，只在匹配失败后尝试）


def _is_ipv4(s):
    return bool(_IPV4_RE.match(s))


def _is_ipv6(s):
    return bool(_IPV6_RE.match(s)) and ":" in s


def is_ip_query(text):
    """整条消息是否就是一个 IP（容忍首尾空白与 IPv4 的 :端口 后缀）。

    句子里「包含」IP 不算 —— 必须整条消息就是一个地址，防止误伤普通聊天。
    返回规范化的 IP 字符串，不是 IP 返回 None。
    """
    s = (text or "").strip()
    if not s or len(s) > 63:
        return None
    if _is_ipv4(s) or _is_ipv6(s):
        return s
    # IPv4 带端口：1.2.3.4:8080（IPv6 不尝试，冒号歧义太大）
    m = _PORT_RE.match(s)
    if m and "." in m.group(1) and _is_ipv4(m.group(1)):
        return m.group(1)
    return None


# ---------------------------------------------------------------- 查询
class IPErr(Exception):
    """查询失败（网络/配额/保留地址），消息可直接展示给用户。"""


def _flag(cc):
    """国家代码 → 旗帜 emoji（无效返回空）。"""
    if not cc or len(cc) != 2 or not cc.isalpha():
        return u""
    return u"".join(chr(0x1F1E6 + ord(c) - 65) for c in cc.upper())


def _norm_ipapi(d):
    """ip-api.com JSON → 统一结构。"""
    if d.get("status") != "success":
        raise IPErr(u"查询失败：%s" % d.get("message", u"未知原因"))
    return {
        "ip": d.get("query", ""),
        "country": d.get("country", ""),
        "cc": d.get("countryCode", ""),
        "region": d.get("regionName", ""),
        "city": d.get("city", ""),
        "zip": d.get("zip", ""),
        "lat": d.get("lat"),
        "lon": d.get("lon"),
        "tz": d.get("timezone", ""),
        "isp": d.get("isp", ""),
        "org": d.get("org", ""),
        "asn": (d.get("as", "") or "").split(" ")[0],
        "asname": (d.get("as", "") or "").split(" ", 1)[-1],
        "mobile": bool(d.get("mobile")),
        "proxy": bool(d.get("proxy")),
        "hosting": bool(d.get("hosting")),
        "src": "ip-api",
    }


def _norm_ipwho(d):
    """ipwho.is JSON → 统一结构。"""
    if not d.get("success", False):
        raise IPErr(u"查询失败：%s" % d.get("message", u"未知原因"))
    conn = d.get("connection") or {}
    tz = d.get("timezone") or {}
    return {
        "ip": d.get("ip", ""),
        "country": d.get("country", ""),
        "cc": d.get("country_code", ""),
        "region": d.get("region", ""),
        "city": d.get("city", ""),
        "zip": d.get("postal", ""),
        "lat": d.get("latitude"),
        "lon": d.get("longitude"),
        "tz": tz.get("id", ""),
        "isp": conn.get("isp", ""),
        "org": conn.get("org", ""),
        "asn": u"AS%s" % conn["asn"] if conn.get("asn") else "",
        "asname": conn.get("domain", ""),
        "mobile": False,
        "proxy": False,
        "hosting": False,
        "src": "ipwho",
    }


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "unmi_TGtool-ip"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        return json.load(r)


def _fetch_cache(ip):
    try:
        with open(CACHE_FILE) as f:
            cache = json.load(f)
    except Exception:                       # noqa: BLE001
        return None
    ent = cache.get(ip)
    if ent and time.time() - ent.get("ts", 0) < CACHE_TTL:
        return ent["data"]
    return None


def _write_cache(ip, data):
    try:
        try:
            with open(CACHE_FILE) as f:
                cache = json.load(f)
        except Exception:                   # noqa: BLE001
            cache = {}
        now = time.time()
        cache = {k: v for k, v in cache.items()
                 if now - v.get("ts", 0) < CACHE_TTL}
        cache[ip] = {"ts": now, "data": data}
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception:                       # noqa: BLE001
        pass                                # 缓存失败不影响主流程


def lookup(ip):
    """查一个 IP 的归属信息。成功返回统一结构 dict，失败抛 IPErr。"""
    hit = _fetch_cache(ip)
    if hit is not None:
        return hit
    try:
        data = _norm_ipapi(_fetch(
            u"http://ip-api.com/json/%s?fields=status,message,country,"
            u"countryCode,region,regionName,city,zip,lat,lon,timezone,"
            u"isp,org,as,mobile,proxy,hosting,query&lang=zh-CN" % ip))
    except IPErr:
        raise                               # 保留地址等业务性失败：不降级，直接报
    except Exception:                       # noqa: BLE001  网络/解析失败 → 备源
        try:
            data = _norm_ipwho(_fetch(u"https://ipwho.is/%s" % ip))
        except Exception as e2:             # noqa: BLE001
            raise IPErr(u"两个查询源都没连上（%s），稍后再试" % type(e2).__name__)
    _write_cache(ip, data)
    return data


# ---------------------------------------------------------------- 排版
def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _props_line(d):
    props = []
    if d.get("hosting"):
        props.append(u"机房数据中心")
    if d.get("proxy"):
        props.append(u"代理/VPN")
    if d.get("mobile"):
        props.append(u"移动网络")
    return u" · ".join(props)


def fmt_report(d):
    """统一结构 → HTML 报告（可读性优先：地区一行、归属一行、属性突出）。"""
    flag = _flag(d.get("cc"))
    loc = u" · ".join(x for x in (d.get("region", ""), d.get("city", "")) if x)
    loc_line = u"%s <b>%s</b>" % (flag, esc(d.get("country", u"未知")))
    if loc:
        loc_line += u" · %s" % esc(loc)
    if d.get("zip"):
        loc_line += u" · 邮编 %s" % esc(d["zip"])

    lines = [
        u"🌐 <code>%s</code>" % esc(d.get("ip", "")),
        loc_line,
        u"────────────",
        u"📡 运营商：<b>%s</b>" % esc(d.get("isp", u"未知")),
    ]
    if d.get("asn"):
        asn = u"%s %s" % (d["asn"], d.get("asname", "")) if d.get("asname") else d["asn"]
        lines.append(u"🏷 ASN：%s" % esc(asn))
    props = _props_line(d)
    if props:
        lines.append(u"⚠️ 属性：<b>%s</b>" % props)
    if d.get("tz"):
        lines.append(u"🕐 时区：%s" % esc(d["tz"]))
    if d.get("lat") is not None and d.get("lon") is not None:
        lines.append(u"📍 坐标：%s, %s" % (d["lat"], d["lon"]))
    lines.append(u"────────────")
    lines.append(u"<i>ip-api.com</i>" if d.get("src") != "ipwho" else u"<i>ipwho.is</i>")
    return u"\n".join(lines)


def map_url(d):
    """Google Maps 链接（坐标优先，退化到地区名）。"""
    if d.get("lat") is not None and d.get("lon") is not None:
        return u"https://maps.google.com/?q=%s,%s" % (d["lat"], d["lon"])
    loc = u" ".join(x for x in (d.get("country", ""), d.get("city", "")) if x)
    return u"https://maps.google.com/?q=%s" % loc if loc else u""
