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


def test_hook_matchers_include_websearch():
    """Verify WebSearch is included in hook matchers."""
    from pyafk.cli.install import get_pyafk_hooks

    hooks = get_pyafk_hooks()

    # Check PreToolUse matcher includes WebSearch
    pretool = hooks.get("PreToolUse", [])
    assert len(pretool) > 0
    matcher = pretool[0].get("matcher", "")
    assert "WebSearch" in matcher, f"WebSearch not in PreToolUse matcher: {matcher}"

    # Check PostToolUse matcher includes WebSearch
    posttool = hooks.get("PostToolUse", [])
    assert len(posttool) > 0
    matcher = posttool[0].get("matcher", "")
    assert "WebSearch" in matcher, f"WebSearch not in PostToolUse matcher: {matcher}"

    # Check PermissionRequest matcher includes WebSearch
    perm = hooks.get("PermissionRequest", [])
    assert len(perm) > 0
    matcher = perm[0].get("matcher", "")
    assert "WebSearch" in matcher, (
        f"WebSearch not in PermissionRequest matcher: {matcher}"
    )


def test_hook_matchers_include_all_expected_tools():
    """Verify all expected tools are in hook matchers."""
    from pyafk.cli.install import get_pyafk_hooks

    hooks = get_pyafk_hooks()
    pretool = hooks.get("PreToolUse", [])
    matcher = pretool[0].get("matcher", "")

    expected_tools = [
        "Bash",
        "Edit",
        "Write",
        "MultiEdit",
        "WebFetch",
        "WebSearch",
        "Skill",
    ]
    for tool in expected_tools:
        assert tool in matcher, f"{tool} not in hook matcher: {matcher}"

    # MCP tools should be matched via pattern
    assert "mcp__" in matcher, f"MCP pattern not in hook matcher: {matcher}"
