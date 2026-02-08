"""Integration tests for wrapper chain expansion flow.

Tests the complete button-press -> handler -> state update -> message edit cycle
for wrapper chain expansion (ssh, docker, etc.) using FakeTelegramNotifier.
"""

import json

import pytest

from owl.core.command_parser import CommandParser
from owl.core.handlers.chain import ChainStateManager
from owl.core.rules import RulesEngine
from owl.core.storage import Storage

from tests.helpers.fake_telegram import ChainApprovalSimulator


async def _setup_storage(mock_owl_dir) -> Storage:
    """Create and initialize storage for tests."""
    storage = Storage(mock_owl_dir / "test.db")
    await storage.connect()
    return storage


async def _create_chain_request(
    sim: ChainApprovalSimulator,
    cmd: str,
    session_id: str = "s1",
    project_path: str = "/test/project",
) -> tuple[str, int]:
    """Create a pending request and send chain UI. Returns (request_id, msg_id)."""
    storage = sim.storage

    await storage.upsert_session(session_id, project_path)

    tool_input = json.dumps({"command": cmd})
    request_id = await storage.create_request(
        session_id=session_id,
        tool_name="Bash",
        tool_input=tool_input,
    )

    # Analyze chain to get commands and title
    parser = CommandParser()
    analysis = parser.analyze_chain(cmd)

    # Initialize chain state (like get_or_init_state would)
    chain_mgr = ChainStateManager(storage)
    state = {
        "commands": analysis.commands,
        "approved_indices": [],
    }
    if analysis.chain_title:
        state["chain_title"] = analysis.chain_title
    await chain_mgr.save_state(request_id, state, version=0)

    # Send chain UI
    msg_id = await sim.notifier.send_chain_approval_request(
        request_id=request_id,
        session_id=session_id,
        commands=analysis.commands,
        project_path=project_path,
        chain_title=analysis.chain_title,
    )

    return request_id, msg_id


# --- Wrapper chain approval flow ---


@pytest.mark.asyncio
async def test_ssh_wrapper_chain_approval(mock_owl_dir):
    """SSH wrapper chain: approve each command individually."""
    storage = await _setup_storage(mock_owl_dir)
    sim = ChainApprovalSimulator(storage)

    request_id, msg_id = await _create_chain_request(
        sim, "ssh aarni 'cd /tmp && ls -la && rm foo'"
    )

    # Verify initial display has wrapper title and stripped commands
    initial = sim.notifier.messages[0]
    assert "ssh aarni" in initial.text
    assert "cd /tmp" in initial.text
    assert "ls -la" in initial.text
    assert "rm foo" in initial.text

    # Verify markers: first is →, rest are spaces
    markers = sim.notifier.get_chain_markers(msg_id)
    assert markers == ["→", " ", " "]

    # Approve first command (cd /tmp)
    await sim.approve_command(request_id, 0, msg_id)

    # Check progress
    markers = sim.notifier.get_chain_markers(msg_id)
    assert markers == ["✓", "→", " "]

    # Approve second command (ls -la)
    await sim.approve_command(request_id, 1, msg_id)

    markers = sim.notifier.get_chain_markers(msg_id)
    assert markers == ["✓", "✓", "→"]

    # Approve third command (rm foo) → auto-resolves
    await sim.approve_command(request_id, 2, msg_id)

    # Request should be resolved
    request = await storage.get_request(request_id)
    assert request.status == "approved"

    await storage.close()


@pytest.mark.asyncio
async def test_docker_wrapper_chain_approval(mock_owl_dir):
    """Docker wrapper chain expansion works like SSH."""
    storage = await _setup_storage(mock_owl_dir)
    sim = ChainApprovalSimulator(storage)

    request_id, msg_id = await _create_chain_request(
        sim, "docker exec app 'npm install && npm test'"
    )

    # Verify display
    initial = sim.notifier.messages[0]
    assert "docker exec app" in initial.text
    assert "npm install" in initial.text
    assert "npm test" in initial.text

    # Approve both
    await sim.approve_command(request_id, 0, msg_id)
    await sim.approve_command(request_id, 1, msg_id)

    request = await storage.get_request(request_id)
    assert request.status == "approved"

    await storage.close()


@pytest.mark.asyncio
async def test_wrapper_chain_deny(mock_owl_dir):
    """Denying a wrapper chain denies the entire request."""
    storage = await _setup_storage(mock_owl_dir)
    sim = ChainApprovalSimulator(storage)

    request_id, msg_id = await _create_chain_request(
        sim, "ssh aarni 'cd /tmp && rm -rf *'"
    )

    # Deny the chain
    await sim.deny_chain(request_id, msg_id)

    request = await storage.get_request(request_id)
    assert request.status == "denied"

    await storage.close()


@pytest.mark.asyncio
async def test_wrapper_chain_approve_entire(mock_owl_dir):
    """Approve entire chain at once skips individual approval."""
    storage = await _setup_storage(mock_owl_dir)
    sim = ChainApprovalSimulator(storage)

    request_id, msg_id = await _create_chain_request(
        sim, "ssh aarni 'cd /tmp && ls -la && echo done'"
    )

    # Approve entire chain at once
    await sim.approve_entire(request_id, msg_id)

    request = await storage.get_request(request_id)
    assert request.status == "approved"

    await storage.close()


# --- Wrapper title display ---


