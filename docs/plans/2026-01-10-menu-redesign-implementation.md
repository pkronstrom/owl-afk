# Menu Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace questionary-based menus with dodo-style TUI using Rich + readchar + simple-term-menu, and migrate CLI from argparse to Typer.

**Architecture:** Layered UI with lazy loading - hook path stays fast, UI libraries only load for interactive mode. Simple-term-menu for shallow menus, Rich.Live panels for rules list. All config changes save immediately.

**Tech Stack:** Typer (CLI), Rich (rendering), simple-term-menu (selection), readchar (keyboard input)

**Reference:** Design doc at `docs/plans/2026-01-10-menu-redesign.md`, dodo implementation at `~/Projects/own/dodo/src/dodo/ui/`

---

## Phase 1: Dependencies & Structure

### Task 1: Update dependencies

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add new dependencies**

In `pyproject.toml`, update dependencies array:

```toml
dependencies = [
    "aiosqlite>=0.20.0",
    "httpx>=0.28.0",
    "readchar>=4.0.0",
    "rich>=13.0.0",
    "simple-term-menu>=1.6.0",
    "typer>=0.9.0",
]
```

Remove `questionary` from the list.

**Step 2: Sync dependencies**

Run: `uv sync --extra dev`
Expected: New packages installed, questionary removed

**Step 3: Verify imports work**

Run: `uv run python -c "import typer, readchar, simple_term_menu; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add typer, readchar, simple-term-menu; remove questionary"
```

---

### Task 2: Create UI module structure

**Files:**
- Create: `src/pyafk/cli/ui/__init__.py`
- Create: `src/pyafk/cli/ui/base.py`

**Step 1: Create ui package init**

```python
"""UI components for interactive CLI."""

from pyafk.cli.ui.base import MenuUI

__all__ = ["MenuUI"]
```

**Step 2: Create MenuUI protocol**

```python
"""Base protocol for menu UI."""

from typing import Optional, Protocol


class MenuUI(Protocol):
    """Protocol for menu implementations.

    Allows swapping menu backends if needed.
    """

    def select(
        self,
        options: list[str],
        title: str = "",
    ) -> Optional[int]:
        """Show selection menu, return selected index or None if cancelled."""
        ...

    def confirm(self, message: str) -> bool:
        """Show yes/no confirmation, return True for yes."""
        ...

    def input(self, prompt: str, default: str = "") -> Optional[str]:
        """Get text input, return value or None if cancelled."""
        ...
```

**Step 3: Verify module imports**

Run: `uv run python -c "from pyafk.cli.ui import MenuUI; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add src/pyafk/cli/ui/
git commit -m "feat(ui): add UI module structure with MenuUI protocol"
```

---

### Task 3: Implement RichTerminalMenu wrapper

**Files:**
- Create: `src/pyafk/cli/ui/menu.py`
- Modify: `src/pyafk/cli/ui/__init__.py`

**Step 1: Create menu wrapper**

```python
"""Terminal menu wrapper using simple-term-menu."""

from typing import Optional

from simple_term_menu import TerminalMenu


class RichTerminalMenu:
    """Wrapper around simple-term-menu with Rich styling."""

    def select(
        self,
        options: list[str],
        title: str = "",
        cursor_index: int = 0,
    ) -> Optional[int]:
        """Show selection menu.

        Args:
            options: List of option strings
            title: Optional title shown above menu
            cursor_index: Starting cursor position

        Returns:
            Selected index or None if cancelled (q/Ctrl+C)
        """
        if not options:
            return None

        menu = TerminalMenu(
            options,
            title=title if title else None,
            cursor_index=cursor_index,
            menu_cursor="> ",
            menu_cursor_style=("fg_cyan", "bold"),
            menu_highlight_style=("fg_cyan", "bold"),
            cycle_cursor=True,
            clear_screen=False,
        )

        result = menu.show()
        return result if result is not None else None

    def confirm(self, message: str, default: bool = False) -> bool:
        """Show yes/no confirmation.

        Args:
            message: Question to ask
            default: Default selection (False = No)

        Returns:
            True for yes, False for no/cancel
        """
        options = ["Yes", "No"]
        cursor = 0 if default else 1

        result = self.select(options, title=message, cursor_index=cursor)
        return result == 0

    def input(self, prompt: str, default: str = "") -> Optional[str]:
        """Get text input using configured editor.

        For simple inputs, uses inline prompt.
        For complex inputs, opens editor.

        Args:
            prompt: Input prompt
            default: Default value

        Returns:
            Input string or None if cancelled
        """
        import os
        import subprocess
        import tempfile

        from pyafk.utils.config import Config, get_pyafk_dir

        # Get editor from config or environment
        cfg = Config(get_pyafk_dir())
        editor = getattr(cfg, 'editor', None) or os.environ.get('EDITOR', 'vim')

        # Create temp file with default content
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.txt', delete=False
        ) as f:
            f.write(f"# {prompt}\n")
            f.write(f"# Lines starting with # are ignored\n")
            f.write(default)
            tmp_path = f.name

        try:
            subprocess.run([editor, tmp_path], check=True)

            with open(tmp_path) as fp:
                lines = [
                    ln.rstrip('\n')
                    for ln in fp.readlines()
                    if not ln.startswith('#')
                ]
            return '\n'.join(lines).strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None
        finally:
            os.unlink(tmp_path)
```

