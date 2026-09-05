# 🧰 unmi_TGtool — 开箱即用的自托管 Telegram 工具集

> **English version: [README_EN.md](README_EN.md)**

**零第三方依赖**（纯 Python 标准库）。一个可插拔的 Telegram 工具集框架，
**默认装好就能当计算器用**，想加功能就往 `modules/` 里丢文件。

拷到任意一台有 Python 3.6+ 的 Linux 机器上，**一条命令，开箱即用**。

## ⚡ 一键安装（推荐）

用 `root` 执行下面**一条命令**，自动完成下载、安装、配置，装完直接能用：

```bash
bash <(curl -sL https://raw.githubusercontent.com/unmime/unmi_TGtool/main/unmi.sh)
```

过程中会提示你输入 **Bot Token** 和 **Chat ID**（去 @BotFather 建 bot 拿 token，
先给 bot 发条消息再拿 chat id），输完自动配置、启动，并**发一条测试消息**到你的 Telegram。

装完发 `66*98` 立刻得到 `66*98=6468｜6468｜`，外加中文读法和**符合央行规范的会计大写金额**
（`陆仟肆佰陆拾捌元整`）。结果分两段，点哪段复制哪段。

## 手动安装（备选）

```bash
# 1) 下载（二选一）
wget https://github.com/unmime/unmi_TGtool/releases/latest/download/unmi_TGtool.tar.gz
# 或： curl -LO https://github.com/unmime/unmi_TGtool/releases/latest/download/unmi_TGtool.tar.gz

# 2) 解压安装（tar 包带顶层目录 unmi_TGtool/）
tar xzf unmi_TGtool.tar.gz && cd unmi_TGtool
sudo ./install.sh "<BOT_TOKEN>" "<CHAT_ID>"

# 3) 去 Telegram 给 bot 发 66*98
```

装完自动注册并启动 systemd 服务 `unmi_TGtool`，开机自启、崩了自动拉起。

## 计算器内置功能

| 能力 | 示例 |
|---|---|
| 直接发算式 | `66*98` → `66*98=6468｜6468｜` |
| 结果两段可复制 | 点左边复制整段，点右边只复制结果 |
| 中文读法 | `自然读法：六千四百六十八` |
| 会计大写（央行规范） | `会计大写：陆仟肆佰陆拾捌元整` |
| 精确运算 | 全程 `Fraction`，`0.1+0.2` 就是 `0.3`，`2^64` 精确 |
| 设置面板 `/calc` | 小数位 1~6 / 显示格式 / 结果转换 / 连续计算 |
| 连续计算（默认关） | `3+3`=6，发 `+3` → `6+3=9`；`/00` 退出；3 分钟自动超时 |
| 函数与常量 | `sqrt` `abs` `round` `ln` `lg` `log` `sin` `cos` `tan` `factorial` `gcd` `lcm` `max` `min`、`pi` `e` `tau` `phi` |
| 安全 | AST 白名单求值，**不用 `eval`**；`__import__`/`open`/属性访问全部拒绝 |

## 可插拔框架

核心是 `main.py`（统一入口，不含业务）+ `modules/`（功能模块）。

```
main.py                  统一入口：初始化 / 注册 / 调度 / 轮询
core/                    框架内核（接口 / Telegram 封装 / 日志 / 配置）
modules/
├── calc.py              计算器（默认启用）
└── demo.py              示例模块（/ping /echo，默认不启用）
TGcalc_bot.py            计算器业务核心
data/modules.json        启用哪些模块（顺序即优先级）
```

### 新增一个模块（3 步）

| 步骤 | 做什么 |
|---|---|
| 1 | 写 `modules/mymodule.py`，导出 `Plugin(Module)` 类（参考 `modules/demo.py`） |
| 2 | `data/modules.json` 的 `enabled` 里加 `"mymodule"` |
| 3 | `sudo systemctl restart unmi_TGtool` |

模块接口（`core/base.py`）：

```python
from core.base import Module, PASS

class Plugin(Module):
    name = "mymodule"
    version = "1.0.0"
    description = "干什么用的"

    def on_message(self, text, chat_id):      # 非命令消息，True=接管
    def on_command(self, cmd, args, chat_id): # /命令，PASS=不归我管
    def on_callback(self, data, cb_id, msg):  # 按钮回调，True=接管
    def on_report(self, kind):                # 定时报告（可选）
    def on_start(self): ...                   # 启动钩子（可选）
```

**模块隔离**：每个方法调用都被 try/except 包裹，某个模块崩了不影响其他模块。

## ⚠️ 一个 token 只能有一个轮询进程

Telegram 的 `getUpdates` 是独占消费的，同一 token 跑两个进程会互相抢消息（各丢一半）。
多机部署请给每个实例申请独立 bot token。

## 运维

```bash
sudo systemctl status  unmi_TGtool
sudo journalctl -u unmi_TGtool -f
sudo systemctl restart unmi_TGtool      # 改完代码必须重启

cd /opt/unmi_TGtool
sudo python3 selftest_public.py         # 框架 + 计算器（离线）
sudo python3 selftest_calc.py           # 计算器核心 203 条
sudo python3 main.py --dry-run          # 加载模块但不轮询
```

## 卸载

```bash
sudo systemctl stop unmi_TGtool && sudo systemctl disable unmi_TGtool
sudo rm -f /etc/systemd/system/unmi_TGtool.service /etc/unmi_TGtool.env
sudo rm -rf /opt/unmi_TGtool
sudo systemctl daemon-reload
```

## 已验证环境

arm64 / Ubuntu 24.04 / Python 3.12 · x86_64 / Debian 13 / Python 3.13

## 许可证

MIT —— 随便用、随便改，不用打招呼。
