"""Tests for install/uninstall commands."""
import json
import pytest
from click.testing import CliRunner
from pathlib import Path
from pyafk.cli import main

@pytest.fixture
def cli_runner():
    return CliRunner()

def test_install_creates_hooks(cli_runner, mock_pyafk_dir, tmp_path, monkeypatch):
    """Install should create hook configuration."""
    monkeypatch.setenv("PYAFK_DIR", str(mock_pyafk_dir))
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    result = cli_runner.invoke(main, ["install"], input="y\n")
    assert result.exit_code == 0
    settings_file = claude_dir / "settings.json"
    assert settings_file.exists()
    settings = json.loads(settings_file.read_text())
    assert "hooks" in settings

def test_uninstall_removes_hooks(cli_runner, mock_pyafk_dir, tmp_path, monkeypatch):
    """Uninstall should remove hook configuration."""
    monkeypatch.setenv("PYAFK_DIR", str(mock_pyafk_dir))
    monkeypatch.setenv("HOME", str(tmp_path))
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings_file = claude_dir / "settings.json"
    settings_file.write_text(json.dumps({
        "hooks": {"PreToolUse": [{"command": "pyafk hook PreToolUse"}]}
    }))
    result = cli_runner.invoke(main, ["uninstall"], input="k\n")
    assert result.exit_code == 0
    settings = json.loads(settings_file.read_text())
    assert "PreToolUse" not in settings.get("hooks", {})
