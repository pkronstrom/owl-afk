"""Configuration management."""

import json
import os
from pathlib import Path
from typing import Optional


def get_owl_dir() -> Path:
    """Get the owl data directory (XDG-compliant)."""
    if env_dir := os.environ.get("OWL_DIR"):
        return Path(env_dir)
    return Path.home() / ".config" / "owl"


class Config:
    """Application configuration."""

    # Toggleable settings with descriptions (attr_name -> description)
    # These are auto-discovered by the interactive menu
    TOGGLES: dict[str, str] = {
        "debug": "Log to ~/.config/owl/debug.log",
        "stop_hook": "Notify when Claude session ends",
        "subagent_hook": "Notify when subagent finishes",
        "notification_hook": "Forward notifications to TG",
        "auto_approve_notify": "Notify on auto-approvals",
        "tool_results": "Show tool results in Telegram messages",
    }

    def __init__(self, owl_dir: Optional[Path] = None):
        """Load config from directory."""
        self.owl_dir = owl_dir or get_owl_dir()
        self._config_file = self.owl_dir / "config.json"
        self._load()

    def _load(self):
        """Load config from file."""
        from owl.utils.constants import (
            DEFAULT_REQUEST_TIMEOUT,
            DEFAULT_TIMEOUT_ACTION,
        )

        # Set defaults
        self.telegram_bot_token = None
        self.telegram_chat_id = None
        self.timeout_seconds = DEFAULT_REQUEST_TIMEOUT
        self.timeout_action = DEFAULT_TIMEOUT_ACTION
        self.debug = False
        self.subagent_auto_dismiss_seconds = (
            60  # Auto-dismiss subagent messages after 1 min
        )
        # Hook enable flags (default enabled)
        self.stop_hook = True
        self.subagent_hook = True
        self.notification_hook = False  # New feature, default off
        self.auto_approve_notify = False  # Notify on auto-approvals
        self.tool_results = False  # Show tool results in Telegram messages
        # Polling grace period - how long to keep polling after request resolves (seconds)
        self.polling_grace_period = 900  # 15 minutes default
        # Env var overrides (like hawk-hooks)
        self.env: dict[str, str] = {}
        # Editor for text input
        self.editor = os.environ.get("EDITOR", "vim")
        # Project filter - empty list means global (all projects)
        self.enabled_projects: list[str] = []

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
                self.subagent_auto_dismiss_seconds = data.get(
                    "subagent_auto_dismiss_seconds", 60
                )
                # New positive names (with backwards compat for old disable_* names)
                if "stop_hook" in data:
                    self.stop_hook = data.get("stop_hook", True)
                else:
                    # Old config: invert disable_stop_hook
                    self.stop_hook = not data.get("disable_stop_hook", False)
                if "subagent_hook" in data:
                    self.subagent_hook = data.get("subagent_hook", True)
                else:
                    # Old config: invert disable_subagent_hook
                    self.subagent_hook = not data.get("disable_subagent_hook", False)
                self.notification_hook = data.get("notification_hook", False)
                self.auto_approve_notify = data.get("auto_approve_notify", False)
                self.tool_results = data.get("tool_results", False)
                self.polling_grace_period = data.get("polling_grace_period", 900)
                self.env = data.get("env", {})
                self.editor = data.get("editor", os.environ.get("EDITOR", "vim"))
                self.enabled_projects = data.get("enabled_projects", [])
            except (json.JSONDecodeError, IOError):
                pass

        # Apply env section from config, then shell env vars override
        self._apply_env_overrides()

    def _apply_env_overrides(self):
        """Apply env overrides: first from config.env, then from shell OWL_* vars."""
        prefix = "OWL_"

        def apply_env_dict(env_dict: dict[str, str]):
            for key, value in env_dict.items():
                # Support both OWL_FOO and FOO formats in config.env
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
        """Save config to file.

        Config contains credentials so we set restrictive permissions (0600).
        """
        self.owl_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "telegram_bot_token": self.telegram_bot_token,
            "telegram_chat_id": self.telegram_chat_id,
            "timeout_seconds": self.timeout_seconds,
            "timeout_action": self.timeout_action,
            "debug": self.debug,
            "subagent_auto_dismiss_seconds": self.subagent_auto_dismiss_seconds,
            "stop_hook": self.stop_hook,
            "subagent_hook": self.subagent_hook,
            "notification_hook": self.notification_hook,
            "auto_approve_notify": self.auto_approve_notify,
            "tool_results": self.tool_results,
            "polling_grace_period": self.polling_grace_period,
            "env": self.env,
            "editor": self.editor,
            "enabled_projects": self.enabled_projects,
        }
        self._config_file.write_text(json.dumps(data, indent=2))
        # Restrict permissions: owner read/write only (contains credentials)
        self._config_file.chmod(0o600)

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
        return self.owl_dir / "owl.db"

    @property
    def mode_file(self) -> Path:
        """Path to mode file."""
        return self.owl_dir / "mode"

    def get_mode(self) -> str:
        """Get current mode (on/off)."""
        try:
            return self.mode_file.read_text().strip()
        except FileNotFoundError:
            return "off"

    def set_mode(self, mode: str):
        """Set current mode."""
        self.owl_dir.mkdir(parents=True, exist_ok=True)
        self.mode_file.write_text(mode)

    def is_enabled_for_project(self, project_path: Optional[str]) -> bool:
        """Check if owl is enabled for a given project path.

        Returns True if:
        - Mode is on AND no project filter (global mode)
        - Mode is on AND project matches one of enabled_projects
        """
        if self.get_mode() != "on":
            return False
        if not self.enabled_projects:
            return True  # Global mode - all projects enabled

        if not project_path:
            return False

        for pattern in self.enabled_projects:
            if pattern.startswith("/"):
                # Full path - check if session starts with it
                if project_path.startswith(pattern):
                    return True
            else:
                # Name only - check if path contains /name/ or ends with /name
                if f"/{pattern}/" in project_path or project_path.endswith(
                    f"/{pattern}"
                ):
                    return True
        return False

    def add_enabled_project(self, project: str) -> None:
        """Add a project to the enabled list."""
        if project not in self.enabled_projects:
            self.enabled_projects.append(project)
            self.save()

    def remove_enabled_project(self, project: str) -> bool:
        """Remove a project from the enabled list. Returns True if removed."""
        if project in self.enabled_projects:
            self.enabled_projects.remove(project)
            self.save()
            return True
        return False

    def clear_enabled_projects(self) -> None:
        """Clear all enabled projects (switch to global mode)."""
        self.enabled_projects = []
        self.save()
