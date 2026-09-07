# -*- coding: utf-8 -*-
"""IP 模块自测 —— 全离线（mock 网络），跑法：python3 selftest_ip.py"""
import json
import os
import sys
import tempfile
import unittest.mock as mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from modules.ip import engine as ip                    # noqa: E402

_tmpd = tempfile.mkdtemp()
ip.CACHE_FILE = os.path.join(_tmpd, "ip_cache.json")

_pass, _fail = 0, 0


def check(name, got, want):
    global _pass, _fail
    ok = got == want
    _pass, _fail = (_pass + 1, _fail) if ok else (_pass, _fail + 1)
    print("  %s %s" % ("✅" if ok else "❌ %s  得到 %r 期望 %r" % (name, got, want), name) if ok
          else "  ❌ %s\n      得到 %r\n      期望 %r" % (name, got, want))


def check_true(name, cond):
    check(name, bool(cond), True)


print(u"── 1. IP 识别（is_ip_query）")
cases = [
    ("179.255.112.32", "179.255.112.32"),       # 用户原话场景
    ("  1.2.3.4  ", "1.2.3.4"),                 # 首尾空白
    ("1.2.3.4:8080", "1.2.3.4"),                # 带端口
    ("2001:db8::1", "2001:db8::1"),             # IPv6
    ("::1", "::1"),                             # IPv6 回环
    ("::ffff:1.2.3.4", "::ffff:1.2.3.4"),       # 映射地址
    ("255.255.255.255", "255.255.255.255"),     # 边界值
    ("8.8.8.8", "8.8.8.8"),
    ("256.1.1.1", None),                        # 段超 255
    ("1.2.3", None),                            # 只有 3 段
    ("1.2.3.4.5", None),                        # 5 段
    ("999", None),                              # 纯数字不是 IP
    ("这是句子 1.2.3.4 吗", None),                # 句子里含 IP → 不触发
    ("1.2.3.4 5.6.7.8", None),                  # 两个 IP → 不触发
    ("abc", None),
    ("", None),
    ("1.2.3.4:abc", None),                      # 端口非数字
    ("8.8.8.8:99999", "8.8.8.8"),               # 端口超 5 位数字截不了，仍识别 IPv4+端口
]
for t, want in cases:
    check("识别 %r" % t, ip.is_ip_query(t), want)

print(u"── 2. 响应解析（两源格式）")
API_OK = {"status": "success", "country": "巴西", "countryCode": "BR",
          "region": "SP", "regionName": "圣保罗州", "city": "圣保罗", "zip": "01310",
          "lat": -23.55, "lon": -46.63, "timezone": "America/Sao_Paulo",
          "isp": "Vivo", "org": "Telefonica Brasil", "as": "AS28573 Claro NET",
          "mobile": False, "proxy": False, "hosting": True, "query": "179.255.112.32"}
d = ip._norm_ipapi(API_OK)
check("ipapi country", d["country"], "巴西")
check("ipapi asn", d["asn"], "AS28573")
check("ipapi asname", d["asname"], "Claro NET")
check("ipapi hosting", d["hosting"], True)
check("ipapi src", d["src"], "ip-api")
WHO_OK = {"ip": "8.8.8.8", "success": True, "country": "United States",
          "country_code": "US", "region": "California", "city": "Mountain View",
          "postal": "94043", "latitude": 37.42, "longitude": -122.09,
          "timezone": {"id": "America/Los_Angeles"},
          "connection": {"asn": 15169, "org": "GOOGLE", "isp": "Google LLC",
                         "domain": "google.com"}}
d2 = ip._norm_ipwho(WHO_OK)
check("who isp", d2["isp"], "Google LLC")
check("who asn", d2["asn"], "AS15169")
check("who src", d2["src"], "ipwho")
try:
    ip._norm_ipapi({"status": "fail", "message": "reserved range"})
    check("ipapi fail 抛 IPErr", False, True)
except ip.IPErr as e:
    check("ipapi fail 抛 IPErr", "reserved" in str(e), True)
try:
    ip._norm_ipwho({"success": False, "message": "msg"})
    check("who fail 抛 IPErr", False, True)
