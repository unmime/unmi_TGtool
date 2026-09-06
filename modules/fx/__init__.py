# -*- coding: utf-8 -*-
"""汇率模块 —— 把 engine.py 的换算能力接进框架（v2：交互菜单 + 向导）。

用法：
  直接发消息（自然语言，无需命令）：
      22人民币             → 按「展示货币」里勾选的币种排版展示
      100美元 人民币       → 显式指定目标币（单币种结果）
      100 usd cny / $100   → 三字码/符号也认
  命令：
      /fx                  → 交互菜单（点按钮操作，不用记命令）
      /fx 100 usd cny      → 换算
      /fx set eur          → 设置默认目标币
      /fx refresh          → 强制刷新汇率

汇率源：内置 4 个免费源（open.er-api.com 默认 / frankfurter / currency-api /
exchangerate-api v4），在 /fx 的「汇率源」页点一个切换，不用配 key。

触发门槛（防误伤闲聊）：
  - 用了中文/符号别名（"100美元"）→ 响应
  - 带金额的三字码（"100 usd"）→ 响应
  - 裸三字码不带金额（"usd"）→ 不响应（"try"/"usd" 可能是闲聊，想看汇率用 /fx）

默认不预勾选任何展示货币：新用户直接发金额时，会收到「先去设置勾选」的
友好引导（显式指定目标的换算不受影响）。
"""
import os
import re

from core.base import Module, PASS

from . import engine as fx

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DATA_DIR = os.environ.get("DATA_DIR", os.path.join(_PROJECT_ROOT, "data"))

fx._CACHE_FILE = os.path.join(_DATA_DIR, "fx_rates.json")
fx.SETTINGS_FILE = os.path.join(_DATA_DIR, "fx_settings.json")

_CB = "fxset"          # callback_data 前缀：fxset:动作:参数
_BTN_PER_ROW = 3       # 货币按钮每行 3 个（带国旗+名字，3 个不超宽）

# 「直接输入」选货币的向导状态：chat_id → True（等用户发货币/国家名）
_PENDING_TYPEIN = {}

# 加密货币关闭时用户尝试的换算：chat_id → (amount, frm, to, text, expr)
# 一键开启后直接把结果补出来，不用重发
_PENDING_CRYPTO = {}

_TYPEIN_GUIDE = (
    u"✏️ <b>直接输入货币</b>\n\n"
    u"把货币或国家名发给我，<b>连着写</b>或用空格/逗号隔开都行：\n"
    u"<code>美金人民币日元澳大利亚印度</code>\n"
    u"<code>usd eur 日本 澳洲</code>\n\n"
    u"认出来的自动勾选，没认出来的会告诉你。\n"
    u"发「取消」退出")

_TYPEINC_GUIDE = (
    u"🪙 <b>输入加密货币</b>\n\n"
    u"把加密货币名发给我：\n"
    u"<code>比特币 以太坊 狗狗币</code>\n"
    u"<code>btc eth doge</code>\n\n"
    u"认出来的自动勾选进展示货币。发「取消」退出")


# ---------------------------------------------------------------- 按钮标签
def _tag(label, selected):
    return u"%s%s" % (u"🟢 " if selected else "", label)


def _btn_label(code):
    """货币按钮：国旗 + 短名 + 代码。短名优先用 BUTTON_SHORT，没有就截全名。"""
    fl = fx.flag(code)
    short = fx.BUTTON_SHORT.get(code) or fx.cn_name(code)[:4]
    if fl:
        return u"%s %s %s" % (fl, short, code)
    return u"%s %s" % (short, code)


def _rows(items, per=_BTN_PER_ROW):
    return [items[i:i + per] for i in range(0, len(items), per)]


_BACK_CLOSE = [{"text": u"‹ 返回主菜单", "callback_data": "%s:open" % _CB},
               {"text": u"❌ 收起", "callback_data": "%s:close" % _CB}]


