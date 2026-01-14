# pyafk + captain-hook Integration

Use pyafk's Telegram approval system with captain-hook as the hook manager.

## Prerequisites

1. **pyafk installed**: `pip install pyafk` or `pipx install pyafk`
2. **captain-hook set up**: Run `captain-hook` to initialize
3. **Telegram bot configured**: Run `pyafk telegram setup` to configure your bot token and chat ID

## Switching from Standalone Mode

If you previously used `pyafk install` (standalone mode), uninstall those hooks first:

```bash
pyafk uninstall
```

This prevents duplicate hooks running.

## Installation

```bash
pyafk captain-hook install
```

This creates and enables pyafk wrapper scripts in `~/.config/captain-hook/hooks/`:
- `pre_tool_use/pyafk-pre_tool_use.sh` - Remote approval for tool calls
- `post_tool_use/pyafk-post_tool_use.sh` - Deliver queued messages after tool execution
- `stop/pyafk-stop.sh` - Notify on session stop
- `subagent_stop/pyafk-subagent_stop.sh` - Notify when subagents complete

## How It Works

When using captain-hook mode:

1. **Same config** - Uses `~/.config/pyafk/` for settings, rules, and storage
2. **Same features** - Approve/deny, rules, chain approval all work
3. **Inline polling** - Hooks poll Telegram inline during execution

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
pyafk telegram setup
```

## Uninstall

```bash
pyafk captain-hook uninstall
captain-hook toggle  # Update runners
```
