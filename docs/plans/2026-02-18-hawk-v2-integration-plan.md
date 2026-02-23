# owl-afk hawk-hooks v2 Integration Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make owl-afk compatible with hawk-hooks v2 registry-based architecture while keeping standalone install working.

**Architecture:** Add `hooks/` directory with v2-compatible shell wrappers. Update `install.py` to detect hawk v2 and delegate to `hawk scan`. Update detection logic. All 8 events owl uses get hook files.

**Tech Stack:** Python, bash, hawk-hooks v2 CLI

---

### Task 1: Create hook shell scripts

**Files:**
- Create: `hooks/owl-pre-tool-use.sh`
- Create: `hooks/owl-post-tool-use.sh`
- Create: `hooks/owl-permission-request.sh`
- Create: `hooks/owl-subagent-stop.sh`
- Create: `hooks/owl-stop.sh`
- Create: `hooks/owl-session-start.sh`
- Create: `hooks/owl-pre-compact.sh`
- Create: `hooks/owl-session-end.sh`

**Step 1: Create the 8 hook wrapper scripts**

Each script follows this pattern with `# hawk-hook:` metadata:

```bash
# hooks/owl-pre-tool-use.sh
#!/usr/bin/env bash
# hawk-hook: events=pre_tool_use
# hawk-hook: description=OWL AFK pre-tool-use gate
# hawk-hook: timeout=3600
exec owl hook PreToolUse
```

Scripts that need `timeout=3600` (they wait for user approval):
- owl-pre-tool-use.sh (pre_tool_use)
- owl-permission-request.sh (permission_request)
- owl-subagent-stop.sh (subagent_stop)
- owl-stop.sh (stop)

Scripts without timeout (fire-and-forget):
- owl-post-tool-use.sh (post_tool_use)
- owl-session-start.sh (session_start)
- owl-pre-compact.sh (pre_compact)
- owl-session-end.sh (session_end)

**Step 2: Make scripts executable**

```bash
chmod +x hooks/*.sh
```

**Step 3: Commit**

```bash
git add hooks/
git commit -m "feat: add hawk-hooks v2 compatible hook scripts"
```

---

### Task 2: Update install.py — add v2 constants and detection

**Files:**
- Modify: `src/owl/cli/install.py`

**Step 1: Add v2 constants and update detection**

Add at the top of `install.py` alongside existing constants:

```python
# Hawk v2 registry
HAWK_V2_REGISTRY = Path.home() / ".config" / "hawk-hooks" / "registry"
HAWK_V2_HOOK_NAMES = [
    "owl-pre-tool-use.sh",
    "owl-post-tool-use.sh",
    "owl-permission-request.sh",
    "owl-subagent-stop.sh",
    "owl-stop.sh",
    "owl-session-start.sh",
    "owl-pre-compact.sh",
    "owl-session-end.sh",
]
```

**Step 2: Update `check_hooks_installed()` to detect v2**

```python
def check_hooks_installed() -> tuple[bool, str]:
    # Check v2 first (registry-based)
    v2_hook = HAWK_V2_REGISTRY / "hooks" / "owl-pre-tool-use.sh"
    if v2_hook.exists():
        return True, "hawk-v2"

    # Check v1 (directory-based)
    v1_hook = HAWK_HOOKS_DIR / "pre_tool_use" / "owl-pre_tool_use.sh"
    if v1_hook.exists():
        return True, "hawk-hooks"

    # Check standalone
    settings_path = get_claude_settings_path()
    if settings_path and settings_path.exists():
        settings = load_claude_settings(settings_path)
        hooks = settings.get("hooks", {})
        for hook_entries in hooks.values():
            for entry in hook_entries:
                if is_owl_hook(entry):
                    return True, "standalone"

    return False, "none"
```

**Step 3: Update `check_hawk_hooks_installed()` to detect both versions**

```python
def check_hawk_hooks_installed() -> bool:
    # v2
    v2_hook = HAWK_V2_REGISTRY / "hooks" / "owl-pre-tool-use.sh"
    if v2_hook.exists():
        return True
    # v1
    return (HAWK_HOOKS_DIR / "pre_tool_use" / "owl-pre_tool_use.sh").exists()
```

**Step 4: Commit**

