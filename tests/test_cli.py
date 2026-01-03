"""Tests for CLI commands."""
import pytest
from click.testing import CliRunner
from pyafk.cli import main


@pytest.fixture
def cli_runner():
    return CliRunner()


def test_cli_status_off(cli_runner, mock_pyafk_dir, monkeypatch):
    """Status command shows off mode."""
    monkeypatch.setenv("PYAFK_DIR", str(mock_pyafk_dir))
    (mock_pyafk_dir / "mode").write_text("off")
    result = cli_runner.invoke(main, ["status"])
    assert result.exit_code == 0
    assert "off" in result.output.lower()


def test_cli_on_command(cli_runner, mock_pyafk_dir, monkeypatch):
    """On command enables pyafk."""
    monkeypatch.setenv("PYAFK_DIR", str(mock_pyafk_dir))
    result = cli_runner.invoke(main, ["on"])
    assert result.exit_code == 0
    assert (mock_pyafk_dir / "mode").read_text() == "on"


def test_cli_off_command(cli_runner, mock_pyafk_dir, monkeypatch):
    """Off command disables pyafk."""
    monkeypatch.setenv("PYAFK_DIR", str(mock_pyafk_dir))
    (mock_pyafk_dir / "mode").write_text("on")
    result = cli_runner.invoke(main, ["off"])
    assert result.exit_code == 0
    assert (mock_pyafk_dir / "mode").read_text() == "off"


def test_cli_rules_list_empty(cli_runner, mock_pyafk_dir, monkeypatch):
    """Rules list shows empty when no rules."""
    monkeypatch.setenv("PYAFK_DIR", str(mock_pyafk_dir))
    result = cli_runner.invoke(main, ["rules", "list"])
    assert result.exit_code == 0
    assert "no rules" in result.output.lower() or result.output.strip() == ""


def test_cli_rules_add(cli_runner, mock_pyafk_dir, monkeypatch):
    """Rules add creates a new rule."""
    monkeypatch.setenv("PYAFK_DIR", str(mock_pyafk_dir))
    result = cli_runner.invoke(main, ["rules", "add", "Bash(git *)", "--approve"])
    assert result.exit_code == 0
    result = cli_runner.invoke(main, ["rules", "list"])
    assert "Bash(git *)" in result.output
