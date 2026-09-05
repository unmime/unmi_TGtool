# 🧰 unmi_TGtool — 自托管 Telegram 工具集

> **English version: [README_EN.md](README_EN.md)**

**unmi_TGtool** 是一个自托管的 Telegram 工具集外壳：**零第三方依赖**（纯 Python 标准库），
自带消息轮询，往里挂什么工具就有什么功能。拷到任意一台有 Python 3.6+ 的 Linux 机器上，一条命令就能跑。

## 名字怎么来的

| 层次 | 命名 | 例子 |
|---|---|---|
| 项目（仓库 / 安装目录） | `unmi_TGtool` | 服务 `unmi_TGtool`、目录 `/opt/unmi_TGtool`、env `/etc/unmi_TGtool.env` |
| 功能脚本 | **一个功能一个名字** | 计算器就是 `TGcalcbot.py` |
| 模块 | 各用各的名字 | 计算器核心 `calc.py`，不叫 `unmi_TGtool_calc.py` |

**命名约定**：每个独立 bot 用自己的名字 `TG<功能>bot.py`，互不牵连、按需选装。
本仓库是其中的计算器 `TGcalcbot.py`。

## 当前内置模块

**计算器 `calc.py`** —— 直接发 `66*98` 就出结果，还会给出中文读法和
**符合央行规范的会计大写金额**（`陆仟肆佰陆拾捌元整`），结果分两段，点哪段复制哪段。

## 一分钟安装

```bash
# 1) 去 @BotFather 建 bot，拿到 token；拿到你自己的 chat id（可以先给 bot 发条消息）
# 2) 在目标机器上：
tar xzf unmi_TGtool.tar.gz && cd unmi_TGtool
sudo ./install.sh "<BOT_TOKEN>" "<CHAT_ID>"
```

装完自动注册 systemd 服务 `unmi_TGtool` 并启动。之后给 bot 发 `66*98` 就有结果。

不想立刻启动（演练 / 稍后手动切）：

```bash
sudo ./install.sh "<BOT_TOKEN>" "<CHAT_ID>" --no-start
sudo systemctl start unmi_TGtool     # 想启动时再启动
```

## ⚠️ 最重要的一条：一个 token 只能轮询一次

Telegram 的 `getUpdates` 是**独占消费**的。同一个 bot token 只能有一个进程在轮询，
两个进程同时跑会**互相抢消息**（告警、计算结果都会随机丢一半）。

所以：

| 场景 | 做法 |
|---|---|
| 机器上没别的 bot 在跑 | 直接装 |
| 已有别的程序在用**同一 token** 轮询 | **不要装**，或换一个独立 bot token |
| 想多套功能各自独立 | 去 @BotFather 多建几个 bot，各用各的 token |

`install.sh` 开头会 `pgrep` 检测本机是否已有疑似轮询进程并提示确认。

## 功能

| 能力 | 示例 |
|---|---|
| 直接发算式 | `66*98` → `66*98=6468｜6468｜` |
| 结果两段可复制 | 点左边复制整段，点右边只复制结果 |
| 中文读法 | `自然读法：六千四百六十八` |
| 会计大写（央行规范） | `会计大写：陆仟肆佰陆拾捌元整` |
| 设置面板 `/calc` | 小数位 1~6 / 显示格式 / 结果转换 / 连续计算 |
| 连续计算（默认关） | `3+3`=6，接着发 `+3` → `6+3=9`；`/00` 退出；3 分钟自动退出 |
| 函数与常量 | `sqrt` `abs` `round` `ln` `lg` `log` `sin` `cos` `tan` `factorial` `gcd` `lcm` `max` `min`、`pi` `e` `tau` `phi` |
| 安全 | AST 白名单求值，不用 `eval`；`__import__`/`open`/属性访问全部拒绝 |

完整能力见 `calc.py` 顶部说明。

## 文件

| 文件 | 层次 | 说明 |
|---|---|---|
| `TGcalcbot.py` | 外壳 | 主程序：轮询、消息分发、回调、命令注册。**只依赖同目录的模块** |
| `calc.py` | 模块 | 计算器核心（AST 白名单求值 + 中文数字 + 设置模型） |
| `selftest_calc.py` | 模块自测 | calc.py 的 196 条（安全逃逸 / 畸形输入 / 央行规范对照 / 精度 / 面板） |
| `selftest_TGcalcbot.py` | 外壳自测 | TGcalcbot.py 的 15 条，**mock 掉网络层，不会连真实 API** |
| `install.sh` | 外壳 | 一键安装（带 token 冲突检查，支持 `--no-start`） |
| `unmi_TGtool.service` | 外壳 | systemd 单元（EnvironmentFile 读配置，Restart=always） |

## 往里加新模块

保持「外壳一个名，模块各叫各的」：

```
TGcalcbot.py          外壳：收到消息 → 判断该交给谁
├── calc.py          计算器（现有）
├── ts.py            时间戳转换（将来）
├── cidr.py          子网计算（将来）
└── selftest_*.py    每个模块配一个同名自测
```

加一个模块的步骤：写 `<功能>.py` → 在 `TGcalcbot.py` 的消息处理里加一条分发 →
写 `selftest_<功能>.py` → 跑全部自测。外壳不用改名字，模块也不用迁就外壳。

## 安装后的位置

| 路径 | 说明 |
|---|---|
| `/opt/unmi_TGtool/` | 程序目录（设置文件 `calc_settings.json` 也在里，可写） |
| `/etc/unmi_TGtool.env` | token 与 chat id，权限 600 |
| `systemd: unmi_TGtool` | 服务 |

## 运维

```bash
sudo systemctl status  unmi_TGtool
sudo journalctl -u unmi_TGtool -f        # 实时日志
sudo systemctl restart unmi_TGtool        # 改完代码必须重启

cd /opt/unmi_TGtool
sudo python3 selftest_calc.py                   # 核心 196 条自测
sudo python3 selftest_TGcalcbot.py                    # 消息链路 15 条（离线）
sudo python3 TGcalcbot.py --dry-run                   # 不联网自检
sudo cat calc_settings.json                     # 当前设置
```

## 卸载

```bash
sudo systemctl stop unmi_TGtool
sudo systemctl disable unmi_TGtool
sudo rm -f /etc/systemd/system/unmi_TGtool.service /etc/unmi_TGtool.env
sudo rm -rf /opt/unmi_TGtool
sudo systemctl daemon-reload
```

## 已验证环境

| 架构 / 系统 / Python | 结果 |
|---|---|
| arm64 / Ubuntu 24.04 / Python 3.12 | 通过 |
| x86_64 / Debian 13 / Python 3.13 | 通过 |

自测：核心 **196 条** + 消息链路 **15 条**（离线 mock）全绿。

## 许可证

MIT —— 随便用、随便改，不用打招呼。
