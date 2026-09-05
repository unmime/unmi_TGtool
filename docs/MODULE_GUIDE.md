# 模块开发规范（unmi_TGtool v1.0.0.0）

给第三方开发者的模块接入手册。读完这篇，你不需要改 `main.py` 任何一行，
就能给自己的 bot 加一个新功能。

**设计原则**：主程序不认识任何具体模块。它只按 `enabled` 列表去 `modules/` 里找模块、
按统一接口问「这条消息你管不管」，谁先举手给谁。模块崩了自己扛，不拖累别人。

---

## 1. 目录结构

```
main.py                 统一入口：初始化 / 装配 / 调度 / 轮询（不含业务逻辑）
core/                   框架内核，模块只依赖它，不要改
├── base.py             Module 基类 + PASS + JSON 读写工具
├── registry.py         模块注册表：发现 / 校验 / 加载 / 生命周期
├── config.py           配置加载（环境变量 + data/modules.json）
├── tg.py               Telegram API 封装（BotContext）
└── log.py              统一日志
modules/                功能模块，一个模块一项
├── calc/               包形态（有内部实现文件时用这个）
│   ├── __init__.py     必须：导出 Plugin
│   └── engine.py       求值核心，不依赖框架，可单独跑自测
└── demo.py             单文件形态（简单功能用这个）
data/                   运行数据（不进代码仓库）
├── modules.json        启用哪些模块、顺序是什么
└── <模块名>.json        各模块自己的配置
selftest_public.py      框架 + 模块自测（离线）
selftest_calc.py        计算器核心自测（203 条）
docs/MODULE_GUIDE.md    本文
```

模块有两种摆放方式，**注册表都认**：

| 形态 | 结构 | 适用场景 |
|---|---|---|
| 单文件 | `modules/foo.py` | 逻辑简单，一个文件写得完 |
| 包 | `modules/foo/__init__.py` + 若干内部文件 | 有实现文件、要拆分子模块、要带资源 |

两条硬性约定：

1. 文件名（包目录名）就是**模块 id**，只能含字母数字和下划线，**不能以下划线开头**
   （下划线开头的文件会被当成内部文件跳过，比如 `modules/calc/engine.py` 不会被当模块）。
2. 包形态必须在 `__init__.py` 里导出 `Plugin`。

---

## 2. 接口约定

模块就是一个继承 `core.base.Module` 的类，导出名**必须叫 `Plugin`**。

```python
# -*- coding: utf-8 -*-
"""一句话说明这个模块干什么。"""
from core.base import Module, PASS


class Plugin(Module):
    name = "mymodule"                 # 必填，全局唯一，用于日志/配置/依赖声明
    version = "1.0.0"                 # 必填，语义化版本
    description = "一句话说明"         # 必填，/help 和 --modules 会展示
    requires = []                     # 可选，依赖的其它模块的 name
    commands = []                     # 可选，贡献给 Telegram 菜单的命令

    def on_start(self):        pass   # 所有模块加载完后调用（起线程、预热）
    def on_stop(self):         pass   # 服务退出前调用（systemd stop/restart 触发）

    def on_message(self, text, chat_id):        # 非命令消息
    def on_command(self, cmd, args, chat_id):   # /命令
    def on_callback(self, data, cb_id, message) # 内联按钮回调
    def on_report(self, kind):                  # 定时报告
```

`name` / `version` / `description` 三者**缺一不可**，空值会在加载时被拦下并写进日志。

### 2.1 生命周期

```
启动    __init__(ctx) → Registry.start() 逐个 on_start()
运行    事件来了按 enabled 顺序逐个问，第一个接管的说了算
停止    SIGTERM/SIGINT → Registry.stop() 倒序逐个 on_stop()
```

- `on_start()` 里可以起后台线程，但请设成 **daemon**，否则进程退不干净。
- `on_stop()` 只在收到 `SIGTERM`/`SIGINT` 时触发（`systemctl stop/restart` 发的就是它）。
  要在这收尾的（关文件、停线程）就写这里。**别假设它一定会被调用**——断电不会。

### 2.2 返回值语义（最容易搞错的地方）