**Step 2: Update ui __init__**

```python
"""UI components for interactive CLI."""

from pyafk.cli.ui.base import MenuUI
from pyafk.cli.ui.menu import RichTerminalMenu

__all__ = ["MenuUI", "RichTerminalMenu"]
```

**Step 3: Test menu manually**

Run: `uv run python -c "from pyafk.cli.ui import RichTerminalMenu; m = RichTerminalMenu(); print(m.select(['a','b','c'], 'Test'))"`
Expected: Menu appears, selection works

**Step 4: Commit**

```bash
git add src/pyafk/cli/ui/
git commit -m "feat(ui): add RichTerminalMenu wrapper"
```

---

### Task 4: Implement panel utilities

**Files:**
- Create: `src/pyafk/cli/ui/panels.py`
- Modify: `src/pyafk/cli/ui/__init__.py`

**Step 1: Create panel utilities**

```python
"""Live panel utilities for scrolling lists."""

from typing import Callable, Optional, TypeVar

import readchar
from rich.console import Console
from rich.live import Live
from rich.panel import Panel

T = TypeVar("T")

# Refresh rate for live panels (Hz)
LIVE_REFRESH_RATE = 20

console = Console()


def calculate_visible_range(
    cursor: int,
    total_items: int,
    max_visible: int,
    scroll_offset: int = 0,
) -> tuple[int, int, int]:
    """Calculate visible window for scrolling list.

    Args:
        cursor: Current cursor position
        total_items: Total number of items
        max_visible: Maximum items that fit on screen
        scroll_offset: Current scroll offset

    Returns:
        Tuple of (start_idx, end_idx, new_scroll_offset)
    """
    if total_items <= max_visible:
        return 0, total_items, 0

    # Adjust scroll to keep cursor visible
    if cursor < scroll_offset:
        scroll_offset = cursor
    elif cursor >= scroll_offset + max_visible:
        scroll_offset = cursor - max_visible + 1

    start = scroll_offset
    end = min(start + max_visible, total_items)

    return start, end, scroll_offset


def format_scroll_indicator(hidden_above: int, hidden_below: int) -> tuple[str, str]:
    """Format scroll indicators.

    Returns:
        Tuple of (top_indicator, bottom_indicator)
    """
    top = f"↑ {hidden_above} more" if hidden_above > 0 else ""
    bottom = f"↓ {hidden_below} more" if hidden_below > 0 else ""
    return top, bottom


def clear_screen() -> None:
    """Clear terminal screen."""
    console.clear()


def get_terminal_size() -> tuple[int, int]:
    """Get terminal width and height."""
    return console.size.width, console.size.height
```

**Step 2: Update ui __init__**

```python
"""UI components for interactive CLI."""

from pyafk.cli.ui.base import MenuUI
from pyafk.cli.ui.menu import RichTerminalMenu
from pyafk.cli.ui.panels import (
    LIVE_REFRESH_RATE,
    calculate_visible_range,
    clear_screen,
    console,
    format_scroll_indicator,
    get_terminal_size,
)

__all__ = [
    "MenuUI",
    "RichTerminalMenu",
    "LIVE_REFRESH_RATE",
    "calculate_visible_range",
    "clear_screen",
    "console",
    "format_scroll_indicator",
    "get_terminal_size",
]
```

**Step 3: Test utilities**

Run: `uv run python -c "from pyafk.cli.ui import calculate_visible_range; print(calculate_visible_range(5, 20, 10, 0))"`
Expected: `(0, 10, 0)` or similar tuple

**Step 4: Commit**

```bash
git add src/pyafk/cli/ui/
git commit -m "feat(ui): add panel utilities for scrolling lists"
```

---

## Phase 2: Convert CLI to Typer

### Task 5: Create Typer CLI structure

**Files:**
- Rewrite: `src/pyafk/cli/__init__.py`

**Step 1: Rewrite CLI with Typer**

