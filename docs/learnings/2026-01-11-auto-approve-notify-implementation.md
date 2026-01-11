# Learnings: Auto-Approve Notification Feature Implementation

**Date**: 2026-01-11
**Objective**: Implement a config toggle that sends Telegram notifications when auto-approve rules trigger
**Outcome**: Success - feature implemented with cleaner design than original plan

## Summary

User requested critical review of an existing plan before implementation. The review identified code smells and DRY violations in the original plan. We revised the approach to use polymorphism instead of `isinstance` checks and reuse existing infrastructure rather than adding duplicate methods. Implementation completed with all 192 tests passing.

## What We Tried

### Approach 1: Original Plan (Rejected Before Implementation)
- **Description**: Plan proposed adding two new methods to TelegramNotifier (`send_auto_approval_notice()` and `send_chain_auto_approval_notice()`), using `isinstance(self.notifier, TelegramNotifier)` checks in the manager, and adding `check_with_pattern()` to rules engine.
- **Result**: Rejected during review
- **Why**: Violated DRY (duplicate methods vs reusing `send_message()`), broke abstraction (isinstance checks in manager), and over-engineered (separate chain/non-chain methods).

### Approach 2: Clean Polymorphic Design (Implemented)
- **Description**: Add `send_info_message()` to base `Notifier` class with no-op default, override in TelegramNotifier to call existing `send_message()`, use single formatting helper for both chains and single commands.
- **Result**: Success
- **Why**: Follows OOP principles (polymorphism over type checking), DRY (reuses existing infrastructure), minimal footprint.

## Final Solution

1. **Config toggle**: Added `auto_approve_notify` to `Config.TOGGLES` dict
2. **Base notifier**: Added `send_info_message()` with no-op default implementation
3. **TelegramNotifier**: 3-line override calling existing `send_message()`
4. **Formatting**: Single `format_auto_approval_message()` function handles both chains and single commands
5. **Manager integration**: Simple conditional after rule match - no type checks

## Key Learnings

- **Review plans critically before implementing** - the original plan had several issues that would have required refactoring later
- **Prefer polymorphism over isinstance checks** - adding a no-op method to base class is cleaner than type-checking in callers
- **Private vs public attributes matter** - manager uses `self._config` not `self.config`, caused test failures initially
- **HTML escaping chains** - `format_tool_summary()` already escapes HTML, so the formatting function needed to avoid double-escaping for single commands while still escaping chain summaries

## Issues & Resolutions

| Issue | Root Cause | Resolution |
|-------|------------|------------|
| `AttributeError: 'ApprovalManager' object has no attribute 'config'` | Manager stores config as `self._config` (private), not `self.config` | Changed integration code to use `self._config` |
| Test assertion failed for HTML escaping | `format_tool_summary()` already escapes HTML, was double-escaping | Added conditional: only escape chain summaries, single commands are pre-escaped |
| `command not found: python` | Virtual environment not activated in test command | Used `source .venv/bin/activate && python -m pytest` |
| Linter removed unused import | Added `from unittest.mock import AsyncMock` at file top but linter removed it | Moved import inside test functions where it's used |
| Toggle not appearing in menu | `interactive.py` has hardcoded `GENERAL_TOGGLES` list separate from `Config.TOGGLES` | Must add to both `Config.TOGGLES` AND the appropriate menu list |

## User Steering

Key moments where user direction shaped the outcome:

| User Said | Impact | Lesson for Next Time |
|-----------|--------|---------------------|
| "re-review it, so that we will implement the feature the right way; DRY, does not introduce spaghetti" | Triggered critical plan review instead of blind implementation | Always critically review existing plans before implementing, especially for code quality |
| "I prefer minimal overhead, DRY, no code smell, good quality code" | Confirmed rejection of original plan's approach, guided cleaner design | When user emphasizes code quality, probe for architectural concerns before implementing |
| "then implement" (after plan revision) | Single combined request for plan + implementation | Can batch plan revision and implementation when user explicitly requests both |

## Gotchas & Warnings

- **Check attribute naming conventions in target classes** - private (`_config`) vs public (`config`) matters
- **Watch for double-escaping when composing formatted strings** - helper functions may already escape
- **Test commands need virtual environment** - always prefix with `source .venv/bin/activate &&`
- **Linters may remove imports** - if import appears unused (e.g., only used inside a function), move it to where it's used

## Technical Notes

### HTML Escaping Strategy
- `format_tool_summary()` returns already-escaped HTML
- `format_auto_approval_message()` must not double-escape for single commands
- Chain summaries are built from raw command strings, so they need escaping
- Solution: conditional escaping based on `is_chain` flag

### Notifier Abstraction
- Base `Notifier` class defines interface
- `TelegramNotifier` implements it
- Adding `send_info_message()` to base with no-op default allows manager to call without type checks
- `ConsoleNotifier` automatically gets no-op behavior (appropriate - CLI doesn't need info messages)

## References

- `src/pyafk/core/manager.py:217-235` - Integration point
- `src/pyafk/notifiers/base.py:80-86` - Base class extension
- `src/pyafk/utils/formatting.py:29-74` - Formatting helper
- `docs/plans/2026-01-11-auto-approve-notify.md` - Revised plan document