except ip.IPErr:
    check("who fail 抛 IPErr", True, True)

print(u"── 3. 国旗")
check("BR 旗", ip._flag("BR"), "🇧🇷")
check("US 旗", ip._flag("us"), "🇺🇸")
check("无效 cc", ip._flag("XX1"), u"")

print(u"── 4. 排版（可读性）")
html = ip.fmt_report(d)
check_true("含 IP", "179.255.112.32" in html)
check_true("含国旗", "🇧🇷" in html)
check_true("含国家", "巴西" in html)
check_true("含省市", "圣保罗" in html)
check_true("含运营商", "Vivo" in html)
check_true("含 ASN", "AS28573" in html)
check_true("含机房标记", "机房数据中心" in html)
check_true("含时区", "America/Sao_Paulo" in html)
check_true("HTML 转义生效", ip.fmt_report(ip._norm_ipapi(
    dict(API_OK, isp='A&B<test>'))).count("&amp;") >= 1)
check_true("地图链接", "maps.google.com" in ip.map_url(d))
check_true("无属性行（住宅直连）", "机房" not in ip.fmt_report(ip._norm_ipapi(
    dict(API_OK, hosting=False, proxy=False, mobile=False))))

print(u"── 5. lookup：mock 主源成功 + 缓存")
calls = []


class FakeResp(object):
    def __init__(self, payload):
        self._p = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._p


def fake_urlopener(resp_by_url_sub):
    def _open(req, timeout=0):
        calls.append(req.full_url if hasattr(req, "full_url") else str(req))
        for sub, payload in resp_by_url_sub.items():
            if sub in req.full_url:
                return FakeResp(payload)
        raise IOError("no route")
    return _open


ip.CACHE_FILE = os.path.join(_tmpd, "c5.json")
with mock.patch("urllib.request.urlopen",
                fake_urlopener({"ip-api.com": API_OK, "ipwho.is": WHO_OK})):
    r1 = ip.lookup("179.255.112.32")
check("主源成功", r1["country"], "巴西")
check_true("只打了主源", len(calls) == 1 and "ip-api" in calls[0])
with mock.patch("urllib.request.urlopen",
                fake_urlopener({"ip-api.com": API_OK, "ipwho.is": WHO_OK})):
    n = len(calls)
    r2 = ip.lookup("179.255.112.32")
check_true("10 分钟内走缓存（不再打网络）", len(calls) == n and r2["country"] == "巴西")

print(u"── 6. lookup：主源挂 → 备源降级")
ip.CACHE_FILE = os.path.join(_tmpd, "c6.json")
calls = []
with mock.patch("urllib.request.urlopen",
                fake_urlopener({"ipwho.is": WHO_OK})):     # ip-api 不可达
    r3 = ip.lookup("8.8.8.8")
check("备源降级成功", r3["isp"], "Google LLC")
check_true("走了备源", any("ipwho" in c for c in calls))

print(u"── 7. lookup：双源全挂 → 明确报错")
ip.CACHE_FILE = os.path.join(_tmpd, "c7.json")
with mock.patch("urllib.request.urlopen",
                fake_urlopener({"nothing": {}})):
    try:
        ip.lookup("8.8.8.8")
        check("双挂报 IPErr", False, True)
    except ip.IPErr as e:
        check_true("双挂报 IPErr", "两个查询源" in str(e))

print(u"── 8. 保留地址：主源明确报 fail（不降级）")
ip.CACHE_FILE = os.path.join(_tmpd, "c8.json")
calls = []
FAIL_PRIV = {"status": "fail", "message": "private range"}
with mock.patch("urllib.request.urlopen",
                fake_urlopener({"ip-api.com": FAIL_PRIV, "ipwho.is": WHO_OK})):
    try:
        ip.lookup("192.168.1.1")
        check("保留地址报错", False, True)
    except ip.IPErr as e:
        check_true("保留地址报错", "private" in str(e))
check_true("保留地址不降级（不再打备源）", len(calls) == 1)

print()
print("=" * 40)
print("通过 %d，失败 %d" % (_pass, _fail))
sys.exit(1 if _fail else 0)
