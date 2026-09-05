# -*- coding: utf-8 -*-
"""统一日志。

所有模块共用：前缀 [模块名]，走 stderr（systemd 会收进 journalctl）。
比各处裸 sys.stderr.write 好管理，也能统一改格式。
"""
import sys
import threading

_LOCK = threading.Lock()


class Log(object):
    def __init__(self, prefix):
        self.prefix = prefix

    def _write(self, level, msg):
        with _LOCK:
            sys.stderr.write("[%s] %s: %s\n" % (self.prefix, level, msg))

    def info(self, msg, *a):
        self._write("info", msg % a if a else msg)

    def warn(self, msg, *a):
        self._write("warn", msg % a if a else msg)

    def error(self, msg, *a):
        self._write("error", msg % a if a else msg)


def get(prefix):
    return Log(prefix)
