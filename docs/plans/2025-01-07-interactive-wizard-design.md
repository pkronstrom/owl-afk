# Interactive Wizard Design

## Overview

Add an interactive wizard/menu to pyafk that appears when the command is called without parameters. CLI commands remain available when parameters are provided.

## User Flow

### First Run (no config exists)

```
┌─────────────────────────────────────────┐
│  pyafk - Remote approval for Claude Code │
│  First-time setup                        │
└─────────────────────────────────────────┘

How it works:
  1. pyafk intercepts Claude Code tool calls
  2. Sends approval requests to Telegram
  3. You approve/deny from your phone
  4. Use 'pyafk on/off' to enable/disable

? Choose installation method:
  › Standalone     (writes to ~/.claude/settings.json)
    Captain-hook   (uses captain-hook hook manager)
```

After installation:
1. Telegram setup with links:
   - Create bot: https://telegram.me/BotFather
   - Get chat ID: https://t.me/getmyid_bot
2. Test message
3. Option to enable pyafk

### Subsequent Runs (config exists)

```
pyafk - Remote approval for Claude Code
───────────────────────────────────────
Mode: on
Telegram: configured
Daemon: running (pid 12345)

? What would you like to do?
  › Status        Show detailed status
    Turn on       Enable pyafk
    Turn off      Disable pyafk
    Rules         Manage auto-approve rules
    Telegram      Configure Telegram bot
    Config        Edit settings
    ─────────
    Reinstall     Change installation method
    Uninstall     Remove pyafk hooks
    ─────────
    Exit
```

### Config Submenu

```
? Configuration:
    debug         ✓ on    Log to ~/.config/pyafk/debug.log
    daemon          off   Background polling (vs inline)
    ─────────
    Back
```

## Implementation

### Dependencies

Remove:
- `click`

Add:
- `questionary` - interactive prompts
- `rich` - styled console output

### Architecture

Switch from Click to argparse (consistent with captain-hook):

```python
def main():
    parser = argparse.ArgumentParser(...)
    subparsers = parser.add_subparsers(dest="command")

    # Add subcommands: status, on, off, rules, telegram, etc.

    args = parser.parse_args()

    if args.command is None:
        # No command provided - run interactive mode
        if not config_exists():
            run_wizard()
        else:
            interactive_menu()
    else:
        args.func(args)
```

### Key Functions

- `run_wizard()` - first-time setup wizard
- `interactive_menu()` - main menu with status header
- `interactive_config()` - config submenu for debug/daemon toggles
- `cmd_*()` - CLI command handlers (status, on, off, etc.)

### CLI Commands (unchanged functionality)

- `pyafk status` - show status
- `pyafk on` - enable pyafk
- `pyafk off` - disable pyafk
- `pyafk disable` - fully disable (stop daemon)
- `pyafk rules list|add|remove` - manage rules
- `pyafk telegram setup|test` - telegram config
- `pyafk install` - standalone install
- `pyafk uninstall` - standalone uninstall
- `pyafk captain-hook install|uninstall` - captain-hook integration
- `pyafk hook <type>` - internal hook handler
- `pyafk reset` - reset database
- `pyafk debug on|off` - debug mode
