# pyafk Design Document

A Python rewrite of the AFK remote approval system for Claude Code.

## Goals

- **Fix bugs**: Race conditions, state corruption, Telegram reliability issues
- **Production-ready**: Robust enough for daily use
- **Extensible**: Support for multiple sessions, future integrations, better observability
- **Modular**: Usable as a library (for nearly-headless) and as a standalone CLI
- **KISS**: Simple, minimal dependencies, pipx installable

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    pyafk (library)                      │
├─────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐  │
│  │   Storage   │  │   Rules     │  │   Notifiers     │  │
│  │  (SQLite)   │  │  Engine     │  │ (Telegram/etc)  │  │
│  └─────────────┘  └─────────────┘  └─────────────────┘  │
│         │               │                   │           │
│         └───────────────┼───────────────────┘           │
│                         ▼                               │
│              ┌─────────────────────┐                    │
│              │   ApprovalManager   │  ◄── Core API     │
│              └─────────────────────┘                    │
└─────────────────────────────────────────────────────────┘
            │                           │
            ▼                           ▼
   ┌─────────────────┐        ┌─────────────────────┐
   │  Claude Code    │        │   nearly-headless   │
   │  Hooks (CLI)    │        │   (import library)  │
   └─────────────────┘        └─────────────────────┘
```

## Core Design Decisions

### SQLite WAL Mode for State

Replaces flaky JSON files. WAL mode handles concurrent writes from multiple hook processes safely.

### Single Telegram Poller with Lock

Only one process polls Telegram at a time to avoid stealing updates:

```
┌─────────────────────────────────────────────────────────┐
│  Hook 1 fires     Hook 2 fires     Hook 3 fires        │
│      │                │                │               │
│      ▼                ▼                ▼               │
│  ┌──────────────────────────────────────────────────┐  │
│  │            SQLite WAL (requests table)           │  │
│  └──────────────────────────────────────────────────┘  │
│      │                │                │               │
│      ▼                ▼                ▼               │
│  [acquire lock]   [wait]           [wait]              │
│      │                                                 │
│      ▼                                                 │
│  Poll Telegram once, write ALL responses to SQLite     │
│      │                                                 │
│      ▼                                                 │
│  [release lock] ──► other hooks read their response    │
└─────────────────────────────────────────────────────────┘
```

### Fast Path When Off

When pyafk is disabled, hooks exit instantly (~2ms) without importing heavy modules:

```python
#!/usr/bin/env python3
import sys
import os

MODE_FILE = os.path.expanduser("~/.pyafk/mode")

def get_mode():
    try:
        with open(MODE_FILE) as f:
            return f.read().strip()
    except FileNotFoundError:
        return "off"

if __name__ == "__main__":
    if get_mode() == "off":
        print('{"decision": "approve"}')
        sys.exit(0)

    from pyafk.core import handle_hook
    import asyncio
    asyncio.run(handle_hook(sys.argv, sys.stdin))
```

## Data Model

### requests

```sql
CREATE TABLE requests (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    tool_name       TEXT NOT NULL,
    tool_input      TEXT,
    context         TEXT,
    description     TEXT,
    status          TEXT DEFAULT 'pending',
    telegram_msg_id INTEGER,
    created_at      REAL,
    resolved_at     REAL,
    resolved_by     TEXT
);
```

### sessions

```sql
CREATE TABLE sessions (
    session_id      TEXT PRIMARY KEY,
    project_path    TEXT,
    started_at      REAL,
    last_seen_at    REAL,
    status          TEXT DEFAULT 'active'
);
```

### auto_approve_rules

```sql
CREATE TABLE auto_approve_rules (
    id              INTEGER PRIMARY KEY,
    pattern         TEXT NOT NULL,
    action          TEXT DEFAULT 'approve',
    priority        INTEGER DEFAULT 0,
    created_via     TEXT,
    created_at      REAL
);
```

### audit_log

```sql
CREATE TABLE audit_log (
    id              INTEGER PRIMARY KEY,
    timestamp       REAL,
    event_type      TEXT,
    session_id      TEXT,
    details         TEXT
);
```

## Telegram Message Format

### Approval Request

```
🔧 Tool Request [session: abc123]

