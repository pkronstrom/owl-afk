"""Claude Code hook handlers.

This package contains the hook scripts that integrate with Claude Code:
- pretool: Pre-tool-use approval hook
- posttool: Post-tool-use notification hook
- stop: Session stop notification hook
- subagent: Subagent completion notification hook
- session: Session tracking hook

These are invoked via `pyafk hook <hook_type>` and read/write JSON to stdin/stdout.
They are not intended for direct import.
"""

__all__: list[str] = []  # Hooks are CLI scripts, not library modules
