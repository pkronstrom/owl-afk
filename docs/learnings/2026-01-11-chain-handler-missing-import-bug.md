# Learnings: Chain Handler Missing Import Bug

**Date**: 2026-01-11
**Objective**: Debug stuck Telegram messages that weren't being resolved
**Outcome**: Success - found and fixed missing import in chain.py

## Summary

Telegram chain approval buttons were remaining visible after clicking "Approve Chain" because the `ChainApproveEntireHandler` was throwing a `NameError` due to a missing import. The request was internally resolved but the message edit failed, creating the appearance of stuck/unresolved messages.

## What We Tried

### Approach 1: Systematic Debugging via Logs
- **Description**: Followed the systematic-debugging skill - checked debug.log first before making any assumptions
- **Result**: Worked - found exact error in 2 minutes
- **Why**: The debug log clearly showed `error=name 'format_tool_summary' is not defined` with exact request IDs

## Final Solution

Added the missing `format_tool_summary` import to `src/pyafk/core/handlers/chain.py`:

```python
from pyafk.utils.formatting import (
    escape_html,
    format_project_id,
    format_tool_summary,  # <-- was missing
    truncate_command,
)
```

The function was being used at line 119 in `format_chain_approved_message()` but never imported.

## Key Learnings

- **Always check debug logs first** - The error was clearly visible in `~/.config/pyafk/debug.log` with full context
- **Requests can be internally resolved while appearing stuck** - The storage marked the request as approved, but the Telegram message edit failed afterward, creating a disconnect between state and UI
- **Missing imports can silently fail in try/except blocks** - The error was caught and logged but didn't propagate, making it non-obvious without logs
- **This bug predates recent changes** - User suspected recent timeout/reliability changes caused it, but the bug was in the original chain approval implementation

## Issues & Resolutions

| Issue | Root Cause | Resolution |
|-------|------------|------------|
| Chain approve buttons stayed visible after clicking | `format_tool_summary` not imported in chain.py | Added missing import |
| 8 pending requests accumulated | Each failed message edit left request appearing unresolved | Cleared after fix |

## User Steering

| User Said | Impact | Lesson for Next Time |
|-----------|--------|---------------------|
| "did you just introduce this with recent changes" | Prompted checking git history - confirmed bug predates recent commits | When debugging, verify when bug was introduced before assuming recent changes caused it |

## Gotchas & Warnings

- **The debug log location is `~/.config/pyafk/debug.log`** - not `~/.pyafk/` (the config uses XDG paths)
- **Handler errors are caught and logged but don't crash** - This is good for resilience but means bugs can hide if you don't check logs
- **Telegram message state can diverge from storage state** - If message edit fails after request resolution, UI shows stale state

## References

- `src/pyafk/core/handlers/chain.py:119` - where format_tool_summary is called
- `src/pyafk/utils/formatting.py:58` - where format_tool_summary is defined
- `~/.config/pyafk/debug.log` - debug log with full error traces
