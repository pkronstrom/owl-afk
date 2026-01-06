# pyafk + captain-hook Integration

Use pyafk's Telegram approval system with captain-hook as the hook manager.

## Prerequisites

1. **pyafk installed**: `pip install pyafk` or `pipx install pyafk`
2. **captain-hook set up**: Run `captain-hook` to initialize
3. **Telegram bot configured**: Run `pyafk setup` to configure your bot token and chat ID

## Installation

```bash
# From the pyafk repo
./extras/captain-hook/install.sh
```

This copies the pyafk wrapper scripts to `~/.config/captain-hook/hooks/`.

## Enable Hooks

After installation:

```bash
captain-hook toggle
```

Select the pyafk hooks you want to enable:
- `pre_tool_use/pyafk.sh` - Approval for tool calls (Bash, Edit, etc.)
- `post_tool_use/pyafk.sh` - Deliver queued messages after tool execution
- `stop/pyafk.sh` - Interactive confirmation before Claude stops
- `subagent_stop/pyafk.sh` - Approval for subagent continuation

## How It Works

When using captain-hook mode:

1. **No daemon required** - Hooks poll Telegram inline during execution
2. **Same config** - Uses `~/.config/pyafk/` for settings, rules, and storage
3. **Same features** - Approve/deny, rules, chain approval all work
4. **No /msg, /afk commands** - Those require the daemon (standalone mode)

## Standalone vs Captain-Hook Mode

| Feature | Standalone (`pyafk on`) | Captain-Hook |
|---------|------------------------|--------------|
| Telegram approval | Yes | Yes |
| Rules engine | Yes | Yes |
| Chain approval | Yes | Yes |
| /msg command | Yes | No |
| /afk on/off | Yes | No |
| /start command | Yes | No |
| Continuous polling | Yes (daemon) | No (inline) |

## Configuration

Config is stored in `~/.config/pyafk/`:

```
~/.config/pyafk/
├── config.json      # Telegram bot token, chat ID
├── pyafk.db         # Rules and request history
└── mode             # "on" or "off"
```

To configure:
```bash
pyafk setup
```

## Uninstall

Remove the wrapper scripts:
```bash
rm ~/.config/captain-hook/hooks/*/pyafk.sh
```

Then run `captain-hook toggle` to update the runners.
