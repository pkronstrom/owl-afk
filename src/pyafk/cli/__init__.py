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
def reset(
    force: bool = typer.Option(False, "--force", help="Skip confirmation"),
) -> None:
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
