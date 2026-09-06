# -*- coding: utf-8 -*-
"""配置加载。

来源：环境变量（必选项）+ data/modules.json（模块开关，可选）。

  TG_BOT_TOKEN     bot token（必须）
  TG_CHAT_ID       接收消息的 chat id（必须）
  DATA_DIR         运行时数据目录（默认 ./data）
  ENABLED_MODULES  逗号分隔的模块名，覆盖 modules.json（可选）

模块开关：enabled 列表控制加载哪些模块，顺序即分发优先级。
"""
import json
import os

from . import log as _log

_LOG = _log.get("config")

DEFAULT_DATA_DIR = "data"
MODULES_FILE = "modules.json"
DEFAULT_ENABLED = ["calc"]


class Config(object):
    def __init__(self, base_dir):
        self.base_dir = base_dir
        self.token = os.environ.get("TG_BOT_TOKEN", "")
        self.chat_id = os.environ.get("TG_CHAT_ID", "")
        self.data_dir = os.environ.get(
            "DATA_DIR", os.path.join(base_dir, DEFAULT_DATA_DIR))
        self.enabled = self._load_enabled()

    def _load_enabled(self):
        raw = os.environ.get("ENABLED_MODULES", "").strip()
        if raw:
            return [m.strip() for m in raw.split(",") if m.strip()]
        path = os.path.join(self.data_dir, MODULES_FILE)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh) or {}
            enabled = data.get("enabled")
            if isinstance(enabled, list) and enabled:
                return [str(m) for m in enabled]
        except FileNotFoundError:
            _LOG.info("%s 不存在，用默认模块列表", path)
        except Exception as e:  # noqa: BLE001
            _LOG.warn("读取 %s 失败（%s），用默认列表", path, e)
        return list(DEFAULT_ENABLED)

    def check(self):
        """必选项校验，返回错误信息列表（空表示通过）。"""
        errs = []
        if not self.token:
            errs.append("缺少 TG_BOT_TOKEN")
        if not self.chat_id:
            errs.append("缺少 TG_CHAT_ID")
        if not self.enabled:
            errs.append("enabled 模块列表为空")
        return errs

    def modules_file(self):
        return os.path.join(self.data_dir, MODULES_FILE)

    def save_enabled(self, enabled):
        """把模块开关写回 modules.json 并更新内存（模块管理器用）。"""
        self.enabled = [str(m) for m in enabled]
        path = self.modules_file()
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"enabled": self.enabled}, fh,
                          ensure_ascii=False, indent=2)
        except Exception as e:                       # noqa: BLE001
            _LOG.error("写 %s 失败：%s", path, e)
