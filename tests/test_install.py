"""Tests for install/uninstall commands."""

import json
import subprocess
import sys


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


def test_install_creates_hooks(mock_owl_dir, tmp_path):
    """Install should create hook configuration."""
    import os

    env = os.environ.copy()
    env["OWL_DIR"] = str(mock_owl_dir)
    env["HOME"] = str(tmp_path)

    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()

    result = run_cli("install", env=env, input_text="y\n")

    assert result.returncode == 0
    settings_file = claude_dir / "settings.json"
    assert settings_file.exists()
    settings = json.loads(settings_file.read_text())
    assert "hooks" in settings


def test_uninstall_removes_hooks(mock_owl_dir, tmp_path):
    """Uninstall should remove hook configuration."""
    import os

    env = os.environ.copy()
    env["OWL_DIR"] = str(mock_owl_dir)
    env["HOME"] = str(tmp_path)

    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings_file = claude_dir / "settings.json"
    settings_file.write_text(
        json.dumps({"hooks": {"PreToolUse": [{"command": "owl hook PreToolUse"}]}})
    )

    result = run_cli("uninstall", env=env, input_text="y\n")

    assert result.returncode == 0
    settings = json.loads(settings_file.read_text())
    # After uninstall, PreToolUse should be empty or removed
    hooks = settings.get("hooks", {})
    pretool_hooks = hooks.get("PreToolUse", [])
    # Check that owl hooks are removed
    owl_hooks = [h for h in pretool_hooks if "owl" in h.get("command", "")]
    assert len(owl_hooks) == 0


def test_hook_matchers_include_websearch():
    """Verify WebSearch is included in hook matchers."""
    from owl.cli.install import get_owl_hooks

    hooks = get_owl_hooks()

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
    from owl.cli.install import get_owl_hooks

    hooks = get_owl_hooks()
    pretool = hooks.get("PreToolUse", [])
    matcher = pretool[0].get("matcher", "")

    expected_tools = [
        "Bash",
        "Edit",
        "Write",
        "MultiEdit",
        "Read",
        "Glob",
        "Grep",
        "NotebookEdit",
        "NotebookRead",
        "Task",
        "WebFetch",
        "WebSearch",
        "Skill",
    ]
    for tool in expected_tools:
        assert tool in matcher, f"{tool} not in hook matcher: {matcher}"

    # MCP tools should be matched via pattern
    assert "mcp__" in matcher, f"MCP pattern not in hook matcher: {matcher}"


def test_check_hooks_installed_hawk_v2(tmp_path, monkeypatch):
    """Detect hawk v2 registry hooks."""
    registry = tmp_path / ".config" / "hawk-hooks" / "registry"
    hooks_dir = registry / "hooks"
    hooks_dir.mkdir(parents=True)
    (hooks_dir / "owl-pre-tool-use.sh").write_text("#!/bin/bash\nexec owl hook PreToolUse")

    monkeypatch.setattr("owl.cli.install.HAWK_V2_REGISTRY", registry)

    from owl.cli.install import check_hooks_installed
    installed, mode = check_hooks_installed()
    assert installed is True
    assert mode == "hawk-v2"


def test_check_hooks_installed_v2_takes_priority(tmp_path, monkeypatch):
    """v2 detection should take priority over v1 and standalone."""
    # Set up v2
    registry = tmp_path / ".config" / "hawk-hooks" / "registry"
    hooks_dir = registry / "hooks"
    hooks_dir.mkdir(parents=True)
    (hooks_dir / "owl-pre-tool-use.sh").write_text("#!/bin/bash")

    # Set up v1
    v1_dir = tmp_path / ".config" / "hawk-hooks" / "hooks" / "pre_tool_use"
    v1_dir.mkdir(parents=True)
    (v1_dir / "owl-pre_tool_use.sh").write_text("#!/bin/bash")

    monkeypatch.setattr("owl.cli.install.HAWK_V2_REGISTRY", registry)
    monkeypatch.setattr("owl.cli.install.HAWK_HOOKS_DIR", tmp_path / ".config" / "hawk-hooks" / "hooks")

    from owl.cli.install import check_hooks_installed
    installed, mode = check_hooks_installed()
    assert installed is True
    assert mode == "hawk-v2"


def test_check_hooks_installed_v1_fallback(tmp_path, monkeypatch):
    """Falls back to v1 detection when v2 not present."""
    # No v2
    monkeypatch.setattr("owl.cli.install.HAWK_V2_REGISTRY", tmp_path / "nonexistent")

    # Set up v1
    v1_dir = tmp_path / ".config" / "hawk-hooks" / "hooks" / "pre_tool_use"
    v1_dir.mkdir(parents=True)
    (v1_dir / "owl-pre_tool_use.sh").write_text("#!/bin/bash")
    monkeypatch.setattr("owl.cli.install.HAWK_HOOKS_DIR", tmp_path / ".config" / "hawk-hooks" / "hooks")

    from owl.cli.install import check_hooks_installed
    installed, mode = check_hooks_installed()
    assert installed is True
    assert mode == "hawk-hooks"


def test_bundled_hooks_dir_exists():
    """Verify bundled hooks directory exists with expected scripts."""
    from owl.cli.install import _get_hooks_dir
    hooks_dir = _get_hooks_dir()
    assert hooks_dir.exists(), f"hooks/ directory not found at {hooks_dir}"
    scripts = sorted(f.name for f in hooks_dir.glob("*.sh"))
    assert len(scripts) == 8
    assert "owl-pre-tool-use.sh" in scripts
    assert "owl-session-start.sh" in scripts


def test_bundled_hooks_have_hawk_metadata():
    """Verify all bundled hooks have hawk-hook metadata."""
    from owl.cli.install import _get_hooks_dir
    hooks_dir = _get_hooks_dir()
    for script in hooks_dir.glob("*.sh"):
        content = script.read_text()
        assert "# hawk-hook: events=" in content, f"{script.name} missing events metadata"
        assert "# hawk-hook: description=" in content, f"{script.name} missing description metadata"
        assert content.startswith("#!/usr/bin/env bash"), f"{script.name} missing shebang"
        assert "exec owl hook " in content, f"{script.name} missing exec owl hook"
