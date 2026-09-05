# -*- coding: utf-8 -*-
"""模块注册表 —— 统一负责模块的发现、校验、加载与生命周期。

主程序只跟这里打交道，不再直接 import modules.*，好处是：

  · 新增模块不用改 main.py，丢进 modules/ 再写进 enabled 列表即可
  · 模块写错（没继承 Module、缺元信息、重名、依赖缺失）会被拦下来并说明原因，
    不会带着半截状态启动，也不会把别的模块拖垮
  · 生命周期（on_start / on_stop）由注册表统一驱动，模块不用关心调用时机

模块两种摆放方式都支持：
    modules/demo.py          单文件模块（简单功能）
    modules/calc/__init__.py 包模块（有内部实现文件，如 calc/engine.py）
"""
import importlib
import os

from . import log as _log
from .base import Module

_LOG = _log.get("registry")

MODULES_PKG = "modules"
PLUGIN_ATTR = "Plugin"
REQUIRED_META = ("name", "version", "description")


# ---------------------------------------------------------------------------
# 发现
# ---------------------------------------------------------------------------

def _candidates():
    """列出 modules/ 下所有模块 id（文件名或包名），按名字排序，排除私有项。"""
    pkg = importlib.import_module(MODULES_PKG)
    root = os.path.dirname(os.path.abspath(pkg.__file__))
    out = []
    for entry in sorted(os.listdir(root)):
        if entry.startswith(("_", ".")):
            continue
        full = os.path.join(root, entry)
        if os.path.isdir(full):
            if os.path.isfile(os.path.join(full, "__init__.py")):
                out.append(entry)
        elif entry.endswith(".py") and entry != "__init__.py":
            out.append(entry[:-3])
    return out


def get_plugin(mod_id):
    """导入模块并取出 Plugin 类，顺带校验接口是否满足最低约定。

    任何不合规都抛异常，由调用方决定是记日志跳过还是直接失败。
    """
    mod = importlib.import_module("%s.%s" % (MODULES_PKG, mod_id))
    cls = getattr(mod, PLUGIN_ATTR)
    if not (isinstance(cls, type) and issubclass(cls, Module)):
        raise TypeError("%s 必须是 core.base.Module 的子类" % PLUGIN_ATTR)
    for key in REQUIRED_META:
        if not getattr(cls, key, None):
            raise ValueError("类属性 %s 不能为空" % key)
    return cls


def discover():
    """扫描 modules/ 下所有模块，返回元信息列表（不实例化，不触发业务逻辑）。

    每项：{"id", "name", "version", "description", "commands", "requires", "ok", "error"}
    ok=False 的项 error 里有原因，供面板/日志展示，方便排查装坏的模块。
    """
    out = []
    for mod_id in _candidates():
        info = {"id": mod_id, "name": mod_id, "version": "?", "description": "",
                "commands": [], "requires": [], "ok": False, "error": ""}
        try:
            cls = get_plugin(mod_id)
            info["name"] = str(cls.name)
            info["version"] = str(cls.version)
            info["description"] = str(cls.description)
            info["commands"] = list(getattr(cls, "commands", None) or [])
            info["requires"] = list(getattr(cls, "requires", None) or [])
            info["ok"] = True
        except Exception as e:  # noqa: BLE001  扫描阶段任何坏模块都不该中断整个扫描
            info["error"] = "%s: %s" % (type(e).__name__, e)
        out.append(info)
    return out


# ---------------------------------------------------------------------------
# 加载与生命周期
# ---------------------------------------------------------------------------

class Registry(object):
    """按 enabled 列表加载模块，并驱动 on_start / on_stop。

    enabled 的顺序就是消息分发优先级：靠前的模块先被问到。
    """

    def __init__(self, ctx):
        self.ctx = ctx
        self.modules = []       # 已加载的模块实例，顺序 = 分发优先级
        self.by_name = {}       # 声明的模块名 -> 实例（依赖检查用）
        self.skipped = []       # [(id, 原因)] 没加载成的，启动日志里要能看到

    def load(self, enabled):
        """按 enabled 顺序实例化模块。单个模块出问题只跳过它，不影响其它模块。"""
        for mod_id in enabled:
            try:
                cls = get_plugin(mod_id)
            except Exception as e:  # noqa: BLE001
                self.skipped.append((mod_id, "加载失败（%s）" % e))
                continue

            name = getattr(cls, "name", mod_id)
            if name in self.by_name:
                self.skipped.append((mod_id, "模块名重复：%s" % name))
                continue

            # 依赖必须在自己之前加载（enabled 列表里排在前面）
            requires = list(getattr(cls, "requires", None) or [])
            missing = [d for d in requires if d not in self.by_name]
            if missing:
                self.skipped.append(
                    (mod_id, "依赖未满足：%s（需在 enabled 里排在本模块之前）" % "、".join(missing)))
                continue

            try:
                inst = cls(self.ctx)
            except Exception as e:  # noqa: BLE001
                self.skipped.append((mod_id, "初始化失败（%s）" % e))
                continue

            self.modules.append(inst)
            self.by_name[name] = inst

        for mod_id, why in self.skipped:
            _LOG.error("模块 %s 未加载：%s", mod_id, why)
        for m in self.modules:
            _LOG.info("模块就绪: %s v%s（%s）", m.name, m.version, m.description)
        return self.modules

    def start(self):
        """逐个 on_start，单个抛异常不影响其它模块。"""
        for m in self.modules:
            try:
                m.on_start()
            except Exception as e:  # noqa: BLE001
                _LOG.error("模块 %s.on_start 异常: %s", m.name, e)

    def stop(self):
        """逐个 on_stop（服务退出前）。倒序停止，依赖方先停。"""
        for m in reversed(self.modules):
            try:
                m.on_stop()
            except Exception as e:  # noqa: BLE001
                _LOG.error("模块 %s.on_stop 异常: %s", m.name, e)
