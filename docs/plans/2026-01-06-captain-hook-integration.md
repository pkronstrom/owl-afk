# pyafk Captain-Hook Integration Design

## Goal

Make pyafk work both standalone (with daemon) and as hook scripts managed by captain-hook (without daemon).

## Overview

- **Standalone mode**: `pyafk on` starts daemon, handles /msg, /afk, /start commands, polls continuously
- **Captain-hook mode**: No daemon, hooks poll inline during execution, just approval flow

Both modes share the same config, storage, and rules in `~/.config/pyafk/`.

## Changes

### 1. Config Directory

Change from `~/.pyafk/` to `~/.config/pyafk/` (XDG-compliant).

**File:** `src/pyafk/utils/config.py`
- Update `get_pyafk_dir()` default path

**Structure:**
```
~/.config/pyafk/
├── config.json      # Telegram bot token, chat ID
├── pyafk.db         # SQLite (requests, rules, sessions)
├── mode             # "on" or "off"
├── daemon.pid       # Daemon PID file
└── debug.log        # Debug logs (when enabled)
```

### 2. Shared Hook Runner

Create a shared utility for running hooks, used by both CLI and direct module execution.

**New file:** `src/pyafk/hooks/runner.py`
```python
def run_hook(handler):
    """Run an async hook handler with stdin/stdout JSON."""
    import sys
    import json
    import asyncio

    hook_input = json.load(sys.stdin)
    result = asyncio.run(handler(hook_input))
    print(json.dumps(result))
```

**Update each hook module** (`pretool.py`, `posttool.py`, `stop.py`, `subagent.py`):
```python
if __name__ == "__main__":
    from pyafk.hooks.runner import run_hook
    run_hook(handle_<event>)
```

**Update CLI** (`cli.py`):
- Use the same `run_hook()` utility for the `pyafk hook <event>` commands

### 3. Captain-Hook Extras

**New directory:** `extras/captain-hook/`

```
extras/captain-hook/
├── README.md           # Setup instructions
├── install.sh          # Copies wrappers to captain-hook hooks dir
└── hooks/
    ├── pre_tool_use/
    │   └── pyafk.sh
    ├── post_tool_use/
    │   └── pyafk.sh
    ├── stop/
    │   └── pyafk.sh
    └── subagent_stop/
        └── pyafk.sh
```

**Wrapper script template:**
```bash
#!/usr/bin/env bash
# Description: pyafk Telegram approval
# Deps: pyafk
exec python3 -m pyafk.hooks.pretool
```

**install.sh:**
- Check captain-hook hooks directory exists
- Copy wrapper scripts to `~/.config/captain-hook/hooks/{event}/`
- Print instructions to run `captain-hook toggle`

### 4. Documentation

**extras/captain-hook/README.md:**
- Prerequisites (pyafk installed, captain-hook set up)
- Running install.sh
- Enabling hooks via `captain-hook toggle`
- Configuration (`~/.config/pyafk/config.json`)

**Update main README.md:**
- Add section about captain-hook compatibility
- Link to extras/captain-hook/README.md

## Implementation Order

1. Change config directory (`~/.pyafk/` → `~/.config/pyafk/`)
2. Create `hooks/runner.py` with shared `run_hook()` utility
3. Add `if __name__ == "__main__"` to each hook module
4. Update CLI to use shared runner
5. Create `extras/captain-hook/` directory with wrappers and install script
6. Write documentation
7. Test both standalone and captain-hook modes
