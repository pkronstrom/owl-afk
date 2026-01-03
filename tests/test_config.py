"""Tests for configuration module."""

import json
from pathlib import Path

import pytest

from pyafk.utils.config import Config


def test_config_default_values(mock_pyafk_dir):
    """Config should have sensible defaults."""
    config = Config(mock_pyafk_dir)

    assert config.timeout_seconds == 3600
    assert config.timeout_action == "deny"
    assert config.telegram_bot_token is None
    assert config.telegram_chat_id is None


def test_config_loads_from_file(mock_pyafk_dir):
    """Config should load values from config.json."""
    config_file = mock_pyafk_dir / "config.json"
    config_file.write_text(json.dumps({
        "telegram_bot_token": "test-token",
        "telegram_chat_id": "12345",
        "timeout_seconds": 1800,
    }))

    config = Config(mock_pyafk_dir)

    assert config.telegram_bot_token == "test-token"
    assert config.telegram_chat_id == "12345"
    assert config.timeout_seconds == 1800


def test_config_save(mock_pyafk_dir):
    """Config should save changes to file."""
    config = Config(mock_pyafk_dir)
    config.telegram_bot_token = "new-token"
    config.save()

    config_file = mock_pyafk_dir / "config.json"
    data = json.loads(config_file.read_text())
    assert data["telegram_bot_token"] == "new-token"


def test_config_get_pyafk_dir_from_env(temp_dir, monkeypatch):
    """Config should use PYAFK_DIR env var if set."""
    custom_dir = temp_dir / "custom"
    custom_dir.mkdir()
    monkeypatch.setenv("PYAFK_DIR", str(custom_dir))

    from pyafk.utils.config import get_pyafk_dir
    assert get_pyafk_dir() == custom_dir


def test_config_default_pyafk_dir(monkeypatch):
    """Config should default to ~/.pyafk."""
    monkeypatch.delenv("PYAFK_DIR", raising=False)

    from pyafk.utils.config import get_pyafk_dir
    assert get_pyafk_dir() == Path.home() / ".pyafk"
