# 🧰 unmi_TGtool — self-hosted Telegram tool kit

**unmi_TGtool** is a self-hosted Telegram tool shell. **Zero dependencies** (Python standard library only),
with its own `getUpdates` polling — drop a module in and the feature appears.
Runs on any Linux box with Python 3.6+ with a single command.

## Naming

| Layer | Convention | Example |
|---|---|---|
| Project (repo / install dir) | `unmi_TGtool` | service `unmi_TGtool`, dir `/opt/unmi_TGtool`, env `/etc/unmi_TGtool.env` |
| Bot script | **one name per feature** | the calculator is `TGcalcbot.py` |
| Module | its own name | calculator core `calc.py`, not `unmi_TGtool_calc.py` |

**Naming convention**: each standalone bot uses its own `TG<feature>bot.py` name,
independent of the others — install only what you need.
This repo is the calculator one: `TGcalcbot.py`.

## Bundled module

**Calculator `calc.py`** — send `66*98` and get the result, plus the Chinese reading
and the **official banking-style capitalized amount** used on Chinese invoices and cheques.

Send `66*98` and get the result — plus the Chinese reading (`六千四百六十八`) and the
**official banking-style capitalized amount** (`陆仟肆佰陆拾捌元整`) used on Chinese invoices
and cheques. The result comes in two independently click-to-copy blocks.

> 中文版：[README.md](README.md)

## Features

| Feature | Example |
|---|---|
| Just send an expression | `66*98` → `66*98=6468｜6468｜` |
| Two copyable blocks | tap the left one for the whole thing, the right one for the number only |
| Chinese reading | `自然读法：六千四百六十八` |
| Banking-style capitalized amount | `会计大写：陆仟肆佰陆拾捌元整` |
| Settings panel `/calc` | decimals 1–6 / display format / conversion / chained calc |
| Chained calculation (off by default) | `3+3`=6, then `+3` → `6+3=9`; `/00` to exit; auto-exits after 3 min |
| Functions & constants | `sqrt` `abs` `round` `ln` `lg` `log` `sin` `cos` `tan` `factorial` `gcd` `lcm` `max` `min`, `pi` `e` `tau` `phi` |
| Exact arithmetic | `Fraction`-based, no float rounding — `0.1+0.2` is exactly `0.3`, `2^64` is exact |
| Safe | AST allowlist evaluator, **no `eval`**; `__import__`, `open`, attribute access all rejected |

## Installation

```bash
# 1. Create a bot with @BotFather, get the token.
# 2. Get your chat id (send any message to the bot first).
# 3. On your server:
tar xzf unmi_TGtool.tar.gz && cd unmi_TGtool
sudo ./install.sh "<BOT_TOKEN>" "<CHAT_ID>"
```

It installs to `/opt/unmi_TGtool`, writes credentials to `/etc/unmi_TGtool.env`
(mode 600), registers and starts a systemd service.

Install without starting (dry run / switch later):

```bash
sudo ./install.sh "<BOT_TOKEN>" "<CHAT_ID>" --no-start
sudo systemctl start unmi_TGtool
```

## ⚠️ One token = one poller

Telegram's `getUpdates` is **exclusively consumed**. Only one process per bot token may poll —
two pollers will **split your messages randomly between them** (half your messages go missing).

| Scenario | Safe? |
|---|---|
| One process handling multiple features | ✅ Yes |
| Two processes polling the same token (same or different machines) | ❌ No |
| Multiple processes that only call `sendMessage` | ✅ Yes |
| One `getUpdates` + one webhook on the same token | ❌ No |

Check with:

```bash
ps aux | grep -E 'TGcalcbot.py' | grep -v grep
# must print at most one line
```

## Files

| File | Description |
|---|---|
| `TGcalcbot.py` | Main program: polling, message routing, callbacks, command registration. Depends only on `calc.py` |
| `calc.py` | Calculator core (AST allowlist evaluator + Chinese numerals + settings model) |
| `selftest_calc.py` | 196 tests (sandbox escapes / malformed input / banking spec / precision) |
| `selftest_TGcalcbot.py` | 15 offline tests with a mocked network layer — never touches the real API |
| `install.sh` | One-shot installer with token-conflict check; supports `--no-start` |
| `unmi_TGtool.service` | systemd unit |

## Operations

```bash
sudo systemctl status  unmi_TGtool
sudo journalctl -u unmi_TGtool -f
sudo systemctl restart unmi_TGtool        # required after editing code

cd /opt/unmi_TGtool
sudo python3 selftest_calc.py
sudo python3 selftest_TGcalcbot.py
sudo python3 TGcalcbot.py --dry-run
```

## Uninstall

```bash
sudo systemctl stop unmi_TGtool
sudo systemctl disable unmi_TGtool
sudo rm -f /etc/systemd/system/unmi_TGtool.service /etc/unmi_TGtool.env
sudo rm -rf /opt/unmi_TGtool
sudo systemctl daemon-reload
```

## Tested on

| Arch / OS / Python | Result |
|---|---|
| arm64 / Ubuntu 24.04 / Python 3.12 | ✅ |
| x86_64 / Debian 13 / Python 3.13 | ✅ |

## License

MIT.
