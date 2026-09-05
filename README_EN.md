# 🧰 unmi_TGtool — plug-and-play self-hosted Telegram tool kit

> 中文版：[README.md](README.md)

**Zero dependencies** (Python standard library only). A pluggable Telegram tool-kit framework
that **works as a calculator out of the box** — drop files into `modules/` to add features.

Runs on any Linux box with Python 3.6+. **One command, plug and play.**

## Plug and play (3 steps)

```bash
# 1) Create a bot with @BotFather, get the token; message the bot to get your chat id
# 2) Extract & install:
tar xzf unmi_TGtool.tar.gz && cd unmi_TGtool
sudo ./install.sh "<BOT_TOKEN>" "<CHAT_ID>"

# 3) In Telegram, send the bot:
66*98
```

You get `66*98=6468｜6468｜` right away, plus the Chinese reading and the
**official banking-style capitalized amount** used on Chinese invoices and cheques.
The result comes in two independently click-to-copy blocks.

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
| Functions & constants | `sqrt` `abs` `round` `ln` `lg` `log` `sin` `cos` `tan` `factorial` `gcd` `lcm` `max` `min`, `pi` `e` `tau` `phi` |
| Safe | AST allowlist evaluator, **no `eval`**; `__import__`/`open`/attribute access all rejected |

## Pluggable framework

Core is `main.py` (single entry, no business logic) + `modules/` (feature modules).

```
main.py                  single entry: init / register / dispatch / poll
core/                    framework (interface / Telegram wrapper / log / config)
modules/
├── calc.py              calculator (enabled by default)
└── demo.py              example module (/ping /echo, disabled by default)
TGcalc_bot.py            calculator business core
data/modules.json        which modules to enable (order = priority)
```

### Add a module (3 steps)

| Step | What |
|---|---|
| 1 | Write `modules/mymodule.py`, export a `Plugin(Module)` class (see `modules/demo.py`) |
| 2 | Add `"mymodule"` to `enabled` in `data/modules.json` |
| 3 | `sudo systemctl restart unmi_TGtool` |

**Isolation**: every method call is wrapped in try/except — one module crashing never affects the others.

## ⚠️ One token = one poller

Telegram's `getUpdates` is exclusively consumed. Two processes on the same token split your
messages randomly between them (half go missing). Use a separate bot token per instance.

## Operations

```bash
sudo systemctl status  unmi_TGtool
sudo journalctl -u unmi_TGtool -f
sudo systemctl restart unmi_TGtool        # required after editing code

cd /opt/unmi_TGtool
sudo python3 selftest_public.py           # framework + calculator (offline)
sudo python3 selftest_calc.py             # calculator core, 203 tests
sudo python3 main.py --dry-run            # load modules without polling
```

## Uninstall

```bash
sudo systemctl stop unmi_TGtool && sudo systemctl disable unmi_TGtool
sudo rm -f /etc/systemd/system/unmi_TGtool.service /etc/unmi_TGtool.env
sudo rm -rf /opt/unmi_TGtool
sudo systemctl daemon-reload
```

## Tested on

arm64 / Ubuntu 24.04 / Python 3.12 · x86_64 / Debian 13 / Python 3.13

## License

MIT.
