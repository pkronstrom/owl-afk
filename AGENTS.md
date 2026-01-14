# owl

Remote approval system for Claude Code via Telegram.

## Stack

Python 3.10+, aiosqlite, httpx, typer, rich

## Structure

```
src/owl/
├── cli/                      # Typer CLI: on/off/status/rules/debug/install
├── core/
│   ├── handlers/             # Telegram callback handlers (approval, chain, rules, batch)
│   ├── command_parser.py     # Bash chain parsing (&&, ||, ;, pipes)
│   ├── manager.py            # ApprovalManager - main API, leader polling
│   ├── poller.py             # Telegram polling, PollLock, leader election
│   ├── rules.py              # Pattern matching engine
│   └── storage.py            # SQLite: requests, rules, sessions, chain state
├── hooks/                    # Claude Code hook handlers (pretool, posttool, stop, subagent)
├── notifiers/
│   └── telegram.py           # Telegram Bot API, keyboards, message formatting
├── utils/
│   ├── config.py             # Bot token, chat ID from env/config
│   ├── pattern_generator.py  # Generate rule patterns from tool calls
│   └── debug.py              # Debug logging to ~/.config/owl/debug.log
└── data/
    └── safe_defaults.txt     # Default safe patterns for quick setup
```

## Commands

```bash
uv run pytest              # Run tests (191 tests)
uv run mypy src/owl      # Type check
owl on/off/status        # Toggle approval mode
owl rules list/add/remove # Manage auto-approve patterns
owl debug on             # Enable debug logging
```

## Key Patterns

- **Tool patterns**: `ToolName(argument)` e.g., `Bash(git *)`, `Edit(*/src/*)`
- **Wildcards**: `*` matches anything, `*/dir/*` for absolute paths, `dir/*` for relative
- **Chain parsing**: `cmd1 && cmd2` split and approved individually or as batch

## Architecture Notes

### Hook Response Format
Hooks return `hookSpecificOutput` wrapper for Claude Code compatibility.
See `hooks/response.py:make_hook_response()` and `hooks/subagent.py:316-328`.

### Polling Architecture
Leader election via `poll.lock` - one hook polls Telegram, others check DB.
See `poller.py:poll_as_leader()` and `manager.py:_wait_for_response()`.

### Request Deduplication
Multiple hooks may call owl. `storage.py:find_duplicate_pending_request()`
prevents duplicate Telegram messages.

### Chain Pre-approval
`handlers/chain.py:get_or_init_state()` pre-evaluates commands against rules
to show already-allowed commands as checked in chain UI.

### Callback Idempotency
Handlers check `request.status != "pending"` before processing
to handle duplicate callbacks from multiple pollers.

## Adding Features

### New callback handler
1. Create handler class in `core/handlers/` (see `approval.py`)
2. Register with `@HandlerRegistry.register("action_name")`
3. Add keyboard button in `notifiers/telegram.py`

### New rule pattern type
Update `utils/pattern_generator.py:generate_rule_patterns()`

### New hook type
1. Create handler in `hooks/` following `pretool.py` pattern
2. Use `make_hook_response()` for response format
3. Add to `hooks/__init__.py` and `cli/install.py`
