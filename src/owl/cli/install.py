"""Installation helpers for owl hooks."""

import json
import subprocess
from pathlib import Path

from owl.cli.ui import console

# Hawk-hooks integration
HAWK_HOOKS_DIR = Path.home() / ".config" / "hawk-hooks" / "hooks"
HOOK_CONFIG = {
    "pre_tool_use": {
        "type": "PreToolUse",
        "description": "Remote approval for tool calls via Telegram",
    },
    "post_tool_use": {
        "type": "PostToolUse",
        "description": "Deliver queued Telegram messages after tool execution",
    },
    "stop": {
        "type": "Stop",
        "description": "Notify on session stop via Telegram",
    },
    "subagent_stop": {
        "type": "SubagentStop",
        "description": "Notify when subagents complete via Telegram",
    },
}
HOOK_EVENTS = list(HOOK_CONFIG.keys())


def get_claude_settings_path() -> Path:
    """Get path to Claude settings.json."""
    return Path.home() / ".claude" / "settings.json"


def load_claude_settings(settings_path: Path) -> dict:
    """Load Claude settings from file."""
    if settings_path.exists():
        try:
            return json.loads(settings_path.read_text())
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_claude_settings(settings_path: Path, settings: dict):
    """Save Claude settings to file."""
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2))


def get_owl_hooks() -> dict:
    """Get the hook configuration for owl."""
    return {
        "PreToolUse": [
            {
                "matcher": "Bash|Edit|Write|MultiEdit|WebFetch|WebSearch|Skill|mcp__.*",
                "hooks": [
                    {
                        "type": "command",
                        "command": "owl hook PreToolUse",
                        "timeout": 3600,
                    }
                ],
            }
        ],
        "PostToolUse": [
            {
                "matcher": "Bash|Edit|Write|MultiEdit|WebFetch|WebSearch|Skill|mcp__.*",
                "hooks": [
                    {
                        "type": "command",
                        "command": "owl hook PostToolUse",
                    }
                ],
            }
        ],
        "PermissionRequest": [
            {
                "matcher": "Bash|Edit|Write|MultiEdit|WebFetch|WebSearch|Skill|mcp__.*",
                "hooks": [
                    {
                        "type": "command",
                        "command": "owl hook PermissionRequest",
                        "timeout": 3600,
                    }
                ],
            }
        ],
        "SubagentStop": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "owl hook SubagentStop",
                        "timeout": 3600,
                    }
                ],
            }
        ],
        "Stop": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "owl hook Stop",
                    }
                ],
            }
        ],
        "SessionStart": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "owl hook SessionStart",
                    }
                ],
            }
        ],
        "PreCompact": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "owl hook PreCompact",
                    }
                ],
            }
        ],
        "SessionEnd": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "owl hook SessionEnd",
                    }
                ],
            }
        ],
    }


def is_owl_hook(hook_entry: dict) -> bool:
    """Check if a hook entry belongs to owl."""
    command = hook_entry.get("command", "")
    if "owl hook" in command:
        return True
    for hook in hook_entry.get("hooks", []):
        if "owl hook" in hook.get("command", ""):
            return True
    return False


def check_hooks_installed() -> tuple[bool, str]:
    """Check if owl hooks are installed.

    Returns:
        Tuple of (is_installed, install_type) where install_type is
        "standalone", "hawk-hooks", or "none".
    """
    settings_path = get_claude_settings_path()
    if settings_path and settings_path.exists():
        settings = load_claude_settings(settings_path)
        hooks = settings.get("hooks", {})
        for hook_entries in hooks.values():
            for entry in hook_entries:
                if is_owl_hook(entry):
                    return True, "standalone"

    hawk_hooks_dir = Path.home() / ".config" / "hawk-hooks" / "hooks"
    if (hawk_hooks_dir / "pre_tool_use" / "owl-pre_tool_use.sh").exists():
        return True, "hawk-hooks"

    return False, "none"


def check_hawk_hooks_installed() -> bool:
    """Check if hawk-hooks owl integration is installed."""
    hawk_hooks_dir = Path.home() / ".config" / "hawk-hooks" / "hooks"
    return (hawk_hooks_dir / "pre_tool_use" / "owl-pre_tool_use.sh").exists()