```bash
git add src/owl/cli/install.py
git commit -m "feat: add hawk v2 detection to install checks"
```

---

### Task 3: Add `do_hawk_v2_install()` function

**Files:**
- Modify: `src/owl/cli/install.py`

**Step 1: Add the v2 install function**

```python
def _get_hooks_dir() -> Path:
    """Get the path to owl's bundled hooks/ directory."""
    return Path(__file__).resolve().parent.parent.parent.parent / "hooks"


def do_hawk_v2_install(force: bool = False):
    """Install owl hooks via hawk v2 (hawk scan)."""
    if check_standalone_installed() and not force:
        console.print(
            "[red]Error:[/red] Standalone owl hooks are already installed."
        )
        console.print(
            "Having both can cause duplicate approvals and notifications."
        )
        console.print()
        console.print("Options:")
        console.print("  1. Run [cyan]owl uninstall[/cyan] first")
        console.print("  2. Use [cyan]owl hawk install --force[/cyan] to override")
        return

    hooks_dir = _get_hooks_dir()
    if not hooks_dir.exists():
        console.print(f"[red]Error:[/red] Hook scripts not found at {hooks_dir}")
        console.print("Is owl installed correctly?")
        return

    console.print("[bold]Installing via hawk v2...[/bold]")

    try:
        result = subprocess.run(
            ["hawk", "scan", str(hooks_dir), "--all"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            console.print(f"[red]Error:[/red] hawk scan failed: {result.stderr.strip()}")
            return

        result = subprocess.run(
            ["hawk", "sync"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            console.print(f"[yellow]Warning:[/yellow] hawk sync failed: {result.stderr.strip()}")
            console.print("Run [cyan]hawk sync[/cyan] manually.")
            return

        console.print("[green]Done![/green] Hooks registered and synced.")
    except FileNotFoundError:
        console.print("[red]Error:[/red] hawk CLI not found.")
        console.print("Install hawk-hooks: [cyan]pip install hawk-hooks[/cyan]")
```

**Step 2: Commit**

```bash
git add src/owl/cli/install.py
git commit -m "feat: add do_hawk_v2_install() using hawk scan"
```

---

### Task 4: Update commands.py — route hawk install to v2

**Files:**
- Modify: `src/owl/cli/commands.py`

**Step 1: Update imports and `cmd_hawk_hooks_install`**

Add `do_hawk_v2_install` and `HAWK_V2_REGISTRY` to imports from `install.py`.

Update `cmd_hawk_hooks_install`:

```python
def cmd_hawk_hooks_install(force: bool = False):
    """Install owl hooks for hawk-hooks."""
    # Prefer v2 if available
    if HAWK_V2_REGISTRY.exists():
        do_hawk_v2_install(force=force)
        return

    # Fall back to v1
    if not HAWK_HOOKS_DIR.exists():
        print(f"Error: hawk-hooks not found.")
        print("Install hawk-hooks: pip install hawk-hooks")
        sys.exit(1)

    do_hawk_hooks_install(force=force)
```

**Step 2: Update `cmd_hawk_hooks_uninstall` to handle v2**

```python
def cmd_hawk_hooks_uninstall(args):
    """Remove owl hooks from hawk-hooks."""
    # Try v2 first
    if HAWK_V2_REGISTRY.exists():
        _hawk_v2_uninstall()
        return

    # v1 fallback
    removed = False
    for event in HOOK_EVENTS:
        wrapper_name = f"owl-{event}.sh"
        wrapper_path = HAWK_HOOKS_DIR / event / wrapper_name
        if wrapper_path.exists():
            wrapper_path.unlink()
            print(f"Removed: {event}/{wrapper_name}")
            removed = True

    if removed:
        print()
        print("Done! Run 'hawk-hooks toggle' to update runners.")
    else:
        print("No owl hooks found in hawk-hooks.")


def _hawk_v2_uninstall():
    """Remove owl hooks from hawk v2 registry."""
    from owl.cli.install import HAWK_V2_HOOK_NAMES
    from owl.cli.ui import console

    removed = False
    for name in HAWK_V2_HOOK_NAMES:
        try:
            result = subprocess.run(
                ["hawk", "remove", "hook", name],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                console.print(f"  [green]✓[/green] Removed {name}")
                removed = True
        except FileNotFoundError:
            console.print("[red]Error:[/red] hawk CLI not found.")
            return

    if removed:
        subprocess.run(["hawk", "sync"], capture_output=True, text=True)
        console.print("[green]Done![/green] Hooks removed and synced.")
    else:
        console.print("No owl hooks found in hawk v2 registry.")
```

