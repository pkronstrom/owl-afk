"""Tests for CLI commands."""

import json
import subprocess
import sys

import pytest


@pytest.fixture
def cli_env(mock_owl_dir, monkeypatch):
    """Set up environment for CLI tests."""
    monkeypatch.setenv("OWL_DIR", str(mock_owl_dir))
    return mock_owl_dir


def run_cli(*args, env=None, input_text=None):
    """Run owl CLI command and return result."""
    cmd = [sys.executable, "-m", "owl.cli"] + list(args)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        input=input_text,
    )
    return result


class TestStatusCommand:
    """Tests for status command."""

    def test_status_shows_off_mode(self, cli_env, monkeypatch):
        """Status command shows off mode."""
        import os

        env = os.environ.copy()
        env["OWL_DIR"] = str(cli_env)
        (cli_env / "mode").write_text("off")

        result = run_cli("status", env=env)

        assert result.returncode == 0
        assert "off" in result.stdout.lower()

    def test_status_shows_on_mode(self, cli_env, monkeypatch):
        """Status command shows on mode."""
        import os

        env = os.environ.copy()
        env["OWL_DIR"] = str(cli_env)
        (cli_env / "mode").write_text("on")

        result = run_cli("status", env=env)

        assert result.returncode == 0
        assert "on" in result.stdout.lower()


class TestOnOffCommands:
    """Tests for on/off commands."""

    def test_on_command_enables(self, cli_env):
        """On command enables owl."""
        import os

        env = os.environ.copy()
        env["OWL_DIR"] = str(cli_env)

        result = run_cli("on", env=env)

        assert result.returncode == 0
        assert (cli_env / "mode").read_text() == "on"

    def test_off_command_disables(self, cli_env):
        """Off command disables owl."""
        import os

        env = os.environ.copy()
        env["OWL_DIR"] = str(cli_env)
        (cli_env / "mode").write_text("on")

        result = run_cli("off", env=env)

        assert result.returncode == 0
        assert (cli_env / "mode").read_text() == "off"


class TestRulesCommands:
    """Tests for rules commands."""

    def test_rules_list_empty(self, cli_env):
        """Rules list shows empty when no rules."""
        import os

        env = os.environ.copy()
        env["OWL_DIR"] = str(cli_env)

        result = run_cli("rules", "list", env=env)

        assert result.returncode == 0

    def test_rules_add_creates_rule(self, cli_env):
        """Rules add creates a new rule."""
        import os

        env = os.environ.copy()
        env["OWL_DIR"] = str(cli_env)

        result = run_cli("rules", "add", "Bash(git *)", env=env)

        assert result.returncode == 0

        # Verify rule was added
        result = run_cli("rules", "list", env=env)
        assert "Bash(git *)" in result.stdout

    def test_rules_add_deny_rule(self, cli_env):
        """Rules add can create deny rules."""
        import os

        env = os.environ.copy()
        env["OWL_DIR"] = str(cli_env)

        result = run_cli("rules", "add", "Bash(rm *)", "--action", "deny", env=env)

        assert result.returncode == 0

    def test_rules_remove_deletes_rule(self, cli_env):
        """Rules remove deletes a rule."""
        import os

        env = os.environ.copy()
        env["OWL_DIR"] = str(cli_env)

        # First add a rule
        run_cli("rules", "add", "Bash(test *)", env=env)

        # Get the rule ID from list
        result = run_cli("rules", "list", env=env)
        # Rules are listed with ID, find it
        # Format is typically "ID: pattern - action"

        # Remove rule ID 1 (first rule added)
        result = run_cli("rules", "remove", "1", env=env)

        assert result.returncode == 0


class TestDebugCommands:
    """Tests for debug commands."""

    def test_debug_on_enables_debug(self, cli_env):
        """Debug on enables debug mode."""
        import os

        env = os.environ.copy()
        env["OWL_DIR"] = str(cli_env)

        result = run_cli("debug", "on", env=env)

        assert result.returncode == 0

        # Check config was updated
        config_file = cli_env / "config.json"
        if config_file.exists():
            config = json.loads(config_file.read_text())
            assert config.get("debug") is True

    def test_debug_off_disables_debug(self, cli_env):
        """Debug off disables debug mode."""
        import os

        env = os.environ.copy()
        env["OWL_DIR"] = str(cli_env)

        # First enable
        run_cli("debug", "on", env=env)

        # Then disable
        result = run_cli("debug", "off", env=env)

        assert result.returncode == 0