@pytest.mark.asyncio
async def test_wrapper_title_in_display(mock_owl_dir):
    """Wrapper title should appear in chain messages."""
    storage = await _setup_storage(mock_owl_dir)
    sim = ChainApprovalSimulator(storage)

    request_id, msg_id = await _create_chain_request(
        sim, "ssh aarni 'cd /tmp && ls'"
    )

    # Title should be bold wrapper prefix
    msg = sim.notifier.messages[0]
    assert "<b>ssh aarni</b>" in msg.text

    # Commands should be stripped of wrapper prefix
    assert "→ <code>cd /tmp</code>" in msg.text
    # "ssh aarni cd /tmp" should NOT appear as display text
    assert "ssh aarni cd /tmp" not in msg.text

    await storage.close()


@pytest.mark.asyncio
async def test_regular_chain_no_title(mock_owl_dir):
    """Regular chains should have default title, no prefix stripping."""
    storage = await _setup_storage(mock_owl_dir)
    sim = ChainApprovalSimulator(storage)

    request_id, msg_id = await _create_chain_request(
        sim, "git fetch && git push"
    )

    msg = sim.notifier.messages[0]
    assert "<b>Command chain approval:</b>" in msg.text
    assert "git fetch" in msg.text
    assert "git push" in msg.text

    await storage.close()


# --- Compound command flow ---


@pytest.mark.asyncio
async def test_compound_for_loop_chain(mock_owl_dir):
    """For loop compound command should expand to inner commands."""
    storage = await _setup_storage(mock_owl_dir)
    sim = ChainApprovalSimulator(storage)

    request_id, msg_id = await _create_chain_request(
        sim, "for f in *.txt; do rm $f; done"
    )

    msg = sim.notifier.messages[0]
    assert "For: for f in *.txt" in msg.text
    assert "rm $f" in msg.text

    # Approve the single inner command
    await sim.approve_command(request_id, 0, msg_id)

    request = await storage.get_request(request_id)
    assert request.status == "approved"

    await storage.close()


# --- State consistency ---


@pytest.mark.asyncio
async def test_chain_state_persists_chain_title(mock_owl_dir):
    """chain_title should be persisted in chain state for callback consistency."""
    storage = await _setup_storage(mock_owl_dir)
    sim = ChainApprovalSimulator(storage)

    request_id, msg_id = await _create_chain_request(
        sim, "ssh aarni 'cd /tmp && ls'"
    )

    # Read state back
    chain_mgr = ChainStateManager(storage)
    result = await chain_mgr.get_state(request_id)
    assert result is not None
    state, version = result
    assert state["chain_title"] == "ssh aarni"
    assert state["commands"] == ["ssh aarni cd /tmp", "ssh aarni ls"]

    await storage.close()


@pytest.mark.asyncio
async def test_get_or_init_state_uses_analyze_chain(mock_owl_dir):
    """get_or_init_state should use analyze_chain for consistent parsing."""
    storage = await _setup_storage(mock_owl_dir)

    # Create request without pre-initialized state
    await storage.upsert_session("s1", "/test")
    tool_input = json.dumps({"command": "ssh aarni 'cd /tmp && ls'"})
    request_id = await storage.create_request(
        session_id="s1",
        tool_name="Bash",
        tool_input=tool_input,
    )

    # get_or_init_state should parse via analyze_chain
    chain_mgr = ChainStateManager(storage)
    result = await chain_mgr.get_or_init_state(request_id, tool_input)
    assert result is not None
    state, version = result

    assert state["commands"] == ["ssh aarni cd /tmp", "ssh aarni ls"]
    assert state["chain_title"] == "ssh aarni"
    assert version == 0  # Freshly initialized

    await storage.close()


# --- Rule creation within chains ---


@pytest.mark.asyncio
async def test_wrapper_chain_with_pre_approved_rules(mock_owl_dir):
    """Commands matching existing rules should be pre-approved."""
    storage = await _setup_storage(mock_owl_dir)

    # Add rule that approves "ssh aarni ls *"
    engine = RulesEngine(storage)
    await engine.add_rule("Bash(ssh aarni ls *)", "approve", priority=0)

    sim = ChainApprovalSimulator(storage)

    # Create request - "ls" should be auto-approved
    tool_input = json.dumps({"command": "ssh aarni 'cd /tmp && ls -la'"})
    await storage.upsert_session("s1", "/test")
    request_id = await storage.create_request(
        session_id="s1",
        tool_name="Bash",
        tool_input=tool_input,
    )

    # get_or_init_state should detect the rule match
    chain_mgr = ChainStateManager(storage)
    result = await chain_mgr.get_or_init_state(request_id, tool_input)
    state, version = result

    # "ssh aarni ls -la" should match "ssh aarni ls *" rule
    assert 1 in state["approved_indices"]
    # "ssh aarni cd /tmp" should NOT be pre-approved
    assert 0 not in state["approved_indices"]

    await storage.close()


# --- Edge cases ---


@pytest.mark.asyncio
async def test_ssh_no_inner_chain_not_expanded(mock_owl_dir):
    """SSH with single command should NOT be treated as wrapper chain."""
    storage = await _setup_storage(mock_owl_dir)

    parser = CommandParser()
    analysis = parser.analyze_chain("ssh aarni ls -la")

    assert not analysis.is_chain or len(analysis.steps) == 1
    assert analysis.chain_title is None

    await storage.close()


@pytest.mark.asyncio
async def test_ssh_top_level_chain_not_wrapper_expanded(mock_owl_dir):
    """SSH followed by && should be regular chain, not wrapper expanded."""
    storage = await _setup_storage(mock_owl_dir)
    sim = ChainApprovalSimulator(storage)

    request_id, msg_id = await _create_chain_request(
        sim, "ssh aarni 'ls' && echo done"
    )

    msg = sim.notifier.messages[0]
    # Should be regular chain with default title
    assert "<b>Command chain approval:</b>" in msg.text
    # Should show full commands, not stripped
    assert "ssh aarni" in msg.text
    assert "echo done" in msg.text

    await storage.close()
