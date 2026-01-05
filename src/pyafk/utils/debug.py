"""Debug logging utility."""

import sys
from datetime import datetime
from pathlib import Path

from pyafk.utils.config import Config, get_pyafk_dir

_config = None


def _get_config() -> Config:
    """Get cached config instance."""
    global _config
    if _config is None:
        _config = Config(get_pyafk_dir())
    return _config


def reload_config():
    """Reload config (call after debug mode changes)."""
    global _config
    _config = None


def _log_to_file(line: str):
    """Append line to debug log file."""
    try:
        log_path = get_pyafk_dir() / "debug.log"
        with open(log_path, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def debug(category: str, message: str, **kwargs):
    """Log debug message if debug mode is enabled.

    Args:
        category: Category like 'chain', 'rule', 'callback', 'parse'
        message: Debug message
        **kwargs: Additional key=value pairs to log
    """
    config = _get_config()
    if not config.debug:
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    extras = " ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
    line = f"[pyafk:{category}] {timestamp} {message}"
    if extras:
        line += f" | {extras}"

    # Log to file (always) and stderr
    _log_to_file(line)
    print(line, file=sys.stderr)


def debug_chain(message: str, **kwargs):
    """Log chain-related debug message."""
    debug("chain", message, **kwargs)


def debug_rule(message: str, **kwargs):
    """Log rule-related debug message."""
    debug("rule", message, **kwargs)


def debug_callback(message: str, **kwargs):
    """Log callback-related debug message."""
    debug("callback", message, **kwargs)


def debug_parse(message: str, **kwargs):
    """Log parse-related debug message."""
    debug("parse", message, **kwargs)
