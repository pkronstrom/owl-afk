"""Tests for configuration module."""

import json
from pathlib import Path


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
    config_file.write_text(
        json.dumps(
            {
                "telegram_bot_token": "test-token",
                "telegram_chat_id": "12345",
                "timeout_seconds": 1800,
            }
        )
    )

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
    """Config should default to ~/.config/pyafk (XDG-compliant)."""
    monkeypatch.delenv("PYAFK_DIR", raising=False)

    from pyafk.utils.config import get_pyafk_dir

    assert get_pyafk_dir() == Path.home() / ".config" / "pyafk"


def test_auto_approve_notify_default(mock_pyafk_dir):
    """auto_approve_notify should default to False."""
    config = Config(mock_pyafk_dir)
    assert config.auto_approve_notify is False


def test_auto_approve_notify_load_save(mock_pyafk_dir):
    """auto_approve_notify should persist through save/load."""
    config = Config(mock_pyafk_dir)
    config.auto_approve_notify = True
    config.save()

    config2 = Config(mock_pyafk_dir)
    assert config2.auto_approve_notify is True


def test_auto_approve_notify_env_override(mock_pyafk_dir, monkeypatch):
    """auto_approve_notify should be overridable via env var."""
    monkeypatch.setenv("PYAFK_AUTO_APPROVE_NOTIFY", "1")

    config = Config(mock_pyafk_dir)
    assert config.auto_approve_notify is True


def test_auto_approve_notify_in_toggles():
    """auto_approve_notify should be in TOGGLES dict."""
    assert "auto_approve_notify" in Config.TOGGLES
    assert Config.TOGGLES["auto_approve_notify"] == "Notify on auto-approvals"
