# Safe Defaults Feature Design

## Overview

Add a simple way to install a set of safe default rules that auto-approve read-only operations, reducing friction for common Claude Code workflows.

## Goals

- Provide sensible defaults for new users
- Rules stored in editable text file
- Duplicate-safe installation
- Minimal implementation

## Storage Format

Text file at `~/.config/pyafk/safe_defaults.txt`:

```
# Safe default rules - one pattern per line
# Lines starting with # are comments

# Read-only tools
Read(*)
Glob(*)
Grep(*)

# Web (read-only)
WebSearch(*)
WebFetch(*)

# Claude internals
TodoWrite(*)
Task(*)

# Git read operations
Bash(git status)
Bash(git diff *)
Bash(git log *)
Bash(git branch *)
Bash(git remote *)
Bash(git show *)
Bash(git worktree list)

# Info commands
Bash(pwd)
Bash(whoami)
Bash(date)
Bash(ls *)
Bash(which *)
Bash(file *)

# File inspection
Bash(cat *)
Bash(head *)
Bash(tail *)
Bash(wc *)

# Version checks
Bash(node --version)
Bash(python --version)
Bash(uv --version)
Bash(npm --version)
```

## Installation Entry Points

### 1. First-time Setup Wizard

In `run_wizard()` at `src/pyafk/cli/ui/interactive.py:591`, after Step 5 (Enable pyafk), add Step 6:

```
Install Safe Defaults?

These rules auto-approve read-only operations like
file reads, searches, git status, etc.

You can edit ~/.config/pyafk/safe_defaults.txt later.

[Yes, install]  [No, skip]
```

### 2. Main Menu

In `interactive_menu()` at `src/pyafk/cli/ui/interactive.py:46`, add menu item after "Manage Rules":

```
Turn on/off
Manage Rules
Install Safe Defaults    ← new
Config
...
```

## Implementation

### New Files

```
src/pyafk/
├── core/
│   └── safe_defaults.py      # parse & install logic
└── data/
    └── __init__.py           # make it a package
    └── safe_defaults.txt     # bundled template
```

### Core Logic (`src/pyafk/core/safe_defaults.py`)

```python
"""Safe defaults installation."""

from importlib import resources
from pathlib import Path

from pyafk.core.storage import Storage
from pyafk.utils.config import get_pyafk_dir


def get_defaults_path() -> Path:
    """Get user's safe defaults file path."""
    return get_pyafk_dir() / "safe_defaults.txt"


def parse_defaults_file(path: Path) -> list[str]:
    """Parse defaults file, return list of patterns."""
    if not path.exists():
        return []

    patterns = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)

    return list(dict.fromkeys(patterns))  # dedupe, preserve order


def ensure_defaults_file() -> Path:
    """Create defaults file from template if it doesn't exist."""
    path = get_defaults_path()
    if not path.exists():
        template = resources.files("pyafk.data").joinpath("safe_defaults.txt")
        path.write_text(template.read_text())
    return path


async def install_safe_defaults(storage: Storage) -> tuple[int, int]:
    """Install safe defaults from config file.

    Returns: (added_count, skipped_count)
    """
    path = ensure_defaults_file()
    patterns = parse_defaults_file(path)

    added, skipped = 0, 0
    for pattern in patterns:
        existing = await storage.get_rule_by_pattern(pattern, "approve")
        if existing:
            skipped += 1
        else:
            await storage.add_rule(
                pattern, "approve", priority=0, created_via="safe_defaults"
            )
            added += 1

    return added, skipped
```

### Menu Integration

**In `run_wizard()` (`src/pyafk/cli/ui/interactive.py:591`):**
- After Step 5 (Enable pyafk), before "Setup complete" panel
- Show confirm: "Install safe defaults?"
- On Yes: call `install_safe_defaults()`, show "Added X rules"

**In `interactive_menu()` (`src/pyafk/cli/ui/interactive.py:46`):**
- Add "Install Safe Defaults" option after "Manage Rules" (line ~84)
- Handler: call `install_safe_defaults()`, show result

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| File doesn't exist | Create from bundled template |
| File is empty | No rules added |
| Duplicate in file | Dedupe before inserting |
| Pattern already in DB | Skip, count in "skipped" |
| Re-run install | Only adds new patterns |

## Testing

- `test_parse_defaults_file()` - comments, blanks, deduplication
- `test_install_safe_defaults()` - mock storage, duplicate handling