| 方法 | 返回 | 含义 |
|---|---|---|
| `on_message(text, chat_id)` | `True` | 我处理了，别再问后面的模块 |
| | `False` | 不是我的，继续问下一个 |
| `on_command(cmd, args, chat_id)` | `PASS` | 这个命令不归我管，继续问下一个 |
| | 字符串 | 我处理完了，把这段原样发给用户 |
| | `None` | 我处理完了，但不需要回复（自己 ctx.send 过了） |
| `on_callback(data, cb_id, message)` | `True` | 我处理了 |
| | `False` | 继续问下一个 |
| `on_report(kind)` | — | 返回值不care，要发东西就自己 `ctx.send` |

`cmd` 已经去掉前导 `/` 和 `@botname`，并转小写；`args` 是剩余部分。

### 2.3 上下文 `self.ctx`

不用自己碰 `urllib`，全部走 `ctx`：

```python
self.ctx.send(text, buttons=None, silent=False, chat_id=None)  # 发消息
self.ctx.edit(chat_id, message_id, text, buttons=None)         # 改消息
self.ctx.answer(cb_id, text)                                   # 应答回调（去掉转圈）
self.ctx.delete(chat_id, message_id)                           # 删消息
self.ctx.log.info(...)                                         # 日志
```

要点：

- `send` 默认按 **HTML** 解析，用户输入必须过 `core.base.esc()` 转义，否则一个 `<` 就能让
  Telegram 报 400，整条发不出去。
- 单条上限 4096 字符，超了框架会自动截断，但**你自己最好先控制长度**。
- `buttons` 是二维数组：`[[{"text": "按钮", "callback_data": "foo:1"}]]`。
- 代理走环境变量 `https_proxy`，框架自动跟随，模块不用管。

### 2.4 模块自己的配置

别自己拼路径、别往代码目录写文件（一键更新会把代码目录整个换掉）。

```python
cfg = self.load_config()          # 读，文件不存在/损坏返回 {}
cfg["key"] = "value"
self.save_config(cfg)             # 写，原子写（先临时文件再 os.replace）
```

文件落在 `DATA_DIR/<模块名>.json`，跟代码分离。

### 2.5 命令菜单

```python
commands = [{"command": "calc", "description": "🧮 计算器设置"}]
```

启动时主程序汇总所有已启用模块的 `commands` 一起注册。**`setMyCommands` 是全量覆盖**，
所以千万别在别处单独调它，会把别人的命令顶掉。框架会自动追加 `/help`。

---

## 3. 模块注册方式

### 3.1 写好后启用

编辑 `data/modules.json`：

```json
{"enabled": ["calc", "mymodule"]}
```

**数组顺序 = 分发优先级**：靠前的先被问到。两个模块抢同一个命令时，前面的赢。
也可以用环境变量临时覆盖（优先级更高，调试用）：

```bash
ENABLED_MODULES=calc,demo python3 main.py --dry-run
```

### 3.2 声明依赖

如果模块 B 要用到 A 提供的东西：

```python
class Plugin(Module):
    name = "b"
    requires = ["a"]        # 填对方的 name，不是文件名
```

加载时注册表会检查：依赖没在 `enabled` 里、或排在自己后面 → **跳过 B 并记日志**，
不会带着半截状态启动。所以 `enabled` 里 A 必须排在 B 前面。

### 3.3 自检命令

```bash
python3 main.py --modules     # 列出 modules/ 下所有模块及状态（坏模块会显示原因）
python3 main.py --dry-run     # 按 enabled 实际加载一遍，不开始轮询
```

`--modules` 会把没加载成的模块原因直接打出来（`缺少类属性 name`、
`Plugin 必须是 Module 的子类` 之类），排查装坏的模块先看这个。

### 3.4 坏模块会怎样

注册表对下面这些情况一律**跳过该模块 + 记日志**，其它模块照常工作：

- 导入就抛异常（语法错、缺第三方库）
- 没导出 `Plugin`，或 `Plugin` 不是 `Module` 的子类
- `name` / `version` / `description` 缺失或为空
- 与其它已加载模块**重名**
- `requires` 里的依赖没加载

