# CLAUDE.md

## Project Overview

owl-afk is a remote approval system for Claude Code via Telegram. It intercepts tool calls through Claude Code hooks and sends them to Telegram for approval/denial.

## Architecture

- **Hooks**: `src/owl/hooks/` - PreToolUse, PostToolUse, SessionStart/End, Stop, etc.
- **Core**: `src/owl/core/` - Storage (SQLite/WAL), Poller (Telegram long-polling), handlers (approval/denial/chain/rules)
- **Notifiers**: `src/owl/notifiers/` - Telegram Bot API notifier with Protocol-based interface
- **Utils**: `src/owl/utils/` - Formatting, config, language detection, tool result formatting, debug logging
- **CLI**: `src/owl/cli/` - Typer-based CLI with interactive config menu
- **Command Parser**: `src/owl/core/command_parser.py` - Recursive bash command parser for chains, compounds, wrappers

## Key Patterns

- `analyze_chain()` is the single source of truth for chain structure
- `format_tool_call_html()` is the unified formatter for all Telegram messages (approval, resolved, auto-approval, denial)
- `format_tool_summary()` returns raw (unescaped) strings; HTML escaping happens in `format_tool_call_html()`
- Chain state uses optimistic locking via version numbers in SQLite
- Heavy imports are deferred inside functions (not at module level) for CLI startup performance
- `from __future__ import annotations` enables forward references in dataclasses

## Testing

```bash
uv run pytest tests/ -x -q
```

- Tests use `mock_owl_dir` fixture for fresh SQLite per test
- `tests/helpers/fake_telegram.py` provides `FakeTelegramNotifier` + `ChainApprovalSimulator`
- All tests run with `asyncio_mode = "auto"`

## Config Toggles

Settings in `~/.config/owl/config.json`: `debug`, `auto_approve_notify`, `tool_results`, `stop_hook`, `subagent_hook`, `notification_hook`

## Conventions

- Telegram messages use HTML parse mode with `escape_html()` for all user-supplied content
- `project_id` must always be HTML-escaped before insertion into messages
- Telegram message limit is 4096 chars; code uses 4000 as buffer
- Tool result content is truncated before wrapping in HTML tags (never slice final HTML)