def check_standalone_installed() -> bool:
    """Check if standalone owl hooks are installed."""
    settings_path = get_claude_settings_path()
    if settings_path and settings_path.exists():
        settings = load_claude_settings(settings_path)
        hooks = settings.get("hooks", {})
        for hook_entries in hooks.values():
            for entry in hook_entries:
                if is_owl_hook(entry):
                    return True
    return False


def do_standalone_install(owl_dir: Path, force: bool = False):
    """Perform standalone installation.

    Args:
        owl_dir: Path to owl config directory.
        force: If True, proceed even if hawk-hooks is installed.
    """
    # Check for conflict
    if check_hawk_hooks_installed() and not force:
        console.print(
            "[red]Error:[/red] hawk-hooks owl integration is already installed."
        )
        console.print(
            "Having both can cause duplicate approvals and notifications."
        )
        console.print()
        console.print("Options:")
        console.print("  1. Run [cyan]owl hawk-hooks uninstall[/cyan] first")
        console.print("  2. Use [cyan]owl install --force[/cyan] to override")
        return

    settings_path = get_claude_settings_path()

    console.print("[bold]Installing standalone hooks...[/bold]")

    settings = load_claude_settings(settings_path)
    existing_hooks = settings.get("hooks", {})

    owl_hooks = get_owl_hooks()

    new_hooks = existing_hooks.copy()
    for hook_type, hook_entries in owl_hooks.items():
        if hook_type not in new_hooks:
            new_hooks[hook_type] = []
        new_hooks[hook_type] = [h for h in new_hooks[hook_type] if not is_owl_hook(h)]
        new_hooks[hook_type].extend(hook_entries)

    settings["hooks"] = new_hooks

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    save_claude_settings(settings_path, settings)

    for hook_type in owl_hooks:
        console.print(f"  [green]✓[/green] {hook_type}")

    console.print()
    console.print(f"[dim]Settings: {settings_path}[/dim]")


def do_hawk_hooks_install(force: bool = False):
    """Perform hawk-hooks installation.

    Args:
        force: If True, proceed even if standalone is installed.
    """
    # Check for conflict
    if check_standalone_installed() and not force:
        console.print(
            "[red]Error:[/red] Standalone owl hooks are already installed."
        )
        console.print(
            "Having both can cause duplicate approvals and notifications."
        )
        console.print()
        console.print("Options:")
        console.print("  1. Run [cyan]owl uninstall[/cyan] first")
        console.print("  2. Use [cyan]owl hawk-hooks install --force[/cyan] to override")
        return

    console.print("[bold]Installing hawk-hooks hooks...[/bold]")

    for event in HOOK_EVENTS:
        event_dir = HAWK_HOOKS_DIR / event
        event_dir.mkdir(parents=True, exist_ok=True)

        hook_config = HOOK_CONFIG[event]
        hook_type = hook_config["type"]
        description = hook_config["description"]
        wrapper_name = f"owl-{event}.sh"
        wrapper_path = event_dir / wrapper_name

        # Add timeout for hooks that wait for user approval
        needs_timeout = hook_type in (
            "PreToolUse",
            "PermissionRequest",
            "SubagentStop",
            "Stop",
        )
        timeout_line = "# Timeout: 3600\n" if needs_timeout else ""

        wrapper_content = f"""#!/usr/bin/env bash
# Description: {description}
# Deps: owl
{timeout_line}exec owl hook {hook_type}
"""
        wrapper_path.write_text(wrapper_content)
        wrapper_path.chmod(0o755)
        console.print(f"  [green]✓[/green] {event}/{wrapper_name}")

    # Enable hooks via hawk-hooks CLI
    console.print()
    console.print("Enabling hooks...")
    hook_names = [f"{event}/owl-{event}" for event in HOOK_EVENTS]
    try:
        subprocess.run(
            ["hawk-hooks", "enable"] + hook_names,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["hawk-hooks", "toggle"],
            check=True,
            capture_output=True,
        )
        console.print("[green]Done![/green]")
    except subprocess.CalledProcessError as e:
        console.print(f"[yellow]Warning:[/yellow] Failed to auto-enable: {e}")
        console.print("Run [cyan]hawk-hooks toggle[/cyan] to enable owl hooks.")
    except FileNotFoundError:
        console.print("[yellow]Warning:[/yellow] hawk-hooks CLI not found")
        console.print("Run [cyan]hawk-hooks toggle[/cyan] to enable owl hooks.")