Tool: Bash
Description: Run tests for the auth module

Command:
pytest tests/auth/ -v

Context: User asked to verify the authentication changes work

━━━━━━━━━━━━━━━━━━━━━━━
⏱ Timeout: 60m (deny)
```

Buttons: `[✅ Approve] [❌ Deny] [⏭ Approve All] [📝 Add Rule]`

### Session Status

```
📊 Session Status

Session: abc123 (project: ~/myapp)
Status: 🟢 Active (last seen: 5s ago)
Pending: 2 requests
Approved: 14 | Denied: 1 | Auto: 23
```

Buttons: `[📋 Show Queue] [🔕 Pause] [💀 Kill Session]`

### Multi-Session Overview

```
📊 Active Sessions

1. abc123 - ~/myapp - 🟢 2 pending
2. def456 - ~/other - 🟡 idle 5m
3. ghi789 - ~/test  - 🔴 stale 30m
```

Buttons: `[View #1] [View #2] [View #3]`

## CLI Commands

```bash
# Installation
pyafk install          # Set up hooks in ~/.claude/settings.json
pyafk uninstall        # Remove hooks (prompts for data cleanup)

# Mode control
pyafk on               # Enable approval flow
pyafk off              # Disable (fast path)
pyafk status           # Show current mode + active sessions

# Configuration
pyafk config           # Show current config
pyafk config set timeout 3600
pyafk config set timeout_action deny

# Telegram setup
pyafk telegram setup   # Interactive setup
pyafk telegram test    # Send test message

# Rules management
pyafk rules list
pyafk rules add "Bash(git *)" --approve
pyafk rules add "Edit(*.prod.*)" --deny
pyafk rules remove <id>

# Monitoring
pyafk sessions         # List active sessions
pyafk queue            # Show pending approvals
pyafk history          # Show audit log
pyafk tail             # Live stream of events

# Data management
pyafk reset            # Wipe DB but keep config/rules
pyafk export           # Export history to JSON
pyafk import <file>    # Restore from export

# Hook entry points (called by Claude Code)
pyafk hook PreToolUse < stdin
pyafk hook Stop < stdin
pyafk hook SessionStart < stdin
```

## Package Structure

```
pyafk/
├── pyproject.toml
├── src/
│   └── pyafk/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       ├── fast_path.py
│       │
│       ├── core/
│       │   ├── manager.py
│       │   ├── storage.py
│       │   ├── rules.py
│       │   └── poller.py
│       │
│       ├── notifiers/
│       │   ├── base.py
│       │   ├── telegram.py
│       │   └── console.py
│       │
│       ├── hooks/
│       │   ├── handler.py
│       │   ├── pretool.py
│       │   ├── stop.py
│       │   └── session.py
│       │
│       └── utils/
│           ├── config.py
│           └── logging.py
│
└── tests/
```

## Library Usage (for nearly-headless)

```python
from pyafk import ApprovalManager
from pyafk.notifiers import TelegramNotifier

manager = ApprovalManager(db_path="~/.pyafk/pyafk.db")
manager.add_notifier(TelegramNotifier(token=..., chat_id=...))

decision = await manager.request_approval(
    tool_name="ExecuteCode",
    tool_input={"code": "rm -rf /"},
    context="User asked to clean up disk space",
    session_id="my-session-123"
)
```

## Uninstall Behavior

```
pyafk uninstall

Removing Claude Code hooks... done

Found pyafk data in ~/.pyafk/:
  - Database: 2.3 MB (847 requests, 12 sessions)
  - Rules: 5 custom rules
  - Audit log: 1,204 entries

What would you like to do?
  [K] Keep data (can reinstall later)
  [D] Delete everything
  [E] Export history first, then delete
```

## Dependencies

Minimal:
- Python 3.10+
- `aiosqlite` - async SQLite
- `httpx` - async HTTP for Telegram API

No heavy frameworks.

## Installation

```bash
pipx install pyafk
pyafk install
pyafk telegram setup
pyafk on
```
