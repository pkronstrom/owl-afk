# pyafk - Claude Code Context

Remote approval system for Claude Code via Telegram.

## Project Structure

```
src/pyafk/
├── __init__.py           # Package exports
├── cli.py                # CLI commands (on/off/status/rules/debug/install)
├── core/
│   ├── command_parser.py # Bash command parsing and pattern generation
│   ├── manager.py        # ApprovalManager - main API
│   ├── poller.py         # Telegram polling and callback handling
│   ├── rules.py          # Pattern matching and rules engine
│   └── storage.py        # SQLite storage layer
├── hooks/                # Claude Code hook scripts (installed to ~/.claude/hooks/)
├── notifiers/
│   ├── base.py           # Notifier interface
│   ├── console.py        # Console notifier (for testing)
│   └── telegram.py       # Telegram Bot API notifier
└── utils/
    ├── config.py         # Configuration (bot token, chat ID)
    └── debug.py          # Debug logging utilities
```

## Key Concepts

### Pattern Matching
Patterns use glob-style wildcards:
- `*` matches anything
- `?` matches single character
- Tool calls formatted as `ToolName(argument)` e.g., `Bash(git status)`, `Edit(/path/file.py)`

### Chain Approval
Complex bash commands like `cmd1 && cmd2 || cmd3` are parsed and approved step-by-step or all at once.

### Wrapper Commands
SSH, Docker, sudo, kubectl, etc. are detected and patterns can match the inner command.

## Running Tests

```bash
pytest
```

## Debug Mode

Enable debug logging:
```bash
pyafk debug on
```
Logs go to `~/.config/pyafk/debug.log`.

## Common Tasks

### Adding a new callback handler
1. Add handler method in `poller.py` (e.g., `_handle_new_action`)
2. Register it in `_handle_callback` method
3. Add Telegram keyboard button in `telegram.py`

### Adding a new storage method
1. Add method to `Storage` class in `storage.py`
2. Update any callers to use the new method

### Modifying pattern generation
Update `_generate_rule_patterns` in `poller.py` or pattern functions in `command_parser.py`.
