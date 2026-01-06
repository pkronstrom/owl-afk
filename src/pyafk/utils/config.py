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

    def __init__(self, pyafk_dir: Optional[Path] = None):
        """Load config from directory."""
        self.pyafk_dir = pyafk_dir or get_pyafk_dir()
        self._config_file = self.pyafk_dir / "config.json"
        self._load()

    def _load(self):
        """Load config from file."""
        # Set defaults
        self.telegram_bot_token = None
        self.telegram_chat_id = None
        self.timeout_seconds = 3600
        self.timeout_action = "deny"
        self.debug = False

        if self._config_file.exists():
            try:
                data = json.loads(self._config_file.read_text())
                self.telegram_bot_token = data.get("telegram_bot_token")
                self.telegram_chat_id = data.get("telegram_chat_id")
                self.timeout_seconds = data.get("timeout_seconds", 3600)
                self.timeout_action = data.get("timeout_action", "deny")
                self.debug = data.get("debug", False)
            except (json.JSONDecodeError, IOError):
                pass

    def save(self):
        """Save config to file."""
        self.pyafk_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "telegram_bot_token": self.telegram_bot_token,
            "telegram_chat_id": self.telegram_chat_id,
            "timeout_seconds": self.timeout_seconds,
            "timeout_action": self.timeout_action,
            "debug": self.debug,
        }
        self._config_file.write_text(json.dumps(data, indent=2))

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