# ---------------------------------------------------------------- 菜单构建
def _menu_main():
    st = fx.get_settings()
    disp = [c for c in st["display"] if c]
    if disp:
        disp_txt = u" · ".join(fx.cn_name(c) for c in disp[:5])
        if len(disp) > 5:
            disp_txt += u" 等%d种" % len(disp)
    else:
        disp_txt = u"（还没勾选 · 换算时会引导你设置）"
    src = next((a["name"] for a in fx.BUILTIN_APIS if a["id"] == st["source"]),
               st["source"])
    crypto = u"、".join(fx.CRYPTO_NAMES[c] for c in
                        ("BTC", "ETH", "USDT", "SOL", "DOGE"))
    crypto_line = (u"🪙 加密货币：开（实时价 · Binance）" if st["crypto_on"]
                   else u"🪙 加密货币：关")
    text = (
        u"💱 <b>汇率换算</b>\n\n"
        u"直接发金额就能换，比如 <code>22人民币</code> / <code>zg</code> / <code>$100</code> / <code>100usd</code>\n\n"
        u"🌐 展示货币：%s\n"
        u"🎯 默认目标：%s（%s）\n"
        u"💵 汇率源：%s\n"
        u"%s" % (
            disp_txt, fx.cn_name(st["target"]), st["target"], src, crypto_line))
    kb = [
        [{"text": u"➕ 添加法定货币",
          "callback_data": "%s:cur:typein:0" % _CB}],
        [{"text": u"🔄 重置展示货币", "callback_data": "%s:cur:reset" % _CB}],
        [{"text": u"🎯 默认目标 ▸", "callback_data": "%s:tgt:page:0" % _CB},
         {"text": u"💵 汇率源 ▸", "callback_data": "%s:api:open" % _CB}],
        [{"text": u"🪙 加密货币换算：%s" % (u"🟢 开" if st["crypto_on"] else u"⚪ 关"),
          "callback_data": "%s:cryptotoggle" % _CB}]]
    if st["crypto_on"]:       # 关着时不显示加密向导入口
        kb.append([{"text": u"🪙 输入加密货币关键字添加转换货币",
                    "callback_data": "%s:cur:typeinc:0" % _CB}])
    kb.append([
        {"text": u"🔄 刷新汇率", "callback_data": "%s:refresh" % _CB},
        {"text": u"❌ 收起", "callback_data": "%s:close" % _CB}])
    return text, kb



def _menu_picker(kind, page):
    """货币选择页。kind: cur（多选，展示货币）/ tgt（单选，默认目标）。"""
    st = fx.get_settings()
    data = fx.load_rates()
    codes = fx.all_codes(data)
    cur_page, total = fx.page_slice(codes, page)
    if kind == "cur":
        selected = set(st["display"])
        title = u"🪙 <b>展示货币</b>（勾选换算时展示哪些，可多选）"
        if selected:
            sel_txt = u"已选 %d 个：%s%s" % (
                len(selected),
                u"、".join(fx.cn_name(c) for c in sorted(selected)[:6]),
                u" …" if len(selected) > 6 else "")
        else:
            sel_txt = u"还没勾选 —— 勾几个常用的，比如 🇺🇸美元 🇯🇵日元 🇭🇰港币"
    else:
        selected = {st["target"]}
        title = u"🎯 <b>默认目标币</b>"
        sel_txt = u"当前：%s（%s）" % (fx.cn_name(st["target"]), st["target"])
    text = u"%s\n%s\n<i>第 %d/%d 页 · 点币种%s</i>" % (
        title, sel_txt, page + 1, total,
        u"切换勾选" if kind == "cur" else u"设为默认")
    btns = []
    for c in cur_page:
        cb = u"%s:cur:toggle:%s:%d" % (_CB, c, page) if kind == "cur" \
            else u"%s:tgt:set:%s" % (_CB, c)
        btns.append({"text": _tag(_btn_label(c), c in selected), "callback_data": cb})
    kb = _rows(btns)
    # 页码全部直接列出（7 页以内一行放得下），当前页用【】标出，点哪页跳哪页
    nav = []
    for i in range(total):
        label = u"【%d】" % (i + 1) if i == page else str(i + 1)
        nav.append({"text": label, "callback_data": "%s:%s:page:%d" % (_CB, kind, i)})
    kb.append(nav)
    if kind == "cur":
        kb.append([{"text": u"✏️ 直接输入（支持多个）",
                    "callback_data": "%s:cur:typein:%d" % (_CB, page)},
                   {"text": u"🧹 清空勾选", "callback_data": "%s:cur:clear:%d" % (_CB, page)}])
    kb.append(_BACK_CLOSE)
    return text, kb


