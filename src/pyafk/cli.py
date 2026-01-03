"""CLI entry point."""

import click


@click.group()
def main():
    """pyafk - Remote approval system for Claude Code."""
    pass


@main.command()
def status():
    """Show current status."""
    click.echo("pyafk is not configured yet")


if __name__ == "__main__":
    main()