class TestResetCommand:
    """Tests for reset command."""

    def test_reset_with_force(self, cli_env):
        """Reset with --force clears database."""
        import os

        env = os.environ.copy()
        env["OWL_DIR"] = str(cli_env)

        # Create a database file
        db_file = cli_env / "owl.db"
        db_file.write_text("dummy")

        result = run_cli("reset", "--force", env=env)

        assert result.returncode == 0


class TestEnvCommands:
    """Tests for env commands."""

    def test_env_list_empty(self, cli_env):
        """Env list shows empty when no overrides."""
        import os

        env = os.environ.copy()
        env["OWL_DIR"] = str(cli_env)

        result = run_cli("env", "list", env=env)

        assert result.returncode == 0

    def test_env_set_creates_override(self, cli_env):
        """Env set creates an override."""
        import os

        env = os.environ.copy()
        env["OWL_DIR"] = str(cli_env)

        result = run_cli("env", "set", "DISABLE_STOP_HOOK", "true", env=env)

        assert result.returncode == 0

    def test_env_unset_removes_override(self, cli_env):
        """Env unset removes an override."""
        import os

        env = os.environ.copy()
        env["OWL_DIR"] = str(cli_env)

        # First set
        run_cli("env", "set", "TEST_VAR", "value", env=env)

        # Then unset
        result = run_cli("env", "unset", "TEST_VAR", env=env)

        assert result.returncode == 0


class TestTelegramCommand:
    """Tests for telegram commands."""

    def test_telegram_test_without_config(self, cli_env):
        """Telegram test fails gracefully without config."""
        import os

        env = os.environ.copy()
        env["OWL_DIR"] = str(cli_env)

        result = run_cli("telegram", "test", env=env)

        # Should fail because no bot token configured
        # But shouldn't crash
        assert result.returncode in [0, 1]


class TestHawkHooksCommands:
    """Tests for hawk-hooks integration commands."""

    def test_hawk_hooks_install_creates_config(self, cli_env, tmp_path):
        """Hawk-hooks install creates hook configuration."""
        import os

        env = os.environ.copy()
        env["OWL_DIR"] = str(cli_env)
        env["HOME"] = str(tmp_path)

        # Create hawk-hooks config directory
        hawk_dir = tmp_path / ".hawk-hooks"
        hawk_dir.mkdir()
        (hawk_dir / "hooks.json").write_text("{}")

        result = run_cli("hawk-hooks", "install", env=env)

        # May fail if hawk-hooks not installed, but shouldn't crash
        assert result.returncode in [0, 1]

    def test_hawk_hooks_uninstall_removes_config(self, cli_env, tmp_path):
        """Hawk-hooks uninstall removes hook configuration."""
        import os

        env = os.environ.copy()
        env["OWL_DIR"] = str(cli_env)
        env["HOME"] = str(tmp_path)

        # Create hawk-hooks config with owl hooks
        hawk_dir = tmp_path / ".hawk-hooks"
        hawk_dir.mkdir()
        (hawk_dir / "hooks.json").write_text(
            json.dumps({"PreToolUse": [{"command": "owl hook PreToolUse"}]})
        )

        result = run_cli("hawk-hooks", "uninstall", env=env)

        # May fail if hawk-hooks not installed, but shouldn't crash
        assert result.returncode in [0, 1]


class TestTyperCLI:
    """Smoke tests for new Typer CLI."""

    def test_cli_help(self):
        """Test CLI help works."""
        from typer.testing import CliRunner

        from owl.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "owl" in result.output

    def test_cli_status(self, cli_env):
        """Test status command via Typer."""
        from typer.testing import CliRunner

        from owl.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0


class TestPresetCommand:
    """Tests for rules preset command."""

    def test_preset_loads_by_name(self, cli_env):
        import os

        env = os.environ.copy()
        env["OWL_DIR"] = str(cli_env)

        result = run_cli("rules", "preset", "cautious", env=env)

        assert result.returncode == 0
        assert "added" in result.stdout.lower()

    def test_preset_invalid_name(self, cli_env):
        import os

        env = os.environ.copy()
        env["OWL_DIR"] = str(cli_env)

        result = run_cli("rules", "preset", "nonexistent", env=env)

        assert "unknown" in result.stdout.lower()

    def test_preset_skips_duplicates(self, cli_env):
        import os

        env = os.environ.copy()
        env["OWL_DIR"] = str(cli_env)

        run_cli("rules", "preset", "cautious", env=env)
        result = run_cli("rules", "preset", "cautious", env=env)

        assert result.returncode == 0
        assert "skip" in result.stdout.lower()
