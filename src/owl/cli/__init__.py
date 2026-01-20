"""CLI entry point for owl.

Uses Typer for command routing with lazy loading for performance.
Hook commands stay fast by not importing UI modules.
"""

import typer

__all__ = ["app", "main"]

app = typer.Typer(
    name="owl",
    help="Remote approval system for Claude Code",
    no_args_is_help=False,
)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Launch interactive menu if no command given."""
    if ctx.invoked_subcommand is None:
        # Lazy load UI - only when interactive
        from owl.cli.ui.interactive import interactive_menu

        interactive_menu()


@app.command()
def status() -> None:
    """Show current status."""
    from owl.cli.commands import cmd_status

    cmd_status(None)


@app.command()
def on(
    project: str = typer.Argument(
        None,
        help="Enable for specific project only. Use '.' for cwd. Omit for global.",
    ),
    this: bool = typer.Option(
        False,
        "--this",
        "-t",
        help="Enable for current directory (shorthand for 'owl on .')",
    ),
) -> None:
    """Enable owl."""
    from owl.cli.commands import cmd_on

    # --this is shorthand for owl on .
    if this:
        project = "."
    cmd_on(project)


@app.command()
def off(
    project: str = typer.Argument(
        None,
        help="Disable for specific project. Use '.' for cwd. Omit for global off.",
    ),
    this: bool = typer.Option(
        False,
        "--this",
        "-t",
        help="Disable for current directory (shorthand for 'owl off .')",
    ),
) -> None:
    """Disable owl."""
    from owl.cli.commands import cmd_off

    # --this is shorthand for owl off .
    if this:
        project = "."
    cmd_off(project)


@app.command()
def install() -> None:
    """Install owl hooks (standalone)."""
    from owl.cli.commands import cmd_install

    cmd_install(None)


@app.command()
def uninstall() -> None:
    """Uninstall owl hooks."""
    from owl.cli.commands import cmd_uninstall

    cmd_uninstall(None)


@app.command()
def reset(
    force: bool = typer.Option(False, "--force", help="Skip confirmation"),
) -> None:
    """Reset database and rules."""
    from owl.cli.commands import cmd_reset

    class Args:
        def __init__(self):
            self.force = force

    cmd_reset(Args())


@app.command()
def hook(hook_type: str) -> None:
    """Internal hook handler (called by Claude Code)."""
    from owl.cli.commands import cmd_hook

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
    from owl.cli.commands import cmd_rules_list

    cmd_rules_list(None)


@rules_app.command("add")
def rules_add(
    pattern: str,
    action: str = typer.Option("approve", "--action", help="approve or deny"),
) -> None:
    """Add a new rule."""
    from owl.cli.commands import cmd_rules_add

    class Args:
        def __init__(self):
            self.pattern = pattern
            self.action = action

    cmd_rules_add(Args())


@rules_app.command("remove")
def rules_remove(rule_id: int) -> None:
    """Remove a rule by ID."""
    from owl.cli.commands import cmd_rules_remove

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
    from owl.cli.commands import cmd_telegram_test

    cmd_telegram_test(None)


# Debug subcommand group
debug_app = typer.Typer(help="Debug mode commands")
app.add_typer(debug_app, name="debug")


@debug_app.command("on")
def debug_on() -> None:
    """Enable debug logging."""
    from owl.cli.commands import cmd_debug_on

    cmd_debug_on(None)


@debug_app.command("off")
def debug_off() -> None:
    """Disable debug logging."""
    from owl.cli.commands import cmd_debug_off

    cmd_debug_off(None)


# Env subcommand group
env_app = typer.Typer(help="Manage env var overrides")
app.add_typer(env_app, name="env")


@env_app.command("list")
def env_list() -> None:
    """List env var overrides."""
    from owl.cli.commands import cmd_env_list

    cmd_env_list(None)


@env_app.command("set")
def env_set(key: str, value: str) -> None:
    """Set an env var override."""
    from owl.cli.commands import cmd_env_set

    class Args:
        def __init__(self):
            self.key = key
            self.value = value

    cmd_env_set(Args())


@env_app.command("unset")
def env_unset(key: str) -> None:
    """Remove an env var override."""
    from owl.cli.commands import cmd_env_unset

    class Args:
        def __init__(self):
            self.key = key

    cmd_env_unset(Args())


# Hawk-hooks subcommand group (external hook manager integration)
hawk_app = typer.Typer(help="Hawk-hooks integration")
app.add_typer(hawk_app, name="hawk-hooks")
app.add_typer(hawk_app, name="hawk")  # Short alias


@hawk_app.command("install")
def hawk_install() -> None:
    """Install owl hooks for hawk-hooks."""
    from owl.cli.commands import cmd_hawk_hooks_install

    cmd_hawk_hooks_install(None)


@hawk_app.command("uninstall")
def hawk_uninstall() -> None:
    """Remove owl hooks from hawk-hooks."""
    from owl.cli.commands import cmd_hawk_hooks_uninstall

    cmd_hawk_hooks_uninstall(None)


def cli_main() -> None:
    """Entry point for pyproject.toml scripts."""
    app()


if __name__ == "__main__":
    cli_main()
