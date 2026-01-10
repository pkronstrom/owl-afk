# Menu System Redesign

**Date**: 2026-01-10
**Status**: Design approved

## Overview

Replace pyafk's questionary-based menu system with dodo-style TUI using Rich + readchar + simple-term-menu. Also migrate CLI from argparse to Typer.

## Goals

- Modern keyboard-driven TUI (like dodo)
- Fast hook execution (lazy loading)
- Cleaner, more dynamic menus
- Consistent navigation patterns

## Dependencies

**Add:**
```toml
"typer>=0.9.0"           # CLI framework
"simple-term-menu>=1.6.0" # Selection menus
"readchar>=4.0.0"        # Keyboard input
```

**Remove:**
- `questionary`

**Keep:**
- `rich>=13.0.0` (already present)

## Architecture

### Module Structure

```
src/pyafk/cli/
├── __init__.py          # Typer app, entry point
├── commands.py          # Command implementations (adapt signatures)
├── ui/
│   ├── __init__.py
│   ├── base.py          # MenuUI protocol
│   ├── menu.py          # RichTerminalMenu wrapper
│   ├── panels.py        # Live panel utilities (scrolling, status)
│   └── interactive.py   # Menu flows
├── helpers.py           # Keep existing
└── install.py           # Keep existing
```

### Lazy Loading Strategy

Critical for hook performance - hooks run on every Claude tool call.

| Tier | When | What loads |
|------|------|------------|
| Hook path | `pyafk hook PreToolUse` | Core only: storage, rules, notifier |
| CLI commands | `pyafk on/off/status` | Core + minimal Rich console |
| Interactive | `pyafk` (no args) | Full UI: typer, simple-term-menu, readchar |

```python
# cli/__init__.py
import typer
app = typer.Typer()

@app.command()
def hook(hook_type: str):
    """Hook handler - minimal imports."""
    from pyafk.hooks.handler import handle_hook
    handle_hook(hook_type)

@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    """Interactive menu - lazy load UI."""
    if ctx.invoked_subcommand is None:
        from pyafk.cli.ui.interactive import interactive_menu
        interactive_menu()
```

## UI Design

### Navigation Keys (consistent everywhere)

- `↑/k` - Move up
- `↓/j` - Move down
- `Space` - Toggle/cycle
- `Enter/e` - Edit text field (opens editor)
- `q` or `Ctrl+C` - Back/cancel (Esc doesn't work reliably)

### Main Menu

Dynamic based on current state:

```
┌─ pyafk ─────────────────────────────┐
│ Remote approval for Claude Code     │
│                                     │
│ Status: on | tg | captain-hook      │
└─────────────────────────────────────┘

> Turn off              ← or "Turn on" based on state
  Manage Rules
  Config
  Install hooks         ← or "Uninstall" based on state

─────────────────────────────────────
↑↓ navigate • Enter select • q quit
```

- Status item removed (shown in banner)
- Turn on/off is first item, changes based on current state
- Install/Uninstall shown conditionally

### Config Screen

Consolidates Telegram settings + boolean toggles:

```
Config

  [x] debug              Log to debug.log
  [ ] daemon_enabled     Background polling
  [ ] disable_stop_hook  Skip stop notifications

  telegram_bot_token     **********3f2a
  telegram_chat_id       12345678
  editor                 vim

─────────────────────────────────────
↑↓ navigate • Space/Enter toggle • Enter edit text • q back
```

**Behaviors:**
- Bools: Space or Enter toggles, saves immediately
- Text: Enter or `e` opens in configured editor, saves on close
- `editor` config defaults to `$EDITOR` env var
- All changes persist instantly (no confirmation dialog)

### Rules Live Panel

Dodo-style scrollable list with 20Hz refresh:

```
┌─ Rules ─────────────────────────────┐
│ ↑ 3 more                            │
│                                     │
│   ✓ Bash(git *)                     │
│   ✓ Bash(uv run pytest *)           │
│ > ✓ Edit(*.py)                      │
│   ✓ Read(*.md)                      │
│   ✗ Bash(rm -rf *)                  │
│                                     │
│ ↓ 12 more                           │
├─────────────────────────────────────┤
│ ✓ Rule toggled                      │
└─────────────────────────────────────┘
↑↓/jk navigate • Space toggle • Enter/e edit • a add • d delete • q back
```

**Features:**
- Scroll indicators when list overflows
- `✓` = approve, `✗` = deny
- Status line shows brief feedback, auto-clears

**Keybindings:**
| Key | Action |
|-----|--------|
| ↑/k | Move up |
| ↓/j | Move down |
| Space | Toggle approve ↔ deny |
| Enter/e | Edit pattern (opens editor) |
| a | Add new rule |
| d | Delete rule (inline confirm) |
| q | Back to main menu |

### Add Rule Form

Single form screen:

```
Add Rule

> Tool:     Bash           ← Space cycles options
  Pattern:  *              ← Enter/e opens editor
  Action:   ✓ approve      ← Space toggles

───────────────────────────────────────
↑↓ navigate • Space cycle/toggle • Enter edit • s save • q cancel
```

**Tool options:** Bash, Edit, Write, Read, Skill, WebFetch, Task, mcp__*, custom

### Wizard Flow

Keep educational structure, modernize UI:

**Step 1: Welcome**
```
┌─ pyafk Setup ───────────────────────┐
│                                     │
│ Remote approval for Claude Code     │
│                                     │
│ How it works:                       │
│ 1. Intercepts Claude tool calls     │
│ 2. Sends requests to Telegram       │
│ 3. You approve/deny from phone      │
│                                     │
└─────────────────────────────────────┘

> Continue
  Exit
```

**Step 2: Install hooks**
```
Install Hooks

> Standalone         Write to ~/.claude/settings.json
  Captain-hook       (not installed)    ← disabled if not found

───────────────────────────────────────
↑↓ navigate • Enter select • q cancel
```

Captain-hook option disabled/dimmed if `~/.claude/captain-hook` doesn't exist.

**Step 3: Telegram setup** - Form with bot_token + chat_id

**Step 4: Test connection** - Optional

**Step 5: Enable pyafk?** - Toggle

**Step 6: Done** - Summary panel

## Implementation Notes

### From dodo to copy/adapt

- `ui/base.py` - MenuUI protocol
- `ui/rich_menu.py` - RichTerminalMenu class
- `ui/panel_builder.py` - Scroll calculation utilities
- Keyboard loop pattern from `ui/interactive.py`

### Key patterns

1. **Closure-based state** for live panels (no class overhead)
2. **Rich.Live** with 20Hz refresh for smooth updates
3. **readchar.readkey()** for keyboard input
4. **simple-term-menu** for selection dialogs
5. **Immediate saves** on config changes

### Testing considerations

- Mock readchar for keyboard input testing
- Test lazy loading (ensure UI modules don't load during hook tests)
- Integration tests for menu flows
