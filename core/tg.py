# -*- coding: utf-8 -*-
"""Telegram API 封装（BotContext）。

模块不直接碰 urllib，全部走这里的 5 个方法。
这样以后换底层实现（比如加代理、改超时），模块零改动。
"""
import json
import urllib.error
import urllib.parse
import urllib.request

from . import log as _log

_LOG = _log.get("tg")


class BotContext(object):
    """传给每个模块的上下文：Telegram API + 配置 + 日志。"""

    def __init__(self, token, chat_id, data_dir):
        self.token = token
        self.chat_id = str(chat_id)
        self.data_dir = data_dir
        self.api_base = "https://api.telegram.org/bot%s" % token
        self.log = _log.get("ctx")

    # ------------------------------------------------------------------ API
    def api(self, method, params):
        # 兼容旧核心直接传 dict/list 的 reply_markup（原 JSON body 传输的写法），
        # 统一序列化成 JSON 字符串再走表单编码，否则 Telegram 400 解析失败
        params = {k: (json.dumps(v, ensure_ascii=False)
                      if isinstance(v, (dict, list)) else v)
                  for k, v in params.items()}
        data = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request("%s/%s" % (self.api_base, method),
                                     data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with urllib.request.urlopen(req, timeout=40) as resp:
                r = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            r = {"ok": False, "error": "HTTP %s: %s" % (e.code, e.read().decode("utf-8", "ignore")[:200])}
        except Exception as e:  # noqa: BLE001
            r = {"ok": False, "error": str(e)}
        if not r.get("ok") and method != "getUpdates":
            _LOG.warn("tg %s FAILED: %s", method, str(r)[:200])
        return r

    # ------------------------------------------------------------ 快捷方法
    def send(self, text, buttons=None, silent=False, chat_id=None):
        params = {"chat_id": chat_id or self.chat_id, "text": text,
                  "parse_mode": "HTML", "disable_web_page_preview": "true",
                  "disable_notification": "true" if silent else "false"}
        if buttons:
            params["reply_markup"] = json.dumps({"inline_keyboard": buttons},
                                                ensure_ascii=False)
        return self.api("sendMessage", params)

    def edit(self, chat_id, message_id, text, buttons=None):
        params = {"chat_id": chat_id, "message_id": message_id, "text": text,
                  "parse_mode": "HTML", "disable_web_page_preview": "true"}
        if buttons:
            params["reply_markup"] = json.dumps({"inline_keyboard": buttons},
                                                ensure_ascii=False)
        return self.api("editMessageText", params)

    def answer(self, cb_id, text):
        return self.api("answerCallbackQuery",
                        {"callback_query_id": cb_id, "text": text})

    def delete(self, chat_id, message_id):
        return self.api("deleteMessage",
                        {"chat_id": chat_id, "message_id": message_id})

    def get_updates(self, offset, timeout=25):
        req = urllib.request.Request(
            "%s/getUpdates" % self.api_base,
            data=urllib.parse.urlencode(
                {"timeout": timeout, "offset": offset,
                 "allowed_updates": '["callback_query","message"]'}).encode(),
            method="POST")
        with urllib.request.urlopen(req, timeout=timeout + 10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def setup_commands(self, cmds, description):
        self.api("setMyCommands", {"commands": json.dumps(cmds, ensure_ascii=False)})
        self.api("setMyDescription", {"description": description})