```python
"""CLI entry point for pyafk.

Uses Typer for command routing with lazy loading for performance.
Hook commands stay fast by not importing UI modules.
"""

import typer

__all__ = ["app", "main"]

app = typer.Typer(
    name="pyafk",
    help="Remote approval system for Claude Code",
    no_args_is_help=False,
)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Launch interactive menu if no command given."""
    if ctx.invoked_subcommand is None:
        # Lazy load UI - only when interactive
        from pyafk.cli.ui.interactive import interactive_menu
        interactive_menu()


@app.command()
def status() -> None:
    """Show current status."""
    from pyafk.cli.commands import cmd_status
    cmd_status(None)


@app.command()
def on() -> None:
    """Enable pyafk."""
    from pyafk.cli.commands import cmd_on
    cmd_on(None)


@app.command()
def off() -> None:
    """Disable pyafk."""
    from pyafk.cli.commands import cmd_off
    cmd_off(None)


@app.command()
def install() -> None:
    """Install pyafk hooks (standalone)."""
    from pyafk.cli.commands import cmd_install
    cmd_install(None)


@app.command()
def uninstall() -> None:
    """Uninstall pyafk hooks."""
    from pyafk.cli.commands import cmd_uninstall
    cmd_uninstall(None)


@app.command()
def reset(force: bool = typer.Option(False, "--force", help="Skip confirmation")) -> None:
    """Reset database and rules."""
    from pyafk.cli.commands import cmd_reset

    class Args:
        def __init__(self):
            self.force = force

    cmd_reset(Args())


@app.command()
def hook(hook_type: str) -> None:
    """Internal hook handler (called by Claude Code)."""
    from pyafk.cli.commands import cmd_hook

    class Args:
        def __init__(self):
            self.hook_type = hook_type

    cmd_hook(Args())


# Rules subcommand group
rules_app = typer.Typer(help="Manage auto-approve rules")
app.add_typer(rules_app, name="rules")


@rules_app.command("list")
def rules_list() -> None:
    """List all rules."""
    from pyafk.cli.commands import cmd_rules_list
    cmd_rules_list(None)


@rules_app.command("add")
def rules_add(
    pattern: str,
    action: str = typer.Option("approve", "--action", help="approve or deny"),
) -> None:
    """Add a new rule."""
    from pyafk.cli.commands import cmd_rules_add

    class Args:
        def __init__(self):
            self.pattern = pattern
            self.action = action

    cmd_rules_add(Args())


@rules_app.command("remove")
def rules_remove(rule_id: int) -> None:
    """Remove a rule by ID."""
    from pyafk.cli.commands import cmd_rules_remove

    class Args:
        def __init__(self):
            self.rule_id = rule_id

    cmd_rules_remove(Args())


# Telegram subcommand group
telegram_app = typer.Typer(help="Telegram configuration")
app.add_typer(telegram_app, name="telegram")


@telegram_app.command("test")
def telegram_test() -> None:
    """Send a test message."""
    from pyafk.cli.commands import cmd_telegram_test
    cmd_telegram_test(None)


# Debug subcommand group
debug_app = typer.Typer(help="Debug mode commands")
app.add_typer(debug_app, name="debug")


@debug_app.command("on")
def debug_on() -> None:
    """Enable debug logging."""
    from pyafk.cli.commands import cmd_debug_on
    cmd_debug_on(None)


@debug_app.command("off")
def debug_off() -> None:
    """Disable debug logging."""
    from pyafk.cli.commands import cmd_debug_off
    cmd_debug_off(None)


# Env subcommand group
env_app = typer.Typer(help="Manage env var overrides")
app.add_typer(env_app, name="env")


@env_app.command("list")
def env_list() -> None:
    """List env var overrides."""
    from pyafk.cli.commands import cmd_env_list
    cmd_env_list(None)


@env_app.command("set")
def env_set(key: str, value: str) -> None:
    """Set an env var override."""
    from pyafk.cli.commands import cmd_env_set

    class Args:
        def __init__(self):
            self.key = key
            self.value = value

    cmd_env_set(Args())


@env_app.command("unset")
def env_unset(key: str) -> None:
    """Remove an env var override."""
    from pyafk.cli.commands import cmd_env_unset

    class Args:
        def __init__(self):
            self.key = key

    cmd_env_unset(Args())


# Captain-hook subcommand group
captain_app = typer.Typer(help="Captain-hook integration")
app.add_typer(captain_app, name="captain-hook")


@captain_app.command("install")
def captain_install() -> None:
    """Install pyafk hooks for captain-hook."""
    from pyafk.cli.commands import cmd_captain_hook_install
    cmd_captain_hook_install(None)


@captain_app.command("uninstall")
def captain_uninstall() -> None:
    """Remove pyafk hooks from captain-hook."""
    from pyafk.cli.commands import cmd_captain_hook_uninstall
    cmd_captain_hook_uninstall(None)


def cli_main() -> None:
    """Entry point for pyproject.toml scripts."""
    app()


if __name__ == "__main__":
    cli_main()
```

