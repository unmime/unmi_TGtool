# 🧰 unmi_TGtool — 开箱即用的自托管 Telegram 工具集

> 计算器 + 汇率换算 + 可插拔模块框架。零依赖（纯 Python 标准库），一台 VPS 五分钟跑起来。

![version](https://img.shields.io/badge/version-v1.1.0.0-blue) ![license](https://img.shields.io/badge/license-MIT-green) ![python](https://img.shields.io/badge/python-3.10%2B-informational)

---

## ⚡ 一键安装（推荐）

用 `root` 执行下面**一条命令**，自动完成下载、安装、配置，装完直接能用：

```bash
bash <(curl -sL https://raw.githubusercontent.com/unmime/unmi_TGtool/main/unmi.sh)
```

装完即用。以后随时敲 `unmi` 回到控制台面板（添加/开关/代理/一键更新/卸载都在里面）。
---

## 📖 开发背景

这是我为自己日常小众需求写的小工具：想在 Telegram 里随手算数、查汇率、
看看加密货币行情，找不到合适的现成方案，就自己写了一个。
顺手做成了模块化结构，自己用着方便，也开源出来给有类似需求的朋友直接用。
以后还会陆续添加一些小功能。

---

## 🤖 开始使用

### 第 1 步：创建机器人，拿到 Token

1. 在 Telegram 里找 **[@BotFather](https://t.me/BotFather)**，发送 `/newbot`；
2. 按提示给 bot 起名字（显示名）和用户名（必须以 `bot` 结尾）；
3. 创建成功后 BotFather 会发给你一段 **Token**，形如：
   `1234567890:AAH8xXXXXXXXXXXXXXXXXXXXXXXXXXXXX` —— 这就是你的 bot Token，别泄露。

### 第 2 步：拿到你的 Chat ID

1. 在 Telegram 里找 **[@userinfobot](https://t.me/userinfobot)**，随便发一条消息；
2. 它会回你的 `Id`，一串数字（如 `8877120599`）—— 这就是你的 Chat ID。

> ⚠️ 出于安全考虑，建议只给自己用：创建 bot 后在 @BotFather 发 `/setprivacy`，
> 并在安装完成后用 bot 给你发一条消息（面板安装时会自动发测试消息），之后 bot 只响应你的 Chat ID。

### 第 3 步：一键安装

服务器上以 root 执行：

```bash
bash <(curl -sL https://raw.githubusercontent.com/unmime/unmi_TGtool/main/unmi.sh)
```

按 `A` 添加机器人，依次粘贴 **Token** 和 **Chat ID**，起个备注名——完成。
面板会自动写配置、注册 systemd 服务、启动 bot，并发一条测试消息给你。

### 第 4 步：验证

给你的 bot 发：

```
66*9/8
```

看到结果就说明装好了。接下来发 `100usd`、`大饼`、`22人民币` 试试汇率换算。

<details>
<summary>手动安装（备选，不界面党可展开）</summary>

```bash
# 1) 下载
git clone https://github.com/unmime/unmi_TGtool.git /opt/unmi_TGtool
# 或： curl -LO https://github.com/unmime/unmi_TGtool/releases/latest/download/unmi_TGtool.tar.gz

# 2) 解压安装（tar 包带顶层目录 unmi_TGtool/）
sudo bash /opt/unmi_TGtool/install.sh "<BOT_TOKEN>" "<CHAT_ID>"

# 3) 去 Telegram 给 bot 发 66*98
```
</details>

---

## ✨ 功能模块

每个模块都有独立介绍页，点标题进入：

| 模块 | 一句话介绍 | 详细文档 |
|---|---|---|
| 🧮 **计算器 calc** | 算式、中文读法、会计大写、连续计算、与汇率联动 | **[docs/calc.md](docs/calc.md)** |
| 💱 **汇率换算 fx** | 法币 + 加密货币，中英文名/黑话/ISO 全认识，多币种一发出 | **[docs/fx.md](docs/fx.md)** |
| 🧪 **示例 demo** | 模块开发的最小参考实现（/ping /echo） | **[docs/demo.md](docs/demo.md)** |
| 🛠 **模块框架** | 可插拔架构：坏模块隔离、依赖声明、独立配置、完整生命周期 | **[docs/MODULE_GUIDE.md](docs/MODULE_GUIDE.md)** |

用 `/modules` 随时开关任何一个模块，互不影响。

---

## 🧮 计算器（calc）速览

```text
66*9/8        → 74.25（支持 + - * / ^ % // 括号）
1,500+1       → 千分位、小数都认
+56           → 连续计算：上次结果 + 56
66*9/8 后补 mj → 上次结果直接换算成美元
```

设置面板 `/calc`：小数位（1~6）、结果显示格式、中文读法/会计大写（独立开关）、
连续计算开关。命令：`/00` 退出连续计算、`/11` 开启连续计算。

👉 完整功能列表见 **[docs/calc.md](docs/calc.md)**

## 💱 汇率换算（fx）速览

```text
22人民币       → 中文名直接发
100usd        → 按展示单多币种换算
1mjrbxjpcny   → 美元→日元→人民币→加元 链式换算
大饼 / 0.5btc  → 加密货币（Binance/OKX 实时价）
100usd cny    → 指定目标换算
66*9/8mj      → 算式结果直接换汇率
```

菜单 `/fx`：展示货币管理（法币/加密分开）、汇率源切换（4 个法币源 + 3 个加密源）、
加密换算开关。汇率缓存：法币 1 小时、加密 5 分钟。

👉 完整功能列表见 **[docs/fx.md](docs/fx.md)**

---

## 🛠 开发者接入指南

unmi_TGtool 的核心是一个**可插拔模块框架**：主程序不认识任何具体模块，只按
`enabled` 列表去 `modules/` 里找模块、按统一接口问「这条消息你管不管」，谁先举手给谁。
模块崩了自己扛，不拖累别人——这也是"任何模块的开关都不影响其他功能"的架构保证。

### 三步接入一个新模块

| 步骤 | 做什么 |
|---|---|
| 1 | 写 `modules/mymodule.py`，导出 `Plugin(Module)` 类（最小参考：[docs/demo.md](docs/demo.md) 与 `modules/demo.py`） |
| 2 | `data/modules.json` 的 `enabled` 里加 `"mymodule"` |
| 3 | `sudo systemctl restart unmi_TGtool` —— 不用改 `main.py` 任何一行 |

### 接入规范

| 规范 | 说明 |
|---|---|
| 统一接口 | 实现 `on_message` / `on_command` / `on_callback` / `on_start` / `on_stop`，不需要的返回 `PASS` |
| 谁先举手给谁 | 模块按 `enabled` 顺序调度，处理了就返回 `True`，不处理返回 `False` 传给下一个 |
| 坏模块隔离 | 导入失败、缺元信息、重名、依赖缺失 → 跳过并日志说明，其它模块照常 |
| 依赖声明 | `requires = ["其他模块名"]`，加载时校验顺序，缺依赖不会带病启动 |
| 独立配置 | `self.load_config()` / `self.save_config()`，落在 `DATA_DIR/<模块名>.json`，原子写 |
| 异常隔离 | 每个方法调用都包 try/except，一个模块崩了不影响别人和整条消息流 |
| 引擎与界面分离 | 复杂逻辑放 `engine.py`（不依赖框架，可独立跑自测），`__init__.py` 只做适配 |
| 自测义务 | 交付模块请附带 `selftest_<模块名>.py`，参考 `selftest_calc.py`（237 条） |
| 开关独立 | 任何模块的启用/停用不得影响其它模块——框架已保证，模块自身也不要有跨模块副作用 |

完整接口说明、生命周期、消息/回调数据结构，见 **[docs/MODULE_GUIDE.md](docs/MODULE_GUIDE.md)**。

---

## ⚠️ 一个 token 只能有一个轮询进程

Telegram 的 `getUpdates` 是独占消费的，同一 token 跑两个进程会互相抢消息（各丢一半）。
多开请给每个机器人申请独立 bot token —— 面板添加时会查重并提示。

## 运维

```bash
sudo systemctl status  unmi_TGtool
sudo journalctl -u unmi_TGtool -f
sudo systemctl restart unmi_TGtool      # 改完代码必须重启

cd /opt/unmi_TGtool
sudo python3 selftest_public.py         # 框架 + 模块自测（离线，20 条）
sudo python3 selftest_calc.py           # 计算器核心（离线，237 条）
sudo python3 selftest_fx.py             # 汇率换算核心（离线，114 条）
sudo python3 main.py --modules          # 列出所有模块及状态（坏模块直接显示原因）
sudo python3 main.py --dry-run          # 按 enabled 实际加载一遍，不开始轮询
```

## 卸载

```bash
sudo systemctl stop unmi_TGtool && sudo systemctl disable unmi_TGtool
sudo rm -f /etc/systemd/system/unmi_TGtool.service /etc/unmi_TGtool.env
sudo rm -rf /opt/unmi_TGtool
sudo systemctl daemon-reload
```

想只删某一个机器人而保留面板，敲 `unmi` 进那个机器人的管理页选「5」即可。

## 已验证环境

arm64 / Ubuntu 24.04 / Python 3.12 · x86_64 / Debian 13 / Python 3.13

## 许可证

MIT —— 随便用、随便改，不用打招呼。
