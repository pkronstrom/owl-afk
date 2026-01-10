# pyafk

Remote approval system for Claude Code via Telegram.

## Stack

Python 3.11+, aiosqlite, httpx, click

## Structure

```
src/pyafk/
├── cli.py                    # CLI: on/off/status/rules/debug/install
├── core/
│   ├── handlers/             # Telegram callback handlers (approval, chain, rules, batch)
│   ├── command_parser.py     # Bash chain parsing (&&, ||, ;, pipes)
│   ├── manager.py            # ApprovalManager - main API, leader polling
│   ├── poller.py             # Telegram polling, PollLock, leader election
│   ├── rules.py              # Pattern matching engine
│   └── storage.py            # SQLite: requests, rules, sessions, chain state
├── notifiers/
│   └── telegram.py           # Telegram Bot API, keyboards, message formatting
└── utils/
    ├── config.py             # Bot token, chat ID from env/config
    ├── pattern_generator.py  # Generate rule patterns from tool calls
    └── debug.py              # Debug logging to ~/.config/pyafk/debug.log
```

## Commands

```bash
uv run pytest              # Run tests
pyafk on/off/status        # Toggle approval mode
pyafk rules list/add/remove # Manage auto-approve patterns
pyafk debug on             # Enable debug logging
```

## Key Patterns

- **Tool patterns**: `ToolName(argument)` e.g., `Bash(git *)`, `Edit(*/src/*)`
- **Wildcards**: `*` matches anything, patterns use `*/dir/*` for portability across worktrees
- **Chain parsing**: `cmd1 && cmd2` split and approved individually or as batch

## Architecture Notes

### Standalone Polling (no daemon)
Leader election via `poll.lock` - one hook polls Telegram, others check DB.
See `poller.py:poll_as_leader()` and `manager.py:_wait_for_response()`.

### Request Deduplication
Multiple hooks (captain-hook + direct) may call pyafk. `storage.py:find_duplicate_pending_request()`
prevents duplicate Telegram messages.

### Callback Idempotency
Handlers in `core/handlers/` check `request.status != "pending"` before processing
to handle duplicate callbacks from multiple pollers.

## Adding Features

### New callback handler
1. Create handler class in `core/handlers/` (see `approval.py` for pattern)
2. Register action in `core/handlers/dispatcher.py`
3. Add keyboard button in `notifiers/telegram.py`

### New rule pattern type
Update `utils/pattern_generator.py:generate_rule_patterns()`

### New storage method
Add to `core/storage.py`, use `await self.conn.execute()` pattern