**Step 3: Commit**

```bash
git add src/owl/cli/commands.py
git commit -m "feat: route hawk install/uninstall to v2 when available"
```

---

### Task 5: Update wizard detection

**Files:**
- Modify: `src/owl/cli/ui/interactive.py`

**Step 1: Update wizard to detect v2**

In `run_wizard()`, replace the `hawk_available` check:

```python
# Replace:
hawk_available = HAWK_HOOKS_DIR.exists()

# With:
from owl.cli.install import HAWK_V2_REGISTRY
hawk_v2 = HAWK_V2_REGISTRY.exists()
hawk_v1 = HAWK_HOOKS_DIR.exists()
hawk_available = hawk_v2 or hawk_v1
```

And update the install dispatch:

```python
# Replace:
elif choice == 1 and hawk_available:
    do_hawk_hooks_install()

# With:
elif choice == 1 and hawk_available:
    if hawk_v2:
        do_hawk_v2_install()
    else:
        do_hawk_hooks_install()
```

Update the import to include `do_hawk_v2_install`.

**Step 2: Commit**

```bash
git add src/owl/cli/ui/interactive.py
git commit -m "feat: wizard detects hawk v2 for install"
```

---

### Task 6: Write tests for v2 detection and install

**Files:**
- Modify: `tests/test_install.py`

**Step 1: Add v2 detection tests**

```python
def test_check_hooks_installed_hawk_v2(tmp_path, monkeypatch):
    """Detect hawk v2 registry hooks."""
    registry = tmp_path / ".config" / "hawk-hooks" / "registry" / "hooks"
    registry.mkdir(parents=True)
    (registry / "owl-pre-tool-use.sh").write_text("#!/bin/bash\nexec owl hook PreToolUse")

    monkeypatch.setattr("owl.cli.install.HAWK_V2_REGISTRY", tmp_path / ".config" / "hawk-hooks" / "registry")

    from owl.cli.install import check_hooks_installed
    installed, mode = check_hooks_installed()
    assert installed is True
    assert mode == "hawk-v2"


def test_check_hooks_installed_v2_takes_priority(tmp_path, monkeypatch):
    """v2 detection should take priority over v1 and standalone."""
    # Set up v2
    registry = tmp_path / ".config" / "hawk-hooks" / "registry" / "hooks"
    registry.mkdir(parents=True)
    (registry / "owl-pre-tool-use.sh").write_text("#!/bin/bash")

    # Set up v1
    v1_dir = tmp_path / ".config" / "hawk-hooks" / "hooks" / "pre_tool_use"
    v1_dir.mkdir(parents=True)
    (v1_dir / "owl-pre_tool_use.sh").write_text("#!/bin/bash")

    monkeypatch.setattr("owl.cli.install.HAWK_V2_REGISTRY", tmp_path / ".config" / "hawk-hooks" / "registry")
    monkeypatch.setattr("owl.cli.install.HAWK_HOOKS_DIR", tmp_path / ".config" / "hawk-hooks" / "hooks")

    from owl.cli.install import check_hooks_installed
    installed, mode = check_hooks_installed()
    assert installed is True
    assert mode == "hawk-v2"


def test_hooks_dir_exists():
    """Verify bundled hooks directory exists with expected scripts."""
    from owl.cli.install import _get_hooks_dir
    hooks_dir = _get_hooks_dir()
    assert hooks_dir.exists(), f"hooks/ directory not found at {hooks_dir}"
    scripts = sorted(f.name for f in hooks_dir.glob("*.sh"))
    assert len(scripts) == 8
    assert "owl-pre-tool-use.sh" in scripts
```

**Step 2: Run tests**

```bash
cd /Users/pkronstrom/Projects/own/owl-afk && python3 -m pytest tests/test_install.py -v
```

**Step 3: Commit**

```bash
git add tests/test_install.py
git commit -m "test: add hawk v2 detection and hook scripts tests"
```
