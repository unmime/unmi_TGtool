# 🧰 unmi_TGtool — plug-and-play self-hosted Telegram tool kit

> 中文版：[README.md](README.md) · Current version **v1.0.0.0** (first stable release)

**Zero dependencies** (Python standard library only). A pluggable Telegram tool-kit framework
that **works as a calculator out of the box** — drop files into `modules/` to add features,
and manage every bot on the machine from one terminal dashboard with `unmi`.

Runs on any Linux box with Python 3.6+. **One command, plug and play.**

## ⚡ One-line install (recommended)

Run this **single command** as `root` — it downloads, installs and configures everything,
then it's ready to use:

```bash
bash <(curl -sL https://raw.githubusercontent.com/unmime/unmi_TGtool/main/unmi.sh)
```

It drops you into the **console dashboard** (come back any time with `unmi`):

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

Press `A` for a 3-step wizard (Token → Chat ID → label); it configures, starts and sends a
test message automatically. Press a number to open that bot's page
(status / reconfigure / label / logs / delete / update).

| Dashboard action | What it does |
|---|---|
| Add bot | Auto-detects the bot username, warns on duplicate names/tokens, lets you set a label |
| Send test | Pick one or all, sends a test message to verify the config |
| Toggle bot | Running → stop, stopped → start |
| Restart panel | Restart every bot service and reload the console (confirm page, cancellable) |
| Panel command | Rename the launcher command from `unmi` to anything you like (e.g. `tg`); one-click update honours it |
| Single-bot restart | Open that bot's page and pick «Restart this bot» |
| Set proxy | Global proxy shared by every bot, synced and restarted automatically |
| One-click update | Pulls the latest release, updates framework + all bots + the `unmi` command, keeps configs |
| Uninstall | Removes every bot plus the dashboard itself |

## Manual install (alternative)

```bash
# 1) Download (pick one)
wget https://github.com/unmime/unmi_TGtool/releases/latest/download/unmi_TGtool.tar.gz
# or: curl -LO https://github.com/unmime/unmi_TGtool/releases/latest/download/unmi_TGtool.tar.gz

# 2) Extract & install (tarball has a top-level unmi_TGtool/ dir)
tar xzf unmi_TGtool.tar.gz && cd unmi_TGtool
sudo ./install.sh "<BOT_TOKEN>" "<CHAT_ID>"

# 3) In Telegram, send the bot 66*98
```

A systemd service `unmi_TGtool` is registered and started automatically — auto-start on boot, auto-restart on crash.

## Built-in calculator

| Feature | Example |
|---|---|
| Just send an expression | `66*98` → `66*98=6468｜6468｜` |
| Two copyable blocks | tap left for the whole thing, right for the number only |
| Chinese reading | `自然读法：六千四百六十八` |
| Banking-style capitalized amount | `会计大写：陆仟肆佰陆拾捌元整` |
| Exact arithmetic | `Fraction`-based — `0.1+0.2` is exactly `0.3`, `2^64` exact |
| Settings panel `/calc` | decimals 1–6 / display format / conversion / chained calc |
| Chained calc (off by default) | `3+3`=6, then `+3` → `6+3=9`; `/00` to exit; auto-exit after 3 min |
| Functions & constants | `sqrt` `cbrt` `abs` `floor` `ceil` `round` `trunc` `sign` `ln` `log` `log2` `log10` `exp` `sin` `cos` `tan` `asin` `acos` `atan` `sinh` `cosh` `tanh` `factorial` `pow` `nthroot` `hypot` `gcd` `lcm` `comb`/`nCr` `perm`/`nPr` `gamma` `max` `min` `avg` `sum`, `pi` `e` `tau` `phi` |
| Brackets | `()` `[]` `{}` are interchangeable — `{[(2+3)]*4}` works as written |
| Scientific notation | `1e5`, `2.5e-3`; a half-written `1e` errors out instead of silently computing `1×e` |
| Safe | AST allowlist evaluator, **no `eval`**; `__import__`/`open`/attribute access all rejected |

## Pluggable framework

Core is `main.py` (single entry, no business logic) + `modules/` (feature modules).

```
main.py                  single entry: init / assemble / dispatch / poll (no business logic)
core/                    framework internals — modules depend on this only
├── base.py              Module base class + return-value contract + JSON helpers
├── registry.py          module registry: discover / validate / load / lifecycle
├── config.py            config loading (env vars + data/modules.json)
├── tg.py                Telegram API wrapper (BotContext)
└── log.py               unified logging
modules/
├── calc/                calculator (enabled by default, package form)
│   ├── __init__.py      exports Plugin
│   └── engine.py        evaluation core, framework-agnostic, testable standalone
└── demo.py              example module (/ping /echo, disabled by default)
data/                    runtime data (not in the repo)
├── modules.json         which modules to enable (order = priority)
└── <module>.json        each module's own config
docs/MODULE_GUIDE.md     module development guide
```

### Add a module (3 steps, no changes to main.py)

| Step | What |
|---|---|
| 1 | Write `modules/mymodule.py`, export a `Plugin(Module)` class (see `modules/demo.py`) |
| 2 | Add `"mymodule"` to `enabled` in `data/modules.json` |
| 3 | `sudo systemctl restart unmi_TGtool` |

Batteries included — full contract in the **[Module Development Guide](docs/MODULE_GUIDE.md)**:

| Capability | Notes |
|---|---|
| Broken-module isolation | Import errors, missing metadata, duplicate names, unmet deps → the module is skipped with a reason in the log; everything else keeps running |
| Dependency declaration | `requires = ["other_module_name"]`; order is validated at load time |
| Per-module config | `self.load_config()` / `self.save_config()`, stored in `DATA_DIR/<module>.json`, atomic writes |
| Full lifecycle | `on_start` / messages / commands / button callbacks / scheduled reports / `on_stop` (on systemd stop) |
| Exception isolation | Every call is wrapped in try/except — one module crashing never affects the others |

## ⚠️ One token = one poller

Telegram's `getUpdates` is exclusively consumed. Two processes on the same token split your
messages randomly between them (half go missing). Get a separate bot token per bot —
the dashboard warns you on duplicates.

## Operations

```bash
sudo systemctl status  unmi_TGtool
sudo journalctl -u unmi_TGtool -f
sudo systemctl restart unmi_TGtool        # required after editing code

cd /opt/unmi_TGtool
sudo python3 selftest_public.py           # framework + module registry (offline, 20 tests)
sudo python3 selftest_calc.py             # calculator core (offline, 203 tests)
sudo python3 main.py --modules            # list modules and their status (broken ones show why)
sudo python3 main.py --dry-run            # load per `enabled` without polling
sudo python3 main.py --report daily       # trigger a scheduled report by hand
```

## Uninstall

```bash
sudo systemctl stop unmi_TGtool && sudo systemctl disable unmi_TGtool
sudo rm -f /etc/systemd/system/unmi_TGtool.service /etc/unmi_TGtool.env
sudo rm -rf /opt/unmi_TGtool
sudo systemctl daemon-reload
```

To remove just one bot and keep the dashboard, run `unmi`, open that bot's page and pick «5».

## Tested on

arm64 / Ubuntu 24.04 / Python 3.12 · x86_64 / Debian 13 / Python 3.13

## License

MIT.
