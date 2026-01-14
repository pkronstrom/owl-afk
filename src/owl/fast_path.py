"""Fast path mode check - minimal overhead when disabled."""

import os
from enum import Enum
from pathlib import Path
from typing import Optional


class FastPathResult(Enum):
    """Result of fast path check."""
    APPROVE = "approve"
    DENY = "deny"
    CONTINUE = "continue"
    FALLBACK = "fallback"  # Return empty {} to use Claude's CLI


def check_fast_path(owl_dir: Optional[Path] = None) -> FastPathResult:
    """Check if we can fast-path without loading heavy modules.

    This function is designed to be as fast as possible:
    - No imports beyond stdlib
    - Single file read
    - No exception handling overhead for common case

    Args:
        owl_dir: Path to owl directory. If None, uses OWL_DIR env
                   or defaults to ~/.config/owl

    Returns:
        FastPathResult indicating whether to approve, deny, or continue
    """
    if owl_dir is None:
        env_dir = os.environ.get("OWL_DIR")
        if env_dir:
            owl_dir = Path(env_dir)
        else:
            owl_dir = Path.home() / ".config" / "owl"

    mode_file = owl_dir / "mode"

    try:
        mode = mode_file.read_text().strip()
    except FileNotFoundError:
        return FastPathResult.APPROVE
    except Exception:
        return FastPathResult.CONTINUE

    if mode == "off":
        return FastPathResult.FALLBACK  # Fall back to Claude's CLI approval
    elif mode == "on":
        return FastPathResult.CONTINUE
    else:
        return FastPathResult.CONTINUE


def fast_path_main():
    """Entry point for fast path check only.

    Exit codes:
        0 = approve (fast path)
        1 = deny (fast path)
        2 = continue to full check
    """
    import sys

    result = check_fast_path()

    if result == FastPathResult.APPROVE:
        print('{"decision": "approve"}')
        sys.exit(0)
    elif result == FastPathResult.DENY:
        print('{"decision": "deny"}')
        sys.exit(1)
    else:
        sys.exit(2)
