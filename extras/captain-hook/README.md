# owl + captain-hook Integration

Use owl's Telegram approval system with captain-hook as the hook manager.

## Prerequisites

1. **owl installed**: `pip install owl-afk` or `pipx install owl-afk`
2. **captain-hook set up**: Run `captain-hook` to initialize
3. **Telegram bot configured**: Run `owl telegram setup` to configure your bot token and chat ID

## Switching from Standalone Mode

If you previously used `owl install` (standalone mode), uninstall those hooks first:

```bash
owl uninstall
```

This prevents duplicate hooks running.

## Installation

```bash
owl captain-hook install
```

This creates and enables owl wrapper scripts in `~/.config/captain-hook/hooks/`:
- `pre_tool_use/owl-pre_tool_use.sh` - Remote approval for tool calls
- `post_tool_use/owl-post_tool_use.sh` - Deliver queued messages after tool execution
- `stop/owl-stop.sh` - Notify on session stop
- `subagent_stop/owl-subagent_stop.sh` - Notify when subagents complete

## How It Works

When using captain-hook mode:

1. **Same config** - Uses `~/.config/owl/` for settings, rules, and storage
2. **Same features** - Approve/deny, rules, chain approval all work
3. **Inline polling** - Hooks poll Telegram inline during execution

## Configuration

Config is stored in `~/.config/owl/`:

```
~/.config/owl/
├── config.json      # Telegram bot token, chat ID
├── owl.db         # Rules and request history
└── mode             # "on" or "off"
```

To configure:
```bash
owl telegram setup
```

## Uninstall

```bash
owl captain-hook uninstall
captain-hook toggle  # Update runners
```
