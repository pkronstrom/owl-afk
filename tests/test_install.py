"""Tests for install/uninstall commands."""

import json
import subprocess
import sys



def run_cli(*args, env=None, input_text=None):
    """Run pyafk CLI command and return result."""
    cmd = [sys.executable, "-m", "pyafk.cli"] + list(args)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        input=input_text,
    )
    return result


def test_install_creates_hooks(mock_pyafk_dir, tmp_path):
    """Install should create hook configuration."""
    import os

    env = os.environ.copy()
    env["PYAFK_DIR"] = str(mock_pyafk_dir)
    env["HOME"] = str(tmp_path)

    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()

    result = run_cli("install", env=env, input_text="y\n")

    assert result.returncode == 0
    settings_file = claude_dir / "settings.json"
    assert settings_file.exists()
    settings = json.loads(settings_file.read_text())
    assert "hooks" in settings


def test_uninstall_removes_hooks(mock_pyafk_dir, tmp_path):
    """Uninstall should remove hook configuration."""
    import os

    env = os.environ.copy()
    env["PYAFK_DIR"] = str(mock_pyafk_dir)
    env["HOME"] = str(tmp_path)

    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings_file = claude_dir / "settings.json"
    settings_file.write_text(
        json.dumps({"hooks": {"PreToolUse": [{"command": "pyafk hook PreToolUse"}]}})
    )

    result = run_cli("uninstall", env=env, input_text="y\n")

    assert result.returncode == 0
    settings = json.loads(settings_file.read_text())
    # After uninstall, PreToolUse should be empty or removed
    hooks = settings.get("hooks", {})
    pretool_hooks = hooks.get("PreToolUse", [])
    # Check that pyafk hooks are removed
    pyafk_hooks = [h for h in pretool_hooks if "pyafk" in h.get("command", "")]
    assert len(pyafk_hooks) == 0
