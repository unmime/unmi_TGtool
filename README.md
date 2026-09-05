# 🧰 unmi_TGtool — 开箱即用的自托管 Telegram 工具集

> **English version: [README_EN.md](README_EN.md)** · 当前版本 **v1.0.0.0**（首个正式版）

**零第三方依赖**（纯 Python 标准库）。一个可插拔的 Telegram 工具集框架，
**默认装好就能当计算器用**，想加功能就往 `modules/` 里丢文件；一台机器上装多少个 bot，
敲 `unmi` 一个终端面板全管起来。

拷到任意一台有 Python 3.6+ 的 Linux 机器上，**一条命令，开箱即用**。

## ⚡ 一键安装（推荐）

用 `root` 执行下面**一条命令**，自动完成下载、安装、配置，装完直接能用：

```bash
bash <(curl -sL https://raw.githubusercontent.com/unmime/unmi_TGtool/main/unmi.sh)
```

装完会进入**控制台面板**（以后随时敲 `unmi` 回来）：

```
  unmi_TGtool 控制台  集中管理本机的 Telegram 机器人
  https://github.com/unmime/unmi_TGtool   v1.0.0.0

╔════════════════════════════════════════╗
║ 已装机器人：                           ║
║ 「1」 测试1 @unmiTGtool_bot  🟩 运行中 ║
║ ══════════════════════════════════════ ║
║ 「2」 测试2 @ceshi21212bot   🟩 运行中 ║
║ ══════════════════════════════════════ ║
╚════════════════════════════════════════╝

  「A」 添加机器人   「T」 发送测试   「S」 开关机器人
  「R」 重启服务     「P」 配置代理   「U」 一键更新
  「X」 卸载面板     「0」 退出
  ──────────────────────────────────────────
  选择（数字进入管理）:
```

按 `A` 走三步引导（Token → Chat ID → 备注）加机器人，输完自动配置、启动并发一条测试消息。
按数字键进单个机器人的管理页（状态 / 改配置 / 加备注 / 看日志 / 删除 / 更新）。

| 面板功能 | 说明 |
|---|---|
| 添加机器人 | 自动识别 bot 用户名，同名/同 token 会提示；可起好认的备注名 |
| 发送测试 | 选一个或全部，发一条测试消息验证配置 |
| 开关机器人 | 运行中→停止，已停止→启动 |
| 重启面板 | 重启全部机器人服务并重载控制台（确认页，可返回） |
| 面板命令名 | 把打开面板的命令从 `unmi` 改成你喜欢的名字（如 `tg`），一键更新也会认 |
| 单机器人重启 | 进某个机器人的管理页选「重启此机器人」 |
| 配置代理 | 全局代理，一次配置所有机器人共用，自动同步并重启（国内服务器必备） |
| 一键更新 | 拉最新版，更新框架 + 所有机器人 + `unmi` 命令本身，保留各自配置 |
| 卸载面板 | 删除所有机器人 + 控制台本身 |

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
| 函数与常量 | `sqrt` `cbrt` `abs` `floor` `ceil` `round` `trunc` `sign` `ln` `log` `log2` `log10` `exp` `sin` `cos` `tan` `asin` `acos` `atan` `sinh` `cosh` `tanh` `factorial` `pow` `nthroot` `hypot` `gcd` `lcm` `comb`/`nCr` `perm`/`nPr` `gamma` `max` `min` `avg` `sum`、`pi` `e` `tau` `phi` |
| 括号 | `()` `[]` `{}` 混着写都认，`{[(2+3)]*4}` 照常计算 |
| 科学计数法 | `1e5` `2.5e-3`；写了一半的 `1e` 会明确报错，不会算成「1×自然常数」 |
| 安全 | AST 白名单求值，**不用 `eval`**；`__import__`/`open`/属性访问全部拒绝 |

## 可插拔框架

核心是 `main.py`（统一入口，不含业务）+ `modules/`（功能模块）。

```
main.py                  统一入口：初始化 / 装配 / 调度 / 轮询（不含业务逻辑）
core/                    框架内核，模块只依赖它
├── base.py              Module 基类 + 返回值约定 + JSON 读写
├── registry.py          模块注册表：发现 / 校验 / 加载 / 生命周期
├── config.py            配置加载（环境变量 + data/modules.json）
├── tg.py                Telegram API 封装（BotContext）
└── log.py               统一日志
modules/
├── calc/                计算器（默认启用，包形态）
│   ├── __init__.py      导出 Plugin
│   └── engine.py        求值核心，不依赖框架，可单独跑自测
└── demo.py              示例模块（/ping /echo，默认不启用）
data/                    运行数据（不进代码仓库）
├── modules.json         启用哪些模块（顺序即优先级）
└── <模块名>.json        各模块自己的配置
docs/MODULE_GUIDE.md     模块开发规范
```

### 新增一个模块（3 步，不用改 main.py）

| 步骤 | 做什么 |
|---|---|
| 1 | 写 `modules/mymodule.py`，导出 `Plugin(Module)` 类（参考 `modules/demo.py`） |
| 2 | `data/modules.json` 的 `enabled` 里加 `"mymodule"` |
| 3 | `sudo systemctl restart unmi_TGtool` |

框架提供了这些开箱能力，详细约定见 **[模块开发规范](docs/MODULE_GUIDE.md)**：

| 能力 | 说明 |
|---|---|
| 坏模块隔离 | 导入失败、缺元信息、重名、依赖缺失 → 跳过它并在日志说明原因，其它模块照常 |
| 依赖声明 | `requires = ["其他模块名"]`，加载时校验顺序，缺依赖不会带病启动 |
| 独立配置 | `self.load_config()` / `self.save_config()`，落在 `DATA_DIR/<模块名>.json`，原子写 |
| 完整生命周期 | `on_start` / 消息 / 命令 / 按钮回调 / 定时报告 / `on_stop`（systemd 停止时触发） |
| 模块异常隔离 | 每个方法调用都包 try/except，一个模块崩了不影响别人和整条消息流 |

## ⚠️ 一个 token 只能有一个轮询进程

Telegram 的 `getUpdates` 是独占消费的，同一 token 跑两个进程会互相抢消息（各丢一半）。
多开请给每个机器人申请独立 bot token —— 面板添加时会查重并提示。

## 运维

```bash
sudo systemctl status  unmi_TGtool
sudo journalctl -u unmi_TGtool -f
sudo systemctl restart unmi_TGtool      # 改完代码必须重启

cd /opt/unmi_TGtool
sudo python3 selftest_public.py         # 框架 + 模块注册（离线，20 条）
sudo python3 selftest_calc.py           # 计算器核心（离线，203 条）
sudo python3 main.py --modules          # 列出所有模块及状态（坏模块直接显示原因）
sudo python3 main.py --dry-run          # 按 enabled 实际加载一遍，不开始轮询
sudo python3 main.py --report daily     # 手动触发一次定时报告
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
