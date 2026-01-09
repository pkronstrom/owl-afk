"""CLI entry point for pyafk.

This module provides the main CLI interface via the `main()` function,
which is the entry point for the `pyafk` command.
"""

import argparse

__all__ = ["main"]

from pyafk.cli.commands import (
    cmd_captain_hook_install,
    cmd_captain_hook_uninstall,
    cmd_debug_off,
    cmd_debug_on,
    cmd_env_list,
    cmd_env_set,
    cmd_env_unset,
    cmd_hook,
    cmd_install,
    cmd_off,
    cmd_on,
    cmd_reset,
    cmd_rules_add,
    cmd_rules_list,
    cmd_rules_remove,
    cmd_status,
    cmd_telegram_test,
    cmd_uninstall,
)
from pyafk.cli.interactive import interactive_menu


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="pyafk - Remote approval system for Claude Code",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command")

    # status
    status_parser = subparsers.add_parser("status", help="Show current status")
    status_parser.set_defaults(func=cmd_status)

    # on
    on_parser = subparsers.add_parser("on", help="Enable pyafk")
    on_parser.set_defaults(func=cmd_on)

    # off
    off_parser = subparsers.add_parser("off", help="Disable pyafk")
    off_parser.set_defaults(func=cmd_off)

    # install
    install_parser = subparsers.add_parser(
        "install", help="Install pyafk hooks (standalone)"
    )
    install_parser.set_defaults(func=cmd_install)

    # uninstall
    uninstall_parser = subparsers.add_parser("uninstall", help="Uninstall pyafk hooks")
    uninstall_parser.set_defaults(func=cmd_uninstall)

    # reset
    reset_parser = subparsers.add_parser("reset", help="Reset database and rules")
    reset_parser.add_argument("--force", action="store_true", help="Skip confirmation")
    reset_parser.set_defaults(func=cmd_reset)

    # hook (internal)
    hook_parser = subparsers.add_parser("hook", help="Internal hook handler")
    hook_parser.add_argument("hook_type", help="Hook type (PreToolUse, etc.)")
    hook_parser.set_defaults(func=cmd_hook)

    # debug
    debug_parser = subparsers.add_parser("debug", help="Debug mode commands")
    debug_subparsers = debug_parser.add_subparsers(dest="debug_command")

    debug_on_parser = debug_subparsers.add_parser("on", help="Enable debug logging")
    debug_on_parser.set_defaults(func=cmd_debug_on)

    debug_off_parser = debug_subparsers.add_parser("off", help="Disable debug logging")
    debug_off_parser.set_defaults(func=cmd_debug_off)

    # rules
    rules_parser = subparsers.add_parser("rules", help="Manage auto-approve rules")
    rules_subparsers = rules_parser.add_subparsers(dest="rules_command")

    rules_list_parser = rules_subparsers.add_parser("list", help="List all rules")
    rules_list_parser.set_defaults(func=cmd_rules_list)

    rules_add_parser = rules_subparsers.add_parser("add", help="Add a new rule")
    rules_add_parser.add_argument("pattern", help="Pattern to match")
    rules_add_parser.add_argument(
        "--action",
        choices=["approve", "deny"],
        default="approve",
        help="Action (default: approve)",
    )
    rules_add_parser.set_defaults(func=cmd_rules_add)

    rules_remove_parser = rules_subparsers.add_parser("remove", help="Remove a rule")
    rules_remove_parser.add_argument("rule_id", type=int, help="Rule ID to remove")
    rules_remove_parser.set_defaults(func=cmd_rules_remove)

    # telegram
    telegram_parser = subparsers.add_parser("telegram", help="Telegram configuration")
    telegram_subparsers = telegram_parser.add_subparsers(dest="telegram_command")

    telegram_test_parser = telegram_subparsers.add_parser(
        "test", help="Send a test message"
    )
    telegram_test_parser.set_defaults(func=cmd_telegram_test)

    # env - environment variable overrides
    env_parser = subparsers.add_parser("env", help="Manage env var overrides")
    env_subparsers = env_parser.add_subparsers(dest="env_command")

    env_list_parser = env_subparsers.add_parser("list", help="List env var overrides")
    env_list_parser.set_defaults(func=cmd_env_list)

    env_set_parser = env_subparsers.add_parser("set", help="Set an env var override")
    env_set_parser.add_argument("key", help="Variable name (e.g., DISABLE_STOP_HOOK)")
    env_set_parser.add_argument("value", help="Value (e.g., true)")
    env_set_parser.set_defaults(func=cmd_env_set)

    env_unset_parser = env_subparsers.add_parser(
        "unset", help="Remove an env var override"
    )
    env_unset_parser.add_argument("key", help="Variable name to remove")
    env_unset_parser.set_defaults(func=cmd_env_unset)

    # captain-hook
    captain_parser = subparsers.add_parser(
        "captain-hook", help="Captain-hook integration"
    )
    captain_subparsers = captain_parser.add_subparsers(dest="captain_command")

    captain_install_parser = captain_subparsers.add_parser(
        "install", help="Install pyafk hooks for captain-hook"
    )
    captain_install_parser.set_defaults(func=cmd_captain_hook_install)

    captain_uninstall_parser = captain_subparsers.add_parser(
        "uninstall", help="Remove pyafk hooks from captain-hook"
    )
    captain_uninstall_parser.set_defaults(func=cmd_captain_hook_uninstall)

    args = parser.parse_args()

    if args.command is None:
        # No command - run interactive mode
        interactive_menu()
    elif hasattr(args, "func"):
        args.func(args)
    else:
        # Subcommand group without specific command - show help
        parser.parse_args([args.command, "--help"])


if __name__ == "__main__":
    main()
