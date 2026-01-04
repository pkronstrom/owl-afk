# Smart Recursive Rule Pattern Engine Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a recursive command parser that handles bash wrappers, chains, and substitutions to generate granular approval patterns, with multi-step Telegram UI for chain approvals.

**Architecture:** CommandNode tree recursively parses bash commands, extracting wrappers (ssh, docker, sudo) and command chains. Pattern generation walks the tree from specific to general. Multi-step Telegram approval shows stacked command list with progress, using editMessageText to swap keyboards as users work through each command.

**Tech Stack:** Python async, regex for parsing, SQLite for rules, Telegram Bot API editMessageText

---

## Task 1: Create CommandNode data structure and registry

**Files:**
- Create: `src/pyafk/core/command_parser.py`
- Create: `tests/test_command_parser.py`

**Step 1: Write the failing test**

```python
# tests/test_command_parser.py
from pyafk.core.command_parser import CommandNode, CommandType

def test_command_node_simple_command():
    node = CommandNode(
        type=CommandType.FILE_OP,
        name="rm",
        args=["file.txt"],
        full_cmd="rm file.txt"
    )
    assert node.name == "rm"
    assert node.type == CommandType.FILE_OP
    assert node.nested is None

def test_command_node_with_nested():
    nested = CommandNode(type=CommandType.VCS, name="git", args=["log"])
    node = CommandNode(
        type=CommandType.WRAPPER,
        name="ssh",
        params={"host": "aarni"},
        nested=nested,
        full_cmd='ssh aarni "git log"'
    )
    assert node.name == "ssh"
    assert node.nested is not None
    assert node.nested.name == "git"
```

**Step 2: Run test to verify it fails**

```bash
cd /Users/bembu/Projects/pyafk
python -m pytest tests/test_command_parser.py::test_command_node_simple_command -v
```

Expected: FAIL - "ModuleNotFoundError: No module named 'pyafk.core.command_parser'"

**Step 3: Write minimal implementation**

```python
# src/pyafk/core/command_parser.py
from enum import Enum
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

class CommandType(Enum):
    WRAPPER = "wrapper"
    FILE_OP = "file_op"
    VCS = "vcs"
    GENERIC = "generic"

@dataclass
class CommandNode:
    """Represents a command in the tree."""
    type: CommandType
    name: str
    args: List[str] = None
    params: Dict[str, str] = None  # For wrappers: host, container, etc.
    nested: Optional['CommandNode'] = None
    full_cmd: str = ""

    def __post_init__(self):
        if self.args is None:
            self.args = []
        if self.params is None:
            self.params = {}

# Wrapper registry
WRAPPERS = {
    "ssh": {
        "param_keys": ["host"],
        "param_count": 1,
    },
    "docker": {
        "param_keys": ["action", "container"],
        "param_count": 2,
    },
    "sudo": {
        "param_keys": [],
        "param_count": 0,
    },
    "nix-shell": {
        "param_keys": [],
        "param_count": 0,
    },
    "kubectl": {
        "param_keys": ["action"],
        "param_count": 1,
    },
    "screen": {
        "param_keys": ["session"],
        "param_count": 1,
    },
    "tmux": {
        "param_keys": ["session"],
        "param_count": 1,
    },
    "env": {
        "param_keys": [],
        "param_count": 0,
    },
    "timeout": {
        "param_keys": ["seconds"],
        "param_count": 1,
    },
}
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_command_parser.py::test_command_node_simple_command tests/test_command_parser.py::test_command_node_with_nested -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add src/pyafk/core/command_parser.py tests/test_command_parser.py
git commit -m "feat: add CommandNode data structure and wrapper registry"
```

---

## Task 2: Implement command chain splitter

**Files:**
- Modify: `src/pyafk/core/command_parser.py`
- Modify: `tests/test_command_parser.py`

**Step 1: Write the failing test**

