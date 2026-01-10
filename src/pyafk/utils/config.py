"""Configuration management."""

import json
import os
from pathlib import Path
from typing import Optional


def get_pyafk_dir() -> Path:
    """Get the pyafk data directory (XDG-compliant)."""
    if env_dir := os.environ.get("PYAFK_DIR"):
        return Path(env_dir)
    return Path.home() / ".config" / "pyafk"


class Config:
    """Application configuration."""

    # Toggleable settings with descriptions (attr_name -> description)
    # These are auto-discovered by the interactive menu
    TOGGLES: dict[str, str] = {
        "debug": "Log to ~/.config/pyafk/debug.log",
        "daemon_enabled": "Background polling (vs inline)",
        "disable_stop_hook": "Skip stop hook notifications",
        "disable_subagent_hook": "Skip subagent finished notifications",
    }

    def __init__(self, pyafk_dir: Optional[Path] = None):
        """Load config from directory."""
        self.pyafk_dir = pyafk_dir or get_pyafk_dir()
        self._config_file = self.pyafk_dir / "config.json"
        self._load()

    def _load(self):
        """Load config from file."""
        from pyafk.utils.constants import (
            DEFAULT_REQUEST_TIMEOUT,
            DEFAULT_TIMEOUT_ACTION,
        )

        # Set defaults
        self.telegram_bot_token = None
        self.telegram_chat_id = None
        self.timeout_seconds = DEFAULT_REQUEST_TIMEOUT
        self.timeout_action = DEFAULT_TIMEOUT_ACTION
        self.debug = False
        # WARNING: experimental - daemon_enabled=False means hooks poll inline
        self.daemon_enabled = False
        self.subagent_auto_dismiss_seconds = (
            60  # Auto-dismiss subagent messages after 1 min
        )
        # Hook disable flags
        self.disable_subagent_hook = False
        self.disable_stop_hook = False
        # Env var overrides (like captain-hook)
        self.env: dict[str, str] = {}

        if self._config_file.exists():
            try:
                data = json.loads(self._config_file.read_text())
                self.telegram_bot_token = data.get("telegram_bot_token")
                self.telegram_chat_id = data.get("telegram_chat_id")
                self.timeout_seconds = data.get(
                    "timeout_seconds", DEFAULT_REQUEST_TIMEOUT
                )
                self.timeout_action = data.get("timeout_action", DEFAULT_TIMEOUT_ACTION)
                self.debug = data.get("debug", False)
                self.daemon_enabled = data.get("daemon_enabled", False)
                self.subagent_auto_dismiss_seconds = data.get(
                    "subagent_auto_dismiss_seconds", 60
                )
                self.disable_subagent_hook = data.get("disable_subagent_hook", False)
                self.disable_stop_hook = data.get("disable_stop_hook", False)
                self.env = data.get("env", {})
            except (json.JSONDecodeError, IOError):
                pass

        # Apply env section from config, then shell env vars override
        self._apply_env_overrides()

    def _apply_env_overrides(self):
        """Apply env overrides: first from config.env, then from shell PYAFK_* vars."""
        prefix = "PYAFK_"

        def apply_env_dict(env_dict: dict[str, str]):
            for key, value in env_dict.items():
                # Support both PYAFK_FOO and FOO formats in config.env
                if key.startswith(prefix):
                    attr_name = key[len(prefix) :].lower()
                else:
                    attr_name = key.lower()
                if not hasattr(self, attr_name):
                    continue
                # Convert value based on current attribute type
                current = getattr(self, attr_name)
                if isinstance(current, bool):
                    setattr(self, attr_name, value.lower() in ("true", "1", "yes"))
                elif isinstance(current, int):
                    try:
                        setattr(self, attr_name, int(value))
                    except ValueError:
                        pass
                else:
                    setattr(self, attr_name, value)

        # First apply config.env (persisted overrides)
        apply_env_dict(self.env)

        # Then apply shell env vars (highest priority)
        shell_env = {k: v for k, v in os.environ.items() if k.startswith(prefix)}
        apply_env_dict(shell_env)

    def save(self):
        """Save config to file."""
        self.pyafk_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "telegram_bot_token": self.telegram_bot_token,
            "telegram_chat_id": self.telegram_chat_id,
            "timeout_seconds": self.timeout_seconds,
            "timeout_action": self.timeout_action,
            "debug": self.debug,
            "daemon_enabled": self.daemon_enabled,
            "subagent_auto_dismiss_seconds": self.subagent_auto_dismiss_seconds,
            "env": self.env,
        }
        self._config_file.write_text(json.dumps(data, indent=2))

    def set_env(self, key: str, value: str):
        """Set an env var override in config."""
        self.env[key] = value
        self.save()
        # Re-apply to update attributes
        self._apply_env_overrides()

    def unset_env(self, key: str) -> bool:
        """Remove an env var override. Returns True if key existed."""
        if key in self.env:
            del self.env[key]
            self.save()
            return True
        return False

    def get_env(self, key: str) -> Optional[str]:
        """Get an env var override value."""
        return self.env.get(key)

    def list_env(self) -> dict[str, str]:
        """List all env var overrides."""
        return self.env.copy()

    def get_toggles(self) -> list[tuple[str, str, bool]]:
        """Get all toggleable settings with current values.

        Returns list of (attr_name, description, is_enabled).
        """
        result = []
        for attr, desc in self.TOGGLES.items():
            value = getattr(self, attr, False)
            result.append((attr, desc, bool(value)))
        return result

    def set_toggle(self, attr: str, enabled: bool):
        """Set a toggle value and persist it."""
        if attr not in self.TOGGLES:
            return
        setattr(self, attr, enabled)
        # For env-style toggles, store in env section
        env_key = attr.upper()
        if enabled:
            self.env[env_key] = "true"
        elif env_key in self.env:
            del self.env[env_key]
        self.save()

    def set_debug(self, enabled: bool):
        """Enable or disable debug mode."""
        self.debug = enabled
        self.save()

    def get_debug(self) -> bool:
        """Get debug mode status."""
        return self.debug

    @property
    def db_path(self) -> Path:
        """Path to SQLite database."""
        return self.pyafk_dir / "pyafk.db"

    @property
    def mode_file(self) -> Path:
        """Path to mode file."""
        return self.pyafk_dir / "mode"

    def get_mode(self) -> str:
        """Get current mode (on/off)."""
        try:
            return self.mode_file.read_text().strip()
        except FileNotFoundError:
            return "off"

    def set_mode(self, mode: str):
        """Set current mode."""
        self.pyafk_dir.mkdir(parents=True, exist_ok=True)
        self.mode_file.write_text(mode)
