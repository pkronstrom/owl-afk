# Rules UI Redesign

## Overview

Improved interactive rules management with better UX for adding/deleting rules.

## Add Rule Wizard

```
? Select tool type:
  › Bash          Shell commands
    Edit          File edits
    Write         File creation
    Read          File reading
    Skill         Skill execution
    WebFetch      Web requests
    WebSearch     Web searches
    Task          Sub-agents
    mcp__*        MCP tools (match all)
    (custom)      Enter tool name

? Enter pattern for Bash:
  Wildcards: * matches anything, ? matches single char
  Examples: git *, npm run *, python scripts/*.py

  Pattern: git *

? Action:
  › Approve       Auto-approve matching calls
    Deny          Auto-deny matching calls

✓ Added: Bash(git *) -> approve
```

## Rules List & Delete View

Uses select loop pattern (like config) - selecting toggles delete status:

```
Auto-approve Rules
──────────────────────────────────────────────────
  ✓ Bash(git *)              approve
  ✓ Bash(npm run *)          approve
  ✗ Edit(*.py)               approve     ← strikethrough, red
  ✓ Bash(rm -rf *)           deny

? Select to toggle delete:
  › Bash(git *)              approve
    Bash(npm run *)          approve
    Edit(*.py)               approve     [DELETE]
    Bash(rm -rf *)           deny
    ─────────
    Add rule
    Apply changes (1 deletion)
    Cancel
```

## Sorting

Rules displayed sorted by:
1. Tool name (Bash, Edit, etc.)
2. Pattern within tool

## Tool Types

Full list for wizard:
- Bash, Edit, Write, Read
- Skill, Task
- WebFetch, WebSearch
- mcp__* (wildcard for all MCP tools)
- (custom) for other tools
