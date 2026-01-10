# Learnings: Standalone Polling and Request Deduplication

**Date**: 2026-01-10
**Objective**: Fix multiple issues with pyafk's standalone mode (no daemon) including pattern matching for worktrees, polling hangs, and duplicate requests
**Outcome**: Success - All issues resolved with commits `d686c52`, `62a28ec`, and `585ceae`

## Summary

When running pyafk in standalone mode (multiple hook processes polling Telegram independently), several race conditions and coordination issues emerged. We solved these through: (1) wildcard-based pattern matching for portability, (2) leader election for cooperative polling, (3) request deduplication at creation time, and (4) idempotent callback handling.

## What We Tried

### Approach 1: Simple Cooperative Lock Per Poll
- **Description**: Each hook acquires lock, polls once, releases immediately
- **Result**: Partially worked
- **Why**: Reduced 409 conflicts but hooks that couldn't get the lock would just check DB. If no one was polling when user clicked approve, callbacks weren't processed.

### Approach 2: Leader Election with Grace Period
- **Description**: First hook becomes "polling leader", keeps polling continuously. After own request resolves, continues polling for 30s grace period to help other requests.
- **Result**: Worked
- **Why**: Single process handles all Telegram callbacks, updates DB for everyone. Other hooks just check DB. Grace period ensures callbacks are processed even if leader's request resolves first.

### Approach 3: Retry Becoming Leader
- **Description**: If a hook's `poll_as_leader` returns False (couldn't get lock), retry on next loop iteration
- **Result**: Worked
- **Why**: When leader finishes/exits, another waiting hook can become the new leader. No gaps in polling coverage.

## Final Solution

**Multi-layer approach:**

1. **Pattern Generator** (`pattern_generator.py`): Changed from absolute paths (`Write(/Users/.../dodo/*)`) to wildcard prefixes (`Write(*/dodo/*)`). Patterns now work across git worktrees and different machines.

2. **Leader Polling** (`poller.py`, `manager.py`):
   - `poll_as_leader()` method that holds lock and polls continuously
   - Leader processes ALL callbacks, not just its own request
   - 30 second grace period after own request resolves
   - Hooks retry becoming leader if their task finishes

3. **Request Deduplication** (`storage.py`, `manager.py`):
   - `find_duplicate_pending_request()` checks for existing pending request with same tool_name, tool_input, session_id
   - If duplicate found, wait for existing request instead of creating new one
   - Prevents duplicate Telegram messages when multiple hooks (captain-hook + direct pyafk) call pyafk

4. **Idempotent Callbacks** (`approval.py`, `chain.py`):
   - Check `request.status != "pending"` before processing
   - Skip callback if request already resolved
   - Prevents duplicate processing when multiple pollers receive same callback

## Key Learnings

- **Telegram's `getUpdates` only allows one concurrent call per bot** - Multiple processes polling simultaneously get 409 Conflict errors and may "lose" updates to wrong process

- **Deduplication must happen at multiple layers** - Request creation (prevents duplicate Telegram messages) AND callback processing (prevents duplicate state changes)

- **Leader election is simpler than distributed coordination** - Having one process be responsible for all polling is easier than trying to partition work

- **Grace periods prevent gaps** - When leader's request resolves, other requests might still be pending. Grace period of 30s ensures they're not orphaned

- **Pattern portability matters** - Absolute paths break across worktrees, machines, and over time. Wildcards (`*/project/*`) are more robust

- **Idempotent handlers are essential** - When callbacks can be delivered multiple times (different pollers), handlers must check state before acting

## Issues & Resolutions

| Issue | Root Cause | Resolution |
|-------|------------|------------|
| "Any in /dodo/" pattern didn't match worktree paths | Pattern used absolute path `/Users/.../dodo/*` but worktree was at `/Users/.../dodo-formatters/` | Changed to `*/dodo/*` wildcard prefix |
| Last command in chain hung in standalone mode | Hook finished polling, no one picked up callback | Leader election with retry - hooks retry becoming leader when their task finishes |
| Duplicate Telegram messages | Two hooks (captain-hook + direct pyafk) both calling pyafk | Request deduplication - check for existing pending request before creating |
| Same callback processed multiple times | Multiple pollers received same Telegram update | Idempotent handlers - skip if `request.status != "pending"` |
| 409 Conflict errors from Telegram | Multiple processes calling `getUpdates` simultaneously | Leader election ensures only one process polls at a time |

## Gotchas & Warnings

- **Lock files persist** - If a process crashes while holding `poll.lock`, the lock file remains. The `PollLock` class handles this by opening file fresh each time, but stale lock files can cause confusion during debugging

- **captain-hook can chain to pyafk** - Users may have pyafk in both captain-hook hooks AND direct Claude settings. Must handle this gracefully via deduplication

- **`tool_input IS ?` in SQLite** - Using `IS` instead of `=` for NULL-safe comparison when deduplicating requests

- **Callback query expiration** - Telegram callback queries expire after ~30 seconds. If processing takes too long, `answerCallbackQuery` fails with "query is too old"

## References

- `src/pyafk/core/poller.py` - Leader election and polling logic
- `src/pyafk/core/manager.py` - Request creation with deduplication
- `src/pyafk/core/storage.py` - `find_duplicate_pending_request()` method
- `src/pyafk/core/handlers/approval.py` - Idempotent approve handler
- `src/pyafk/core/handlers/chain.py` - Idempotent chain handlers
- `src/pyafk/utils/pattern_generator.py` - Wildcard pattern generation
