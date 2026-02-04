"""Shared hook runner utility."""

import asyncio
import json
import sys
from typing import Any, Awaitable, Callable

from owl.fast_path import FastPathResult, check_fast_path


def run_hook(handler: Callable[[dict], Awaitable[dict[str, Any]]]) -> int:
    """Run an async hook handler with stdin/stdout JSON.

    Handles fast_path checking, JSON I/O, and async execution.

    Args:
        handler: Async function that takes hook input dict and returns result dict

    Returns:
        Exit code (0 for success)
    """
    from owl.utils.debug import debug_hook

    # Fast path check first
    result = check_fast_path()
    debug_hook("runner fast_path check", result=result.value)

    if result == FastPathResult.APPROVE:
        print(json.dumps({"decision": "approve"}))
        return 0
    elif result == FastPathResult.DENY:
        print(json.dumps({"decision": "deny"}))
        return 0
    elif result == FastPathResult.FALLBACK:
        # Return empty to fall back to Claude's CLI approval
        debug_hook("runner fallback - handler not called")
        print(json.dumps({}))
        return 0

    # Read stdin
    try:
        hook_input = json.load(sys.stdin)
    except json.JSONDecodeError:
        hook_input = {}

    # Run async handler
    response = asyncio.run(handler(hook_input))
    print(json.dumps(response))
    return 0