def _menu_api():
    st = fx.get_settings()
    cur = st["source"]
    csrc = st.get("crypto_source", "binance")
    lines = [u"💵 <b>汇率源</b>（免费源，点一个切换）", ""]
    kb = []
    for a in fx.BUILTIN_APIS:
        on = a["id"] == cur
        lines.append(u"%s <b>💵 %s 💵</b> — %s"
                     % (u"🟢" if on else u"⚪", a["name"], a["desc"]))
        kb.append([{"text": _tag(u"💵 %s 💵" % a["name"], on),
                    "callback_data": "%s:api:use:%s" % (_CB, a["id"])}])
    lines.append(u"")
    lines.append(u"🪙 <b>加密货币源</b>（实时价，点一个切换）")
    for a in fx.CRYPTO_SOURCES:
        on = a["id"] == csrc
        lines.append(u"%s <b>🪙 %s 🪙</b> — %s"
                     % (u"🟢" if on else u"⚪", a["name"], a["desc"]))
        kb.append([{"text": _tag(u"🪙 %s 🪙" % a["name"], on),
                    "callback_data": "%s:csrc:use:%s" % (_CB, a["id"])}])
    kb.append(_BACK_CLOSE)
    return u"\n".join(lines), kb




def _find_api(st, key):
    for a in st["apis"]:
        if a["id"] == key or a["name"] == key:
            return a
    return None


def _suggest(code, known):
    c = code.lower()
    cand = [k for k in known if k.lower().startswith(c[:1])]
    cand.sort(key=len)
    return cand[:3]


# ---------------------------------------------------------------- 输出
def _disp_width(text):
    """估算显示宽度：CJK/全角/emoji 算 2，其余算 1。用于让分割线匹配内容长度。"""
    import re as _re
    import unicodedata
    plain = _re.sub(r"<[^>]+>", "", text)   # 剥掉 HTML 标签
    w = 0
    for ch in plain:
        if ord(ch) >= 0x1F000 or unicodedata.east_asian_width(ch) in ("W", "F"):
            w += 2
        else:
            w += 1
    return w


def _divider(header_text):
    """按标题行的显示宽度生成分割线（─ 按 1 格计，略留余量）。"""
    return u"─" * max(4, _disp_width(header_text))


def _amt_str(amount, frm, expr):
    """金额展示：有算式时显示 '算式 = 结果 单位'（联动计算器）。"""
    if expr:
        return u"%s = %s%s" % (expr, fx.fmt_amt(amount), fx.unit(frm))
    return u"%s%s" % (fx.fmt_amt(amount), fx.unit(frm))


def _fmt_pair(amount, frm, to, data, expr=None):
    """单币种结果：金额前带国旗和代码。返回 HTML 文本。"""
    rates = data["rates"]
    out = fx.convert(amount, frm, to, rates)
    rate = fx.convert(1, frm, to, rates)
    return (
        u"%s %s %s（%s）≈ <code>%s</code> %s %s（%s）\n"
        u"1 %s = %s %s\n"
        u"<i>%s</i>" % (
            _amt_str(amount, frm, expr), fx.flag(frm) or u"　", fx.cn_name(frm), frm,
            fx.fmt_amt(out) + fx.unit(to), fx.flag(to) or u"　", fx.cn_name(to), to,
            frm, fx.fmt_rate(rate), to, data["src"]))


def _fmt_targets(amount, frm, targets, data, expr=None):
    """按给定目标列表排版的多币种结果。"""
    rates = data["rates"]
    if expr:                        # 算式放 <code> 外，点复制只拿结果值
        head = u"%s %s（%s） %s = <code>%s%s</code> ≈" % (
            fx.flag(frm) or u"　", fx.cn_name(frm), frm, expr,
            fx.fmt_amt(amount), fx.unit(frm))
    else:
        head = u"%s %s（%s） <code>%s%s</code> ≈" % (
            fx.flag(frm) or u"　", fx.cn_name(frm), frm,
            fx.fmt_amt(amount), fx.unit(frm))
    lines = [head, _divider(head)]
    for c in targets:
        out = fx.convert(amount, frm, c, rates)
        fl = fx.flag(c)
        lines.append(u"   %s %s%s <code>%s%s</code>" % (
            fl or u"　", fx.cn_name(c),
            u"（%s）" % c if fx.cn_name(c) != c else "",
            fx.fmt_amt(out), fx.unit(c)))
    lines.append(u"\n<i>%s</i>" % data["src"])
    return u"\n".join(lines)


