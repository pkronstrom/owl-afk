# Telegram Command Timeout Fixes

## Problem

Some Telegram commands time out intermittently, causing poor UX.

## Root Causes (via Codex analysis)

### 1. HTTP Timeout Exceeds Telegram Callback Window
- **Location**: `src/pyafk/notifiers/telegram.py:113`
- **Issue**: HTTP client timeout is 30s, but Telegram only allows 10s for callback acknowledgement
- **Impact**: Slow network = callback appears "timed out" to user

### 2. Serial Update Processing
- **Location**: `src/pyafk/core/poller.py:242`
- **Issue**: Updates processed one at a time; heavy handlers stall entire poller
- **Impact**: Delayed response to subsequent commands

### 3. No Poller When Daemon Disabled
- **Locations**: `src/pyafk/core/manager.py:289`, `src/pyafk/daemon.py:176`
- **Issue**: `/msg` and `/afk` sit unprocessed when daemon off and no approval pending
- **Impact**: Commands never handled

### 4. Poller Lock Contention
- **Locations**: `src/pyafk/core/poller.py:34`, `src/pyafk/daemon.py:201`
- **Issue**: Exclusive lock - another process holding it stops all polling
- **Impact**: Complete polling halt

### 5. Stale Updates Skipped
- **Location**: `src/pyafk/core/poller.py:227`
- **Issue**: First poll after missing offset skips all queued updates
- **Impact**: Recent commands appear lost

### 6. Chain Handler Latency
- **Locations**: `src/pyafk/core/handlers/chain.py:98`, `src/pyafk/core/handlers/chain.py:752`
- **Issue**: N x rule checks + DB writes per command in chains
- **Impact**: Large chains cause significant delays

## Proposed Fixes

### P0 - Critical
1. **Reduce `answer_callback` timeout** from 30s to 8s (under Telegram's 10s limit)
   - File: `src/pyafk/notifiers/telegram.py`
   - Change: Use shorter timeout specifically for callback acknowledgement

### P1 - High Priority
2. **Add retry/backoff for Telegram API errors**
   - File: `src/pyafk/notifiers/telegram.py:125`
   - Change: Wrap `_api_request` with exponential backoff (max 2-3 retries)

3. **Handle `/afk` and `/msg` without daemon**
   - Files: `src/pyafk/core/manager.py`, `src/pyafk/hooks/`
   - Change: Lightweight polling for text commands even when daemon disabled

### P2 - Medium Priority
4. **Concurrent handler dispatch**
   - File: `src/pyafk/core/poller.py`
   - Change: Use `asyncio.gather()` for independent callbacks instead of serial loop

5. **Smarter offset initialization**
   - File: `src/pyafk/core/poller.py:227`
   - Change: Only skip truly stale updates (>60s old), preserve recent ones

### P3 - Low Priority
6. **Optimize chain handlers**
   - File: `src/pyafk/core/handlers/chain.py`
   - Change: Batch DB operations, cache rule lookups
