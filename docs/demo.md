# 🧪 示例模块（demo）

[← 返回 README](../README.md) · [🛠 模块开发规范](MODULE_GUIDE.md)

`modules/demo.py` 是一个**最小可参考的模块实现**，默认不启用。
想开发自己的模块，先读它——核心接口都用到了，总共不到一百行。

## 功能

| 命令 | 作用 |
|---|---|
| `/ping` | 回复 `pong 🏓`（验证模块已加载） |
| `/echo <文本>` | 原样复读你发的文本 |
| 包含「你好」的消息 | 打招呼（演示 `on_message`） |

## 启用

```bash
# 编辑 data/modules.json，enabled 里加 "demo"
sudo systemctl restart unmi_TGtool
```

或用 `/modules` 面板点击启用。

## 它演示了什么

```python
from core.base import Module, PASS

class Plugin(Module):
    name = "demo"                                   # 模块名（注册表识别用）
    version = "1.0.0"
    description = "示例模块（/ping /echo）"

    def on_start(self):
        self.ctx.log.info("demo 模块已启动")         # 生命周期：模块加载后

    def on_command(self, cmd, args, chat_id):
        if cmd == "ping":
            return "pong 🏓"                        # 返回字符串 = 直接回复
        if cmd == "echo":
            return "你说：<code>%s</code>" % (args or "（空）")
        return PASS                                 # 不认识的命令交给下一个模块

    def on_message(self, text, chat_id):
        if "你好" in text:
            return "你好！我是 demo 模块"
        return False                                # 普通消息不处理
```

要点：

1. **导出 `Plugin(Module)` 类**——注册表按这个名字发现模块；
2. 类属性 `name / version / description` 是元信息——必填，缺了会加载失败；
3. `on_command` / `on_message` **返回字符串 = 直接回复给用户**；返回 `PASS`（命令）/`False`（消息）= 不处理，传给下一个模块；
4. 返回 `(文本, 键盘)` 元组可以带内联按钮（参考 calc 模块）；
5. `self.ctx` 是框架注入的上下文（`send` / `edit` / `answer` / `delete` / `log`），需要更复杂的回复方式时用它。

## 下一步

- 完整接口、生命周期、配置读写、依赖声明 → **[模块开发规范](MODULE_GUIDE.md)**
- 复杂模块的组织方式 → 看 `modules/calc/`（engine.py 与界面分离 + 237 条自测）