```python
def test_split_chain_single_command():
    parser = CommandParser()
    result = parser.split_chain("git log")
    assert len(result) == 1
    assert result[0] == "git log"

def test_split_chain_multiple_commands():
    parser = CommandParser()
    result = parser.split_chain("cd ~/project && npm test && git log")
    assert len(result) == 3
    assert result[0] == "cd ~/project"
    assert result[1] == "npm test"
    assert result[2] == "git log"

def test_split_chain_ignores_operators_in_quotes():
    parser = CommandParser()
    result = parser.split_chain('ssh aarni "cd ~/p && git log"')
    assert len(result) == 1
    assert result[0] == 'ssh aarni "cd ~/p && git log"'

def test_split_chain_pipe_semicolon():
    parser = CommandParser()
    result = parser.split_chain("cat file | grep pattern; echo done")
    assert len(result) == 3
```

**Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_command_parser.py::test_split_chain_single_command -v
```

Expected: FAIL - "CommandParser not defined"

**Step 3: Write minimal implementation**

```python
# Add to src/pyafk/core/command_parser.py
import re

class CommandParser:
    """Parse bash commands into trees."""

    def split_chain(self, cmd: str) -> List[str]:
        """Split command by chain operators (&&, ||, ;, |) respecting quotes."""
        commands = []
        current = ""
        in_single_quote = False
        in_double_quote = False
        i = 0

        while i < len(cmd):
            char = cmd[i]

            # Track quote state
            if char == "'" and not in_double_quote:
                in_single_quote = not in_single_quote
                current += char
                i += 1
                continue
            elif char == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
                current += char
                i += 1
                continue

            # If not in quotes, check for operators
            if not in_single_quote and not in_double_quote:
                # Check for two-char operators first
                if i + 1 < len(cmd):
                    two_char = cmd[i:i+2]
                    if two_char in ("&&", "||"):
                        if current.strip():
                            commands.append(current.strip())
                        current = ""
                        i += 2
                        continue

                # Check single-char operators
                if char in (";", "|"):
                    if current.strip():
                        commands.append(current.strip())
                    current = ""
                    i += 1
                    continue

            current += char
            i += 1

        # Don't forget last command
        if current.strip():
            commands.append(current.strip())

        return commands
```

**Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_command_parser.py::test_split_chain_single_command tests/test_command_parser.py::test_split_chain_multiple_commands tests/test_command_parser.py::test_split_chain_ignores_operators_in_quotes tests/test_command_parser.py::test_split_chain_pipe_semicolon -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add src/pyafk/core/command_parser.py tests/test_command_parser.py
git commit -m "feat: implement command chain splitter"
```

---

## Task 3: Implement wrapper and basic command detection

**Files:**
- Modify: `src/pyafk/core/command_parser.py`
- Modify: `tests/test_command_parser.py`

**Step 1-5:** [Full implementation steps provided in plan]

---

## Task 4: Implement full command tree builder

**Files:**
- Modify: `src/pyafk/core/command_parser.py`
- Modify: `tests/test_command_parser.py`

**Step 1-5:** [Full implementation steps provided in plan]

---

## Task 5: Implement pattern generation from command tree

**Files:**
- Modify: `src/pyafk/core/command_parser.py`
- Modify: `tests/test_command_parser.py`

**Step 1-5:** [Full implementation steps provided in plan]

---

## Task 6: Update poller to use new pattern generator for Bash

**Files:**
- Modify: `src/pyafk/core/poller.py`

**Step 1-5:** [Full implementation steps provided in plan]

---

## Task 7: Implement chain approval flow in Poller

**Files:**
- Modify: `src/pyafk/core/poller.py`
- Modify: `tests/test_poller.py`

**Step 1-5:** [Full implementation steps provided in plan]

---

## Task 8: Add Telegram chain approval UI methods

**Files:**
- Modify: `src/pyafk/notifiers/telegram.py`

**Step 1-5:** [Full implementation steps provided in plan]

---

## Task 9: Update rule matching for chains

**Files:**
- Modify: `src/pyafk/core/rules.py`

**Step 1-5:** [Full implementation steps provided in plan]

---

## Task 10: Integration test - full chain approval flow

**Files:**
- Create: `tests/test_chain_approval_integration.py`

**Step 1-5:** [Full implementation steps provided in plan]

---

## Task 11: Documentation and final cleanup

**Files:**
- Create: `docs/plans/2025-01-04-chain-approval-engine-implementation.md`

**Step 1-5:** [Full implementation steps provided in plan]
