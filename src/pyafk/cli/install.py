"""Installation helpers for pyafk hooks."""

import json
import subprocess
from pathlib import Path

from pyafk.cli.ui import console

# Captain-hook integration
CAPTAIN_HOOK_DIR = Path.home() / ".config" / "captain-hook" / "hooks"
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


def get_pyafk_hooks() -> dict:
    """Get the hook configuration for pyafk."""
    return {
        "PreToolUse": [
            {
                "matcher": "Bash|Edit|Write|MultiEdit|WebFetch|Skill|mcp__.*",
                "hooks": [
                    {
                        "type": "command",
                        "command": "pyafk hook PreToolUse",
                        "timeout": 3600,
                    }
                ],
            }
        ],
        "PostToolUse": [
            {
                "matcher": "Bash|Edit|Write|MultiEdit|WebFetch|Skill|mcp__.*",
                "hooks": [
                    {
                        "type": "command",
                        "command": "pyafk hook PostToolUse",
                    }
                ],
            }
        ],
        "PermissionRequest": [
            {
                "matcher": "Bash|Edit|Write|MultiEdit|WebFetch|Skill|mcp__.*",
                "hooks": [
                    {
                        "type": "command",
                        "command": "pyafk hook PermissionRequest",
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
                        "command": "pyafk hook SubagentStop",
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
                        "command": "pyafk hook Stop",
                    }
                ],
            }
        ],
        "SessionStart": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "pyafk hook SessionStart",
                    }
                ],
            }
        ],
        "PreCompact": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "pyafk hook PreCompact",
                    }
                ],
            }
        ],
        "SessionEnd": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "pyafk hook SessionEnd",
                    }
                ],
            }
        ],
    }


def is_pyafk_hook(hook_entry: dict) -> bool:
    """Check if a hook entry belongs to pyafk."""
    command = hook_entry.get("command", "")
    if "pyafk hook" in command:
        return True
    for hook in hook_entry.get("hooks", []):
        if "pyafk hook" in hook.get("command", ""):
            return True
    return False


def check_hooks_installed() -> tuple[bool, str]:
    """Check if pyafk hooks are installed."""
    settings_path = get_claude_settings_path()
    if settings_path and settings_path.exists():
        settings = load_claude_settings(settings_path)
        hooks = settings.get("hooks", {})
        for hook_entries in hooks.values():
            for entry in hook_entries:
                if is_pyafk_hook(entry):
                    return True, "standalone"

    captain_hook_dir = Path.home() / ".config" / "captain-hook" / "hooks"
    if (captain_hook_dir / "pre_tool_use" / "pyafk-pre_tool_use.sh").exists():
        return True, "captain-hook"

    return False, "none"


def do_standalone_install(pyafk_dir: Path):
    """Perform standalone installation."""
    settings_path = get_claude_settings_path()

    console.print("[bold]Installing standalone hooks...[/bold]")

    settings = load_claude_settings(settings_path)
    existing_hooks = settings.get("hooks", {})

    pyafk_hooks = get_pyafk_hooks()

    new_hooks = existing_hooks.copy()
    for hook_type, hook_entries in pyafk_hooks.items():
        if hook_type not in new_hooks:
            new_hooks[hook_type] = []
        new_hooks[hook_type] = [h for h in new_hooks[hook_type] if not is_pyafk_hook(h)]
        new_hooks[hook_type].extend(hook_entries)

    settings["hooks"] = new_hooks

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    save_claude_settings(settings_path, settings)

    for hook_type in pyafk_hooks:
        console.print(f"  [green]✓[/green] {hook_type}")

    console.print()
    console.print(f"[dim]Settings: {settings_path}[/dim]")


def do_captain_hook_install():
    """Perform captain-hook installation."""
    console.print("[bold]Installing captain-hook hooks...[/bold]")

    for event in HOOK_EVENTS:
        event_dir = CAPTAIN_HOOK_DIR / event
        event_dir.mkdir(parents=True, exist_ok=True)

        hook_config = HOOK_CONFIG[event]
        hook_type = hook_config["type"]
        description = hook_config["description"]
        wrapper_name = f"pyafk-{event}.sh"
        wrapper_path = event_dir / wrapper_name

        wrapper_content = f"""#!/usr/bin/env bash
# Description: {description}
# Deps: pyafk
exec pyafk hook {hook_type}
"""
        wrapper_path.write_text(wrapper_content)
        wrapper_path.chmod(0o755)
        console.print(f"  [green]✓[/green] {event}/{wrapper_name}")

    # Enable hooks via captain-hook CLI
    console.print()
    console.print("Enabling hooks...")
    hook_names = [f"{event}/pyafk-{event}" for event in HOOK_EVENTS]
    try:
        subprocess.run(
            ["captain-hook", "enable"] + hook_names,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["captain-hook", "toggle"],
            check=True,
            capture_output=True,
        )
        console.print("[green]Done![/green]")
    except subprocess.CalledProcessError as e:
        console.print(f"[yellow]Warning:[/yellow] Failed to auto-enable: {e}")
        console.print("Run [cyan]captain-hook toggle[/cyan] to enable pyafk hooks.")
    except FileNotFoundError:
        console.print("[yellow]Warning:[/yellow] captain-hook CLI not found")
        console.print("Run [cyan]captain-hook toggle[/cyan] to enable pyafk hooks.")