---

## 4. 依赖管理

### 4.1 第三方库

**项目承诺零第三方依赖**（纯 Python 标准库）。这是刻意的：
一键安装脚本不装 pip 包，用户拿到就能跑，不会因为某个依赖装不上而卡住。

所以：

- 新模块**只用标准库**。`urllib` / `json` / `re` / `math` / `fractions` / `ast` / `threading` 随便用。
- 确实需要第三方库时，在模块里**延迟 import + 优雅降级**，并写进模块 docstring：

  ```python
  def on_start(self):
      try:
          import requests
      except ImportError:
          self.ctx.log.error("缺 requests，本模块功能不可用")
          return
  ```

  绝不能让 `import` 失败导致整个 bot 起不来。

### 4.2 模块之间

用 `requires` 声明（见 3.2）。依赖方向必须是单向的，环形依赖注册表不检测，
但会表现为「两个都加载不了」，看到这种日志就说明顺序写反了。

### 4.3 运行期依赖

- **数据目录**：一律用 `self.ctx.data_dir`，不要硬编码路径。
- **网络**：走 `self.ctx`，不要自己开 `urllib`（代理和超时会不一致）。

---

## 5. 代码提交流程

### 5.1 编码规范

| 项 | 要求 |
|---|---|
| 编码 | 文件头 `# -*- coding: utf-8 -*-` |
| 兼容性 | Python 3.6+ 语法（要能在 Debian 老版本上跑） |
| 缩进 | 4 空格，不用 tab |
| 命名 | 类名 `PascalCase`，函数/变量 `snake_case`；内部用的加 `_` 前缀 |
| 文档字符串 | 每个模块、每个公开方法都要有，中文 |
| 注释 | 写「为什么」不写「做什么」；非显而易见的坑必须注释清楚 |
| 日志 | 用 `self.ctx.log`，不要 `print`（会污染 stdout） |

### 5.2 必须做的检查

```bash
python3 -m py_compile modules/你的模块.py     # 语法
python3 selftest_public.py                    # 框架回归（离线，含注册表用例）
python3 selftest_calc.py                      # 计算器回归（如改到公共逻辑）
python3 main.py --modules                     # 你的模块能被发现、状态 OK
python3 main.py --dry-run                     # 能实际加载
```

**给自己的模块写自测**，加进 `selftest_public.py` 的用例列表（照现有 `check(名称, 实际, 期望)`
的写法）。自测必须**离线可跑**、**不碰真实用户数据**（用 `tempfile.mkdtemp()`）。

### 5.3 提交

1. 分支命名：`feat/模块名`、`fix/问题简述`
2. 提交信息：一行说明「用户视角的变化」，不写实现细节流水账
3. 一个 PR 只做一件事
4. PR 里说明：新增/改了哪个模块、是否需要改 `modules.json`、
   自测结果（通过几条）、有没有破坏性变更

### 5.4 版本号

模块用**语义化版本**：

- 修 bug、内部重构 →  patch（`1.0.0` → `1.0.1`）
- 新增能力、向后兼容 → minor（`1.0.0` → `1.1.0`）
- 改接口、删功能、不兼容 → major（`1.0.0` → `2.0.0`）

模块版本和框架版本独立演进，互不影响。

---

## 6. 完整示例

最小可用模块（`modules/echo.py`）：

```python
# -*- coding: utf-8 -*-
"""回声模块 —— 把用户的话原样送回去。

启用：data/modules.json 的 enabled 里加 "echo"
"""
from core.base import Module, PASS, esc


class Plugin(Module):
    name = "echo"
    version = "1.0.0"
    description = "回声（/echo 你要说的话）"
    commands = [{"command": "echo", "description": "🔊 回声"}]

    def on_command(self, cmd, args, chat_id):
        if cmd != "echo":
            return PASS                       # 不归我管
        # 用户输入必须转义：直接拼进 HTML 消息，一个 < 就能让整条发不出去
        return "你说：<code>%s</code>" % esc(args or "（空）")
```

更完整的参考：`modules/demo.py`（单文件）、`modules/calc/`（包形态，带设置面板和按钮回调）。