**Step 2: Update pyproject.toml entry point**

In `pyproject.toml`, update:

```toml
[project.scripts]
pyafk = "pyafk.cli:cli_main"
```

**Step 3: Test CLI commands**

Run: `uv run pyafk --help`
Expected: Shows help with commands

Run: `uv run pyafk status`
Expected: Shows status (may error if interactive import fails, that's OK for now)

**Step 4: Commit**

```bash
git add src/pyafk/cli/__init__.py pyproject.toml
git commit -m "refactor(cli): migrate from argparse to Typer"
```

---

## Phase 3: Implement Interactive Menus

### Task 6: Create stub interactive module

**Files:**
- Create: `src/pyafk/cli/ui/interactive.py`

**Step 1: Create minimal interactive menu**

```python
"""Interactive menu flows."""

from rich.panel import Panel

from pyafk.cli.ui.menu import RichTerminalMenu
from pyafk.cli.ui.panels import clear_screen, console
from pyafk.utils.config import Config, get_pyafk_dir


def _print_header() -> None:
    """Print application header with status."""
    from pyafk.cli.install import check_hooks_installed
    from pyafk.daemon import is_daemon_running

    pyafk_dir = get_pyafk_dir()
    config = Config(pyafk_dir)
    mode = config.get_mode()

    # Build status parts
    parts = []
    parts.append(f"[{'green' if mode == 'on' else 'yellow'}]{mode}[/]")

    if config.telegram_bot_token and config.telegram_chat_id:
        parts.append("[green]tg[/green]")
    else:
        parts.append("[dim]tg[/dim]")

    if is_daemon_running(pyafk_dir):
        parts.append("[green]daemon[/green]")

    hooks_installed, hooks_mode = check_hooks_installed()
    if hooks_installed:
        parts.append(f"[green]{hooks_mode}[/green]")

    status_line = " | ".join(parts)

    console.print(Panel(
        "[bold cyan]pyafk[/bold cyan]\n"
        "[dim]Remote approval for Claude Code[/dim]\n\n"
        f"Status: {status_line}",
        border_style="cyan",
    ))


def interactive_menu() -> None:
    """Main interactive menu."""
    from pyafk.cli.commands import cmd_install, cmd_off, cmd_on, cmd_uninstall
    from pyafk.cli.install import check_hooks_installed
    from pyafk.cli.helpers import config_exists

    menu = RichTerminalMenu()
    pyafk_dir = get_pyafk_dir()

    # Check for first run
    if not config_exists():
        clear_screen()
        console.print("[bold]First time setup[/bold]\n")
        if menu.confirm("Run setup wizard?", default=True):
            run_wizard()
        return

    while True:
        clear_screen()
        _print_header()
        console.print()

        config = Config(pyafk_dir)
        mode = config.get_mode()
        hooks_installed, _ = check_hooks_installed()

        # Build dynamic menu options
        options = []
        actions = []

        # Toggle on/off
        if mode == "on":
            options.append("Turn off")
            actions.append("off")
        else:
            options.append("Turn on")
            actions.append("on")

        options.append("Manage Rules")
        actions.append("rules")

        options.append("Config")
        actions.append("config")

        # Install/Uninstall (conditional)
        if not hooks_installed:
            options.append("Install hooks")
            actions.append("install")
        else:
            options.append("Uninstall hooks")
            actions.append("uninstall")

        options.append("─────────")
        actions.append(None)

        options.append("Exit")
        actions.append("exit")

        # Show legend
        console.print("[dim]↑↓ navigate • Enter select • q quit[/dim]\n")

        choice_idx = menu.select(options)

        if choice_idx is None:
            break

        action = actions[choice_idx]

        if action is None:  # Separator
            continue
        elif action == "exit":
            break
        elif action == "on":
            cmd_on(None)
        elif action == "off":
            cmd_off(None)
        elif action == "rules":
            interactive_rules()
        elif action == "config":
            interactive_config()
        elif action == "install":
            clear_screen()
            cmd_install(None)
            input("\nPress Enter to continue...")
        elif action == "uninstall":
            clear_screen()
            cmd_uninstall(None)
            break


def interactive_rules() -> None:
    """Interactive rules management - placeholder."""
    console.print("[yellow]Rules menu not yet implemented[/yellow]")
    input("\nPress Enter to continue...")


def interactive_config() -> None:
    """Interactive config editor - placeholder."""
    console.print("[yellow]Config menu not yet implemented[/yellow]")
    input("\nPress Enter to continue...")


def run_wizard() -> None:
    """First-time setup wizard - placeholder."""
    console.print("[yellow]Wizard not yet implemented[/yellow]")
    input("\nPress Enter to continue...")
```

**Step 2: Test interactive menu**

Run: `uv run pyafk`
Expected: Menu appears, can navigate and select options

**Step 3: Commit**

```bash
git add src/pyafk/cli/ui/interactive.py
git commit -m "feat(ui): add main interactive menu with Typer integration"
```

---

### Task 7: Implement Config screen

**Files:**
- Modify: `src/pyafk/cli/ui/interactive.py`
- Modify: `src/pyafk/utils/config.py` (add editor field)

**Step 1: Add editor to Config**

In `src/pyafk/utils/config.py`, add to `TOGGLES` dict and `_load`:

```python
# In class Config, update TOGGLES:
TOGGLES: dict[str, str] = {
    "debug": "Log to ~/.config/pyafk/debug.log",
    "daemon_enabled": "Background polling (vs inline)",
    "disable_stop_hook": "Skip stop hook notifications",
    "disable_subagent_hook": "Skip subagent finished notifications",
}

# In _load(), add after other defaults:
self.editor = os.environ.get("EDITOR", "vim")

# In _load(), add to config file loading:
self.editor = data.get("editor", os.environ.get("EDITOR", "vim"))

# In save(), add to data dict:
"editor": self.editor,
```

**Step 2: Implement interactive_config**

Replace the placeholder in `interactive.py`:

```python
def interactive_config() -> None:
    """Interactive config editor with toggles and text fields."""
    import readchar

    pyafk_dir = get_pyafk_dir()

    while True:
        config = Config(pyafk_dir)

        clear_screen()
        console.print("[bold]Config[/bold]\n")

        # Build items list: (label, type, key, value)
        items: list[tuple[str, str, str, any]] = []

        # Add toggles
        for attr, desc in Config.TOGGLES.items():
            value = getattr(config, attr, False)
            items.append((f"{attr:<24} {desc}", "bool", attr, value))

        # Add text fields
        token_display = "**********" + config.telegram_bot_token[-4:] if config.telegram_bot_token and len(config.telegram_bot_token) > 4 else config.telegram_bot_token or "(not set)"
        items.append((f"{'telegram_bot_token':<24} {token_display}", "text", "telegram_bot_token", config.telegram_bot_token or ""))

        chat_display = config.telegram_chat_id or "(not set)"
        items.append((f"{'telegram_chat_id':<24} {chat_display}", "text", "telegram_chat_id", config.telegram_chat_id or ""))

        editor_display = config.editor or "$EDITOR"
        items.append((f"{'editor':<24} {editor_display}", "text", "editor", config.editor or ""))

        cursor = 0
        status_msg = ""

        while True:
            # Render
            clear_screen()
            console.print("[bold]Config[/bold]\n")

            for i, (label, item_type, key, value) in enumerate(items):
                prefix = "> " if i == cursor else "  "

                if item_type == "bool":
                    checkbox = "[x]" if value else "[ ]"
                    console.print(f"{prefix}{checkbox} {label}")
                else:
                    console.print(f"{prefix}    {label}")

            console.print()
            if status_msg:
                console.print(f"[green]✓ {status_msg}[/green]")
            console.print()
            console.print("[dim]↑↓ navigate • Space/Enter toggle/edit • q back[/dim]")

            # Handle input
            key = readchar.readkey()
            status_msg = ""

            if key in (readchar.key.UP, "k"):
                cursor = max(0, cursor - 1)
            elif key in (readchar.key.DOWN, "j"):
                cursor = min(len(items) - 1, cursor + 1)
            elif key in ("q", readchar.key.CTRL_C):
                return
            elif key in (" ", readchar.key.ENTER, "e"):
                label, item_type, attr, value = items[cursor]

                if item_type == "bool":
                    # Toggle boolean
                    new_value = not value
                    config.set_toggle(attr, new_value)
                    items[cursor] = (label, item_type, attr, new_value)
                    status_msg = f"{attr} = {new_value}"
                else:
                    # Edit text field
                    menu = RichTerminalMenu()
                    new_value = menu.input(f"Enter {attr}:", default=value)
                    if new_value is not None:
                        setattr(config, attr, new_value)
                        config.save()
                        status_msg = f"{attr} updated"
                        break  # Refresh outer loop to update display
```

**Step 3: Test config menu**

Run: `uv run pyafk` then select Config
Expected: Config screen shows, toggles work

**Step 4: Commit**

```bash
git add src/pyafk/cli/ui/interactive.py src/pyafk/utils/config.py
git commit -m "feat(ui): implement config screen with toggles and text fields"
```

---

### Task 8: Implement Rules live panel

**Files:**
- Modify: `src/pyafk/cli/ui/interactive.py`

**Step 1: Implement interactive_rules**

Replace the placeholder:

```python
def interactive_rules() -> None:
    """Interactive rules management with live panel."""
    import readchar
    from rich.live import Live

    from pyafk.cli.helpers import add_rule, get_rules, remove_rule
    from pyafk.cli.ui.panels import (
        LIVE_REFRESH_RATE,
        calculate_visible_range,
        format_scroll_indicator,
        get_terminal_size,
    )

    pyafk_dir = get_pyafk_dir()
    menu = RichTerminalMenu()

    cursor = 0
    scroll_offset = 0
    status_msg = ""

    def build_panel() -> Panel:
        nonlocal cursor, scroll_offset

        rules = get_rules(pyafk_dir)

        # Sort rules by tool name, then pattern
        def sort_key(rule):
            pattern = rule["pattern"]
            if "(" in pattern:
                tool = pattern.split("(")[0]
                rest = pattern.split("(", 1)[1]
            else:
                tool = pattern
                rest = ""
            return (tool.lower(), rest.lower())

        rules = sorted(rules, key=sort_key)

        if not rules:
            return Panel(
                "[dim]No rules defined.[/dim]\n\n"
                "[dim]Press 'a' to add a rule[/dim]",
                title="Rules",
                border_style="cyan",
            )

        # Calculate visible range
        _, height = get_terminal_size()
        max_visible = max(5, height - 10)

        start, end, scroll_offset = calculate_visible_range(
            cursor, len(rules), max_visible, scroll_offset
        )

        # Build content
        lines = []

        # Top scroll indicator
        top_ind, _ = format_scroll_indicator(start, len(rules) - end)
        if top_ind:
            lines.append(f"[dim]{top_ind}[/dim]")
            lines.append("")

        # Visible rules
        for i in range(start, end):
            rule = rules[i]
            prefix = "> " if i == cursor else "  "
            icon = "[green]✓[/green]" if rule["action"] == "approve" else "[red]✗[/red]"
            pattern = rule["pattern"]

            if i == cursor:
                lines.append(f"[cyan]{prefix}{icon} {pattern}[/cyan]")
            else:
                lines.append(f"{prefix}{icon} {pattern}")

        # Bottom scroll indicator
        _, bottom_ind = format_scroll_indicator(start, len(rules) - end)
        if bottom_ind:
            lines.append("")
            lines.append(f"[dim]{bottom_ind}[/dim]")

        # Status message
        if status_msg:
            lines.append("")
            lines.append(f"[green]✓ {status_msg}[/green]")

        return Panel(
            "\n".join(lines),
            title="Rules",
            border_style="cyan",
        )

    while True:
        rules = get_rules(pyafk_dir)

        clear_screen()
        console.print(build_panel())
        console.print()
        console.print("[dim]↑↓/jk navigate • Space toggle • Enter/e edit • a add • d delete • q back[/dim]")

        key = readchar.readkey()
        old_status = status_msg
        status_msg = ""

        if key in (readchar.key.UP, "k"):
            cursor = max(0, cursor - 1)
        elif key in (readchar.key.DOWN, "j"):
            cursor = min(max(0, len(rules) - 1), cursor + 1)
        elif key in ("q", readchar.key.CTRL_C):
            return
        elif key == " " and rules:
            # Toggle action
            rule = rules[cursor]
            new_action = "deny" if rule["action"] == "approve" else "approve"
            remove_rule(pyafk_dir, rule["id"])
            add_rule(pyafk_dir, rule["pattern"], new_action)
            status_msg = f"Toggled to {new_action}"
        elif key in (readchar.key.ENTER, "e") and rules:
            # Edit pattern
            rule = rules[cursor]
            # Parse existing pattern
            if "(" in rule["pattern"]:
                old_tool = rule["pattern"].split("(")[0]
                old_arg = rule["pattern"].split("(", 1)[1].rstrip(")")
            else:
                old_tool = rule["pattern"]
                old_arg = ""

            new_pattern = menu.input(f"Pattern for {old_tool}:", default=old_arg)
            if new_pattern is not None:
                full_pattern = f"{old_tool}({new_pattern})" if new_pattern else f"{old_tool}(*)"
                remove_rule(pyafk_dir, rule["id"])
                add_rule(pyafk_dir, full_pattern, rule["action"])
                status_msg = f"Updated: {full_pattern}"
        elif key == "a":
            # Add new rule
            if _add_rule_form(pyafk_dir):
                status_msg = "Rule added"
        elif key == "d" and rules:
            # Delete with confirmation
            rule = rules[cursor]
            if menu.confirm(f"Delete '{rule['pattern']}'?"):
                remove_rule(pyafk_dir, rule["id"])
                cursor = max(0, min(cursor, len(rules) - 2))
                status_msg = "Rule deleted"


def _add_rule_form(pyafk_dir) -> bool:
    """Add rule form. Returns True if rule was added."""
    import readchar

    from pyafk.cli.helpers import add_rule

    menu = RichTerminalMenu()

    tool_options = [
        "Bash", "Edit", "Write", "Read", "Skill",
        "WebFetch", "WebSearch", "Task", "mcp__*", "(custom)"
    ]

    # Form state
    tool_idx = 0
    pattern = "*"
    action_approve = True
    cursor = 0  # 0=tool, 1=pattern, 2=action

    while True:
        clear_screen()
        console.print("[bold]Add Rule[/bold]\n")

        # Tool row
        tool_prefix = "> " if cursor == 0 else "  "
        console.print(f"{tool_prefix}Tool:     {tool_options[tool_idx]}")

        # Pattern row
        pattern_prefix = "> " if cursor == 1 else "  "
        console.print(f"{pattern_prefix}Pattern:  {pattern}")

        # Action row
        action_prefix = "> " if cursor == 2 else "  "
        action_icon = "[green]✓[/green]" if action_approve else "[red]✗[/red]"
        action_text = "approve" if action_approve else "deny"
        console.print(f"{action_prefix}Action:   {action_icon} {action_text}")

        console.print()
        console.print("[dim]↑↓ navigate • Space cycle/toggle • Enter edit pattern • s save • q cancel[/dim]")

        key = readchar.readkey()

        if key in (readchar.key.UP, "k"):
            cursor = max(0, cursor - 1)
        elif key in (readchar.key.DOWN, "j"):
            cursor = min(2, cursor + 1)
        elif key in ("q", readchar.key.CTRL_C):
            return False
        elif key == "s":
            # Save
            tool = tool_options[tool_idx]
            if tool == "(custom)":
                tool = menu.input("Enter tool name:")
                if not tool:
                    continue

            full_pattern = f"{tool}({pattern})"
            action = "approve" if action_approve else "deny"
            add_rule(pyafk_dir, full_pattern, action)
            return True
        elif key == " ":
            if cursor == 0:
                # Cycle tool
                tool_idx = (tool_idx + 1) % len(tool_options)
            elif cursor == 2:
                # Toggle action
                action_approve = not action_approve
        elif key in (readchar.key.ENTER, "e"):
            if cursor == 0:
                # Cycle tool (same as space)
                tool_idx = (tool_idx + 1) % len(tool_options)
            elif cursor == 1:
                # Edit pattern
                new_pattern = menu.input("Pattern:", default=pattern)
                if new_pattern is not None:
                    pattern = new_pattern
            elif cursor == 2:
                # Toggle action
                action_approve = not action_approve
```

**Step 2: Test rules menu**

Run: `uv run pyafk` then select Manage Rules
Expected: Rules panel shows, can navigate, toggle, add, delete

**Step 3: Commit**

```bash
git add src/pyafk/cli/ui/interactive.py
git commit -m "feat(ui): implement rules live panel with keyboard navigation"
```

---

### Task 9: Implement Wizard

**Files:**
- Modify: `src/pyafk/cli/ui/interactive.py`

**Step 1: Implement run_wizard**

Replace the placeholder:

```python
def run_wizard() -> None:
    """First-time setup wizard."""
    from pyafk.cli.helpers import do_telegram_test
    from pyafk.cli.install import (
        CAPTAIN_HOOK_DIR,
        do_captain_hook_install,
        do_standalone_install,
    )

    menu = RichTerminalMenu()
    pyafk_dir = get_pyafk_dir()
    pyafk_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Welcome
    clear_screen()
    console.print(Panel(
        "[bold cyan]pyafk Setup[/bold cyan]\n\n"
        "[dim]Remote approval for Claude Code[/dim]\n\n"
        "[bold]How it works:[/bold]\n"
        "1. Intercepts Claude tool calls\n"
        "2. Sends requests to Telegram\n"
        "3. You approve/deny from phone",
        border_style="cyan",
    ))
    console.print()
    console.print("[dim]Enter select • q exit[/dim]\n")

    choice = menu.select(["Continue", "Exit"])
    if choice is None or choice == 1:
        return

    # Step 2: Install hooks
    clear_screen()
    console.print("[bold]Install Hooks[/bold]\n")

    captain_available = CAPTAIN_HOOK_DIR.exists()

    options = ["Standalone         Write to ~/.claude/settings.json"]
    if captain_available:
        options.append("Captain-hook       Use hook manager")
    else:
        options.append("[dim]Captain-hook       (not installed)[/dim]")

    console.print("[dim]Enter select • q cancel[/dim]\n")
    choice = menu.select(options)

    if choice is None:
        return

    if choice == 0:
        do_standalone_install(pyafk_dir)
    elif choice == 1 and captain_available:
        do_captain_hook_install()

    console.print()

    # Step 3: Telegram setup
    clear_screen()
    console.print("[bold]Telegram Setup[/bold]\n")
    console.print("1. Create a bot: [cyan]https://telegram.me/BotFather[/cyan]")
    console.print("2. Get chat ID:  [cyan]https://t.me/getmyid_bot[/cyan]\n")

    config = Config(pyafk_dir)

    bot_token = menu.input("Bot token:", default=config.telegram_bot_token or "")
    if bot_token:
        config.telegram_bot_token = bot_token

    chat_id = menu.input("Chat ID:", default=config.telegram_chat_id or "")
    if chat_id:
        config.telegram_chat_id = chat_id

    if bot_token or chat_id:
        config.save()
        console.print("\n[green]Telegram configured![/green]")

        # Step 4: Test connection
        if menu.confirm("Send test message?", default=True):
            do_telegram_test(config)

    # Step 5: Enable pyafk
    console.print()
    if menu.confirm("Enable pyafk now?", default=True):
        config.set_mode("on")
        console.print("[green]pyafk enabled![/green]")

    # Ensure config is saved
    config.save()

    # Step 6: Done
    console.print()
    console.print(Panel(
        "[bold green]Setup complete![/bold green]\n\n"
        f"[dim]Config:[/dim] {pyafk_dir}\n\n"
        "[dim]Run[/dim] [cyan]pyafk[/cyan] [dim]to manage[/dim]",
        border_style="green",
    ))
    input("\nPress Enter to continue...")
```

**Step 2: Test wizard**

To test, temporarily remove config: `mv ~/.config/pyafk ~/.config/pyafk.bak`
Run: `uv run pyafk`
Expected: Wizard runs
Restore: `mv ~/.config/pyafk.bak ~/.config/pyafk`

**Step 3: Commit**

```bash
git add src/pyafk/cli/ui/interactive.py
git commit -m "feat(ui): implement setup wizard with modern UI"
```

---

## Phase 4: Cleanup

### Task 10: Remove old UI code

**Files:**
- Delete: `src/pyafk/cli/ui.py` (old UI utilities)
- Modify: `src/pyafk/cli/interactive.py` → delete entirely (replaced by ui/interactive.py)

**Step 1: Remove old files**

```bash
rm src/pyafk/cli/ui.py
rm src/pyafk/cli/interactive.py
```

**Step 2: Update any remaining imports**

Search for old imports and update:
- `from pyafk.cli.ui import` → `from pyafk.cli.ui.panels import`
- `from pyafk.cli.interactive import` → `from pyafk.cli.ui.interactive import`

Check commands.py for any questionary imports and remove them.

**Step 3: Run tests**

Run: `uv run pytest`
Expected: All tests pass (some may need updates for removed questionary)

**Step 4: Commit**

```bash
git add -A
git commit -m "refactor: remove old questionary-based UI code"
```

---

### Task 11: Update tests

**Files:**
- Modify: `tests/test_cli.py` (if it tests interactive menu)

**Step 1: Check for questionary mocks**

```bash
grep -r "questionary" tests/
```

**Step 2: Update or remove questionary-related tests**

If tests mock questionary, either:
- Update to mock new UI components
- Remove if they test implementation details

**Step 3: Add basic smoke tests for new UI**

```python
# In tests/test_cli.py or new file

def test_cli_help():
    """Test CLI help works."""
    from typer.testing import CliRunner
    from pyafk.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "pyafk" in result.output


def test_cli_status():
    """Test status command."""
    from typer.testing import CliRunner
    from pyafk.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
```

**Step 4: Run full test suite**

Run: `uv run pytest`
Expected: All tests pass

**Step 5: Commit**

```bash
git add tests/
git commit -m "test: update tests for new Typer CLI"
```

---

### Task 12: Final verification

**Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: All pass

**Step 2: Manual testing**

Test each flow:
- `pyafk` → main menu works
- `pyafk status` → shows status
- `pyafk on` / `pyafk off` → toggles
- `pyafk rules list` → shows rules
- Main menu → Rules → add/edit/delete
- Main menu → Config → toggle/edit
- Fresh install → wizard flows

**Step 3: Verify hook performance**

Run: `time uv run pyafk hook PreToolUse < /dev/null`
Expected: Fast (< 0.5s ideally)

**Step 4: Final commit**

```bash
git add -A
git commit -m "feat: complete menu system redesign with Typer CLI"
```
