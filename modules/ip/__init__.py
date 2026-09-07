# -*- coding: utf-8 -*-
"""IP 查询模块 —— 发一个 IP 地址，返回归属详情（运营商/ASN/机房标记/坐标）。

免费免登录：主源 ip-api.com（中文返回），备源 ipwho.is 自动降级。
"""
import os

from core.base import Module, PASS
from modules.ip import engine as ip

# 路径注入（engine 自身不依赖框架/环境）
_DATA_DIR = os.environ.get("DATA_DIR", "/opt/unmi_TGtool/data")
ip.CACHE_FILE = os.path.join(_DATA_DIR, "ip_cache.json")

_CB = "ipset"                              # 回调前缀：ipset:动作:参数


def _fmt_kb(d):
    """报告按钮：地图（URL 按钮）+ 重新查询（回调）。"""
    row = []
    mu = ip.map_url(d)
    if mu:
        row.append({"text": u"🗺 打开地图", "url": mu})
    row.append({"text": u"🔄 重新查询",
                "callback_data": "%s:lookup:%s" % (_CB, d.get("ip", ""))})
    return [row]


class Plugin(Module):
    name = "ip"
    version = "1.0.0"
    description = "IP 归属查询（发个 IP 就出运营商/ASN/机房详情）"
    commands = [{"command": "ip", "description": "🌐 IP 归属查询"}]

    def on_start(self):
        self.ctx.log.info("ip 模块已启动")

    # ------------------------------------------------------------ 消息
    def on_message(self, text, chat_id):
        target = ip.is_ip_query(text)
        if not target:
            return False                   # 不是纯 IP，传给下一个模块
        self._lookup_and_reply(target)
        return True

    # ------------------------------------------------------------ 命令
    def on_command(self, cmd, args, chat_id):
        if cmd != "ip":
            return PASS
        target = (args or "").strip()
        if not target:
            return (u"🌐 发一个 IP 地址就出详情，比如 <code>179.255.112.32</code>\n"
                    u"IPv4 / IPv6 都支持，带端口也行（<code>1.2.3.4:8080</code>）")
        self._lookup_and_reply(ip.is_ip_query(target) or target)
        return None

    # ------------------------------------------------------------ 回调
    def on_callback(self, data, cb_id, message):
        if not data.startswith(_CB + ":"):
            return False
        chat_id = str(message.get("chat", {}).get("id"))
        parts = data.split(":")
        if parts[1] == "lookup" and len(parts) >= 3:
            self._lookup_and_reply(parts[2])
            self.ctx.answer(cb_id, u"已刷新")
            return True
        self.ctx.answer(cb_id, u"⚠️ 未知的操作")
        return True

    # ------------------------------------------------------------ 内部
    def _lookup_and_reply(self, target):
        try:
            d = ip.lookup(target)
        except ip.IPErr as e:
            self.ctx.send(u"⚠️ %s" % e)
            return
        except Exception as e:              # noqa: BLE001
            self.ctx.send(u"⚠️ 查询出错了：%s" % type(e).__name__)
            return
        self.ctx.send(ip.fmt_report(d), buttons=_fmt_kb(d))