def _fmt_multi(amount, frm, data, expr=None):
    """按展示货币排版的多币种结果。返回 (HTML 文本, 是否用了多币种)。"""
    st = fx.get_settings()
    targets = [c for c in st["display"] if c != frm and c in data["rates"]]
    if not targets:
        return _fmt_pair(amount, frm, st["target"], data, expr), False
    return _fmt_targets(amount, frm, targets, data, expr), True


_SETUP_PROMPT = (
    u"💡 还没设置「展示货币」～\n"
    u"先去勾选想看的货币（比如 🇺🇸美元 🇯🇵日元），"
    u"之后发金额就能一次换算给你看。")

class Plugin(Module):
    name = "fx"
    version = "2.1.0"
    description = u"汇率换算（发金额即换 / /fx 交互菜单）"
    commands = [{"command": "fx", "description": u"💱 汇率换算"}]

    def on_start(self):
        self.ctx.log.info(u"fx 模块已启动")

    # ------------------------------------------------------------- 消息
    def on_message(self, text, chat_id):
        if chat_id in _PENDING_TYPEIN:
            mode = _PENDING_TYPEIN.get(chat_id) or "fiat"
            # 带金额的合法换算式优先走换算（向导只是选币，别吞掉正经查询）。
            if re.search(r"[0-9]", text):
                q = fx.parse_query_ex(text)
                if q and q["frm"]:
                    self._reply(q["amount"], q["frm"], q["to"], text, q["expr"])
                    return True                  # 向导状态保留，选币继续有效
            self._handle_typein_wizard(text, chat_id, mode)
            return True
        if len(text) > 32:
            return False
        q = fx.parse_query_ex(text)
        if not q:
            return False
        # 触发门槛：裸三字码不带金额不回（防 "usd"/"try" 这类闲聊误伤）
        if not q["used_alias"] and q["amount"] == 1.0:
            return False
        self._reply(q["amount"], q["frm"], q["to"], text, q["expr"])
        return True

    # ------------------------------------------------------------- 回调
    def on_callback(self, data, cb_id, message):
        if not data.startswith(_CB + ":"):
            return False
        # chat_id 必须 str() —— 框架的消息分发里 chat_id = str(...)，
        # 回调里直接取出来的是 int。类型不一致时向导状态字典按 int 存、按 str 查，
        # 永远查不到（「输入关键字不能用」就是这个 bug）。
        chat_id = str(message.get("chat", {}).get("id"))
        message_id = message.get("message_id")
        parts = data.split(":")
        action = parts[1] if len(parts) > 1 else ""
        st = fx.get_settings()

        if action == "close":
            self.ctx.delete(chat_id, message_id)
            self.ctx.answer(cb_id, u"已收起")
            return True
        if action == "open":
            t, kb = _menu_main()
            self.ctx.edit(chat_id, message_id, t, kb)
            self.ctx.answer(cb_id, u"已更新")
            return True
        if action == "cryptoon":
            # 一键开启：把关闭时用户尝试的那条换算直接补出来（原消息编辑成结果）
            st["crypto_on"] = True
            fx.save_settings(st)
            fx.load_rates(force=True)
            pend = _PENDING_CRYPTO.pop(chat_id, None)
            if pend:
                r = self._build_reply(*pend)
                if r:
                    self.ctx.edit(chat_id, message_id, r[0], r[1])
                    self.ctx.answer(cb_id, u"🪙 已开启，这是结果")
                    return True
            self.ctx.edit(chat_id, message_id,
                          u"✅ <b>加密货币换算已开启</b>（实时价 · Binance）\n"
                          u"再发一次刚才的换算就行")
            self.ctx.answer(cb_id, u"🪙 已开启")
            return True
        if action == "cryptotoggle":
            st["crypto_on"] = not st.get("crypto_on", False)
            if not st["crypto_on"]:
                # 关掉时把加密币从展示货币里剔除 —— 关了就彻底不出现
                st["display"] = [c for c in st["display"]
                                 if c not in fx.CRYPTO_NAMES]
            fx.save_settings(st)
            fx.load_rates(force=True)     # 立即重算（合并或剔除加密币）
            t, kb = _menu_main()
            self.ctx.edit(chat_id, message_id, t, kb)
            self.ctx.answer(cb_id, u"🪙 加密货币换算已开启" if st["crypto_on"]
                            else u"加密货币换算已关闭")
            return True
        if action == "csrc" and len(parts) >= 4 and parts[2] == "use":
            src = parts[3]
            if not any(a["id"] == src for a in fx.CRYPTO_SOURCES):
                self.ctx.answer(cb_id, u"⚠️ 这个源不存在")
                return True
            st["crypto_source"] = src
            fx.save_settings(st)
            fx.load_rates(force=True)
            t, kb = _menu_api()
            self.ctx.edit(chat_id, message_id, t, kb)
            self.ctx.answer(cb_id, u"✅ 加密货币源已切换")
            return True
        if action == "refresh":
            data = fx.load_rates(force=True)
            t, kb = _menu_main()
            self.ctx.edit(chat_id, message_id, t, kb)
            if data:
                self.ctx.answer(cb_id,
                                u"✅ 已刷新：%s · %d 币种" % (data["src"], len(data["rates"])))
            else:
                self.ctx.answer(cb_id, u"⚠️ 刷新失败，稍后再试")
            return True
        if action in ("cur", "tgt") and len(parts) >= 3 and parts[2] == "page":
            t, kb = _menu_picker(action, int(parts[3]))
            self.ctx.edit(chat_id, message_id, t, kb)
            self.ctx.answer(cb_id, "")
            return True
        if action == "cur" and len(parts) >= 4 and parts[2] == "toggle":
            code, page = parts[3], int(parts[4])
            disp = set(st["display"])
            if code in disp:
                disp.discard(code)
            else:
                disp.add(code)
            st["display"] = sorted(disp)
            fx.save_settings(st)
            t, kb = _menu_picker("cur", page)
            self.ctx.edit(chat_id, message_id, t, kb)
            self.ctx.answer(cb_id, u"已更新")
            return True
        if action == "cur" and len(parts) >= 3 and parts[2] == "reset":
            st["display"] = list(fx._DEFAULT_DISPLAY)
            fx.save_settings(st)
            t, kb = _menu_main()
            self.ctx.edit(chat_id, message_id, t, kb)
            self.ctx.answer(cb_id, u"✅ 展示货币已重置为默认")
            return True
        if action == "cur" and len(parts) >= 3 and parts[2] == "typein":
            _PENDING_TYPEIN[chat_id] = "fiat"
            self.ctx.edit(chat_id, message_id, _TYPEIN_GUIDE,
                          [[{"text": u"❌ 取消", "callback_data": "%s:open" % _CB}]])
            self.ctx.answer(cb_id, u"把货币/国家名发给我")
            return True
        if action == "cur" and len(parts) >= 3 and parts[2] == "typeinc":
            if not st["crypto_on"]:
                self.ctx.edit(chat_id, message_id,
                              u"🪙 加密货币换算当前是关闭的，开启后就能添加",
                              [[{"text": u"🪙 一键开启加密货币换算",
                                 "callback_data": "%s:cryptoon" % _CB}]])
                self.ctx.answer(cb_id, u"先开启加密货币换算")
                return True
            _PENDING_TYPEIN[chat_id] = "crypto"
            self.ctx.edit(chat_id, message_id, _TYPEINC_GUIDE,
                          [[{"text": u"❌ 取消", "callback_data": "%s:open" % _CB}]])
            self.ctx.answer(cb_id, u"把加密货币名发给我")
            return True
        if action == "cur" and len(parts) >= 4 and parts[2] == "clear":
            st["display"] = []
            fx.save_settings(st)
            t, kb = _menu_picker("cur", int(parts[3]))
            self.ctx.edit(chat_id, message_id, t, kb)
            self.ctx.answer(cb_id, u"🧹 已全部清空")
            return True
        if action == "tgt" and len(parts) >= 4 and parts[2] == "set":
            st["target"] = parts[3]
            fx.save_settings(st)
            t, kb = _menu_main()
            self.ctx.edit(chat_id, message_id, t, kb)
            self.ctx.answer(cb_id, u"✅ 默认目标已设为 %s" % parts[3])
            return True
        if action == "api" and len(parts) >= 3 and parts[2] == "open":
            t, kb = _menu_api()
            self.ctx.edit(chat_id, message_id, t, kb)
            self.ctx.answer(cb_id, "")
            return True
        if action == "api" and len(parts) >= 3 and parts[2] == "use":
            src = parts[3] if len(parts) > 3 else ""
            if not any(a["id"] == src for a in fx.BUILTIN_APIS):
                self.ctx.answer(cb_id, u"⚠️ 这个源不存在")
                return True
            st["source"] = src
            fx.save_settings(st)
            fx.load_rates(force=True)       # 切源后立刻刷新缓存
            t, kb = _menu_api()
            self.ctx.edit(chat_id, message_id, t, kb)
            self.ctx.answer(cb_id, u"✅ 已切换")
            return True
        self.ctx.answer(cb_id, u"⚠️ 未知的操作")
        return True


    # ------------------------------------------------------------- 向导
    def _handle_typein_wizard(self, text, chat_id, mode="fiat"):
        raw = text.strip()
        if raw in (u"取消", "/fx", "/cancel"):
            _PENDING_TYPEIN.pop(chat_id, None)
            self.ctx.send(u"已取消。/fx 回菜单")
            return
        found, not_found, fuzzy_hits = fx.recognize(raw)
        if mode == "crypto":
            # 加密向导：只认加密货币，法币候选一律不收
            found = [c for c in found if c in fx.CRYPTO_NAMES]
            fuzzy_hits = [(t, c, p) for t, c, p in fuzzy_hits
                          if c in fx.CRYPTO_NAMES]
            if not fx.get_settings().get("crypto_on"):
                _PENDING_TYPEIN.pop(chat_id, None)
                self.ctx.send(u"🪙 加密货币换算当前是关闭的，点下面按钮打开后重发即可",
                              buttons=[[{"text": u"🪙 一键开启加密货币换算",
                                         "callback_data": "%s:cryptoon" % _CB}]])
                return
        if not found:
            tip = (u"<code>比特币 以太坊 狗狗币</code>" if mode == "crypto"
                   else u"<code>美金 人民币 日元 澳大利亚</code>")
            self.ctx.send(
                u"⚠️ 一个都没认出来%s\n"
                u"试试这样写：%s\n"
                u"重发一次，或发「取消」退出" % (
                    u"（%s）" % u"、".join(not_found[:5]) if not_found else "", tip))
            return
        st = fx.get_settings()
        disp = set(st["display"])
        newly = [c for c in found if c not in disp]
        disp |= set(found)
        st["display"] = sorted(disp)
        fx.save_settings(st)
        _PENDING_TYPEIN.pop(chat_id, None)
        lines = [u"✅ <b>已识别并勾选 %d 种</b>：" % len(found)]
        if fuzzy_hits:
            fuzzy_txt = u"、".join(u"%s→%s" % (t, c) for t, c, _p in fuzzy_hits[:5])
            lines.append(u"🔍 模糊匹配：%s" % fuzzy_txt)
        lines.append(u" · ".join(fx._flag_from_cc(fx._COUNTRY.get(c, ("", ""))[0]) + u" %s %s"
                                 % (fx.cn_name(c), c) for c in found))
        if newly:
            lines.append(u"<i>新加 %d 种（其余 %d 种本来就在）</i>"
                         % (len(newly), len(found) - len(newly)) if len(found) > len(newly)
                         else u"")
        if not_found:
            lines.append(u"⚠️ 没认出：%s" % u"、".join(not_found[:6]))
        self.ctx.send(u"\n".join(lines),
                      buttons=[[{"text": u"🪙 查看展示货币",
                                 "callback_data": "%s:cur:page:0" % _CB},
                                {"text": u"✔ 完成", "callback_data": "%s:open" % _CB}]])


    # ------------------------------------------------------------- 命令
    def on_command(self, cmd, args, chat_id):
        if cmd != "fx":
            return PASS
        _PENDING_TYPEIN.pop(chat_id, None)
        arg = (args or "").strip()
        if not arg:
            t, kb = _menu_main()
            self.ctx.send(t, buttons=kb)
            return None
        low = arg.lower()

        if low in ("refresh", "update", u"刷新"):
            data = fx.load_rates(force=True)
            if data:
                self.ctx.send(u"✅ 汇率已刷新\n来源：%s\n币种：%d 个\n缓存：1 小时内复用"
                              % (data["src"], len(data["rates"])))
            else:
                self.ctx.send(u"⚠️ 刷新失败：所有源都拉不到，稍后再试")
            return None
        m = re.match(r"^(?:set|设|设置)\s+(\S+)$", low)
        if m:
            code = m.group(1).upper()
            if not re.fullmatch(r"[A-Z]{3}", code):
                self.ctx.send(u"币种要用三字码，如 <code>/fx set eur</code>")
                return None
            data = fx.load_rates()
            if data and code not in data["rates"]:
                self.ctx.send(u"不认识 %s。/fx 里的「展示货币」页有完整列表" % code)
                return None
            st = fx.get_settings()
            st["target"] = code
            fx.save_settings(st)
            self.ctx.send(u"✅ 默认目标币已设为 %s（%s）" % (code, fx.cn_name(code)))
            return None

        # ---- 换算（同消息路径）----
        q = fx.parse_query_ex(arg)
        if not q:
            self.ctx.send(u"没看懂。/fx 看菜单，或 <code>/fx 100 usd cny</code>")
            return None
        self._reply(q["amount"], q["frm"], q["to"], arg, q["expr"])
        return None

    # ------------------------------------------------------------- 内部
    def _reply(self, amount, frm, to, text="", expr=None):
        r = self._build_reply(amount, frm, to, text, expr)
        if r:
            self.ctx.send(r[0], buttons=r[1])

    def _build_reply(self, amount, frm, to, text="", expr=None):
        """构建换算结果 (HTML, buttons)。无法换算返回 None（提示已直接发给用户）。"""
        chat_id = self.ctx.chat_id
        data = fx.load_rates()
        if not data:
            self.ctx.send(u"⚠️ 汇率暂时取不到（网络问题？稍后再试）")
            return None
        rates = data["rates"]
        crypto_off_btn = [[{"text": u"🪙 一键开启加密货币换算",
                            "callback_data": "%s:cryptoon" % _CB}]]
        if frm not in rates:
            if frm in fx.CRYPTO_NAMES:
                _PENDING_CRYPTO[chat_id] = (amount, frm, to, text, expr)
                self.ctx.send(u"🪙 加密货币换算当前是关闭的，点下面按钮直接出结果",
                              buttons=crypto_off_btn)
                return None
            sug = _suggest(frm, fx.known_codes(data))
            self.ctx.send(u"不认识 %s%s" % (
                frm, u"（是想说 %s 吗？）" % u" / ".join(sug) if sug else u""))
            return None
        if isinstance(to, list):            # 多目标：1mjrbxjpcny → 1 USD → JPY/SGD/CNY
            unknown = [c for c in to if c not in rates]
            if unknown:
                btn = crypto_off_btn if any(c in fx.CRYPTO_NAMES for c in unknown) else None
                self.ctx.send(u"不认识 %s。/fx 的「展示货币」页有完整列表"
                              % u"、".join(unknown), buttons=btn)
                return None
            targets = [c for c in to if c != frm]
            if not targets:
                self.ctx.send(u"目标和源是同一种货币，不用换算 😄")
                return None
            return (_fmt_targets(amount, frm, targets, data, expr), None)
        if to is not None and to == frm:
            return (u"%s %s %s（%s）—— 同一种货币，不用换算 😄\n"
                    u"想换成别的，比如发 <code>%s %s usd</code>" % (
                        fx.fmt_amt(amount), fx.flag(frm) or u"　",
                        fx.cn_name(frm), frm, fx.fmt_amt(amount), frm.lower()), None)
        if to is not None:
            if to not in rates:
                if to in fx.CRYPTO_NAMES:
                    _PENDING_CRYPTO[chat_id] = (amount, frm, to, text, expr)
                    self.ctx.send(u"🪙 目标币是加密货币，但换算开关是关的，点下面按钮直接出结果",
                                  buttons=crypto_off_btn)
                    return None
                self.ctx.send(u"不认识目标币 %s。/fx 的「展示货币」页有完整列表" % to)
                return None
            hint = fx.euro_country_hint(text) if "EUR" in (frm, to) else None
            out = _fmt_pair(amount, frm, to, data, expr)
            if hint:
                out += u"\n%s" % hint
            return (out, None)
        # 未指定目标：按展示货币出；没勾选的引导去设置
        st = fx.get_settings()
        if not st["display"]:
            self.ctx.send(_SETUP_PROMPT,
                          buttons=[[{"text": u"🪙 去勾选展示货币",
                                     "callback_data": "%s:cur:page:0" % _CB}]])
            return None
        out, _multi = _fmt_multi(amount, frm, data, expr)
        hint = fx.euro_country_hint(text) if frm == "EUR" else None
        if hint:
            out += u"\n%s" % hint
        return (out, None)
