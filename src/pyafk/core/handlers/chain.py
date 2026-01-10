"""Chain approval handlers for bash command chains."""

import hashlib
import json
from typing import TYPE_CHECKING, Any, Optional

from pyafk.core.command_parser import CommandParser
from pyafk.core.handlers.base import CallbackContext
from pyafk.utils.debug import debug_callback, debug_chain
from pyafk.utils.formatting import (
    escape_html,
    format_project_id,
    truncate_command,
)

if TYPE_CHECKING:
    from pyafk.core.storage import Storage


class ChainStateManager:
    """Manages chain approval state in storage.

    Chain state tracks which commands in a bash chain have been approved.
    Uses optimistic locking with version numbers for concurrent access safety.
    """

    def __init__(self, storage: "Storage") -> None:
        self.storage = storage

    def _state_key(self, request_id: str) -> int:
        """Generate stable key for chain state storage.

        Uses hashlib for stable hashing across process restarts
        (Python's hash() is randomized by PYTHONHASHSEED).
        Uses 15 hex chars (60 bits) to stay within SQLite signed INTEGER max.
        """
        return int(hashlib.md5(f"chain:{request_id}".encode()).hexdigest()[:15], 16)

    async def get_state(self, request_id: str) -> Optional[tuple[dict[str, Any], int]]:
        """Get chain approval state and version.

        Returns (state_dict, version) or None if no state exists.
        """
        msg_id = self._state_key(request_id)
        result = await self.storage.get_chain_state(msg_id)
        if result:
            state_json, version = result
            try:
                return (json.loads(state_json), version)
            except (json.JSONDecodeError, TypeError):
                pass
        return None

    async def save_state(
        self, request_id: str, state: dict[str, Any], version: int
    ) -> bool:
        """Save chain approval state atomically.

        Args:
            request_id: The request identifier
            state: The chain state dict to save
            version: Expected version for optimistic locking (0 for new state)

        Returns:
            True if saved successfully, False on version conflict.
        """
        state_json = json.dumps(state)
        msg_id = self._state_key(request_id)
        return await self.storage.save_chain_state_atomic(msg_id, state_json, version)

    async def clear_state(self, request_id: str) -> None:
        """Clear chain approval state from storage."""
        msg_id = self._state_key(request_id)
        await self.storage.clear_chain_state(msg_id)

    async def get_or_init_state(
        self, request_id: str, tool_input: Optional[str]
    ) -> Optional[tuple[dict[str, Any], int]]:
        """Get existing state or initialize from tool_input.

        Returns (state, version) or None if initialization fails.
        """
        result = await self.get_state(request_id)
        if result:
            return result

        # Initialize from tool_input
        if not tool_input:
            return None

        try:
            data = json.loads(tool_input)
            cmd = data.get("command", "")
            parser = CommandParser()
            commands = parser.split_chain(cmd)
            state = {
                "commands": commands,
                "approved_indices": [],
            }
            return (state, 0)
        except Exception:
            return None


def format_chain_approved_message(commands: list[str], project_id: str) -> str:
    """Format chain approved message with list of commands."""
    cmd_lines = []
    for cmd in commands:
        cmd_escaped = escape_html(truncate_command(cmd))
        cmd_lines.append(f"  • <code>{cmd_escaped}</code>")

    return f"<i>{escape_html(project_id)}</i>\n✅ <b>Chain approved</b>\n" + "\n".join(
        cmd_lines
    )


class ChainApproveHandler:
    """Handle approval of a single command in a chain."""

    async def handle(self, ctx: CallbackContext) -> None:
        """Approve one command in the chain.

        Target ID format: request_id:command_index
        """
        parts = ctx.target_id.rsplit(":", 1)
        if len(parts) != 2:
            await ctx.notifier.answer_callback(ctx.callback_id, "Invalid format")
            return

        request_id = parts[0]
        try:
            command_idx = int(parts[1])
        except ValueError:
            await ctx.notifier.answer_callback(ctx.callback_id, "Invalid index")
            return

        try:
            debug_chain(
                "chain_approve called", request_id=request_id, command_idx=command_idx
            )
            request = await ctx.storage.get_request(request_id)
            if not request:
                debug_chain("Request not found", request_id=request_id)
                await ctx.notifier.answer_callback(ctx.callback_id, "Request not found")
                if ctx.message_id:
                    await ctx.notifier.edit_message(ctx.message_id, "⚠️ Request expired")
                return

            # Skip if already resolved (handles duplicate callbacks from multiple pollers)
            if request.status != "pending":
                debug_chain(
                    "Request already resolved, skipping",
                    request_id=request_id,
                    status=request.status,
                )
                # Still answer the callback to dismiss Telegram loading state
                await ctx.notifier.answer_callback(ctx.callback_id, "Already processed")
                return

            # Get or initialize chain state
            chain_mgr = ChainStateManager(ctx.storage)
            result = await chain_mgr.get_or_init_state(request_id, request.tool_input)
            if not result:
                await ctx.notifier.answer_callback(
                    ctx.callback_id, "Failed to parse chain"
                )
                return

            chain_state, version = result
            debug_chain("Got chain state", result=result)

            # Mark this command as approved
            if command_idx not in chain_state["approved_indices"]:
                chain_state["approved_indices"].append(command_idx)
                debug_chain(
                    "Added command to approved",
                    command_idx=command_idx,
                    approved=chain_state["approved_indices"],
                )

            # Save updated state with optimistic locking
            if not await chain_mgr.save_state(request_id, chain_state, version):
                # Conflict - re-read and retry once
                debug_chain("Save conflict, retrying", request_id=request_id)
                result = await chain_mgr.get_state(request_id)
                if result:
                    chain_state, version = result
                    if command_idx not in chain_state["approved_indices"]:
                        chain_state["approved_indices"].append(command_idx)
                    await chain_mgr.save_state(request_id, chain_state, version)

            debug_chain(
                "Saved chain state",
                approved_count=len(chain_state["approved_indices"]),
                total=len(chain_state["commands"]),
            )

            await ctx.notifier.answer_callback(ctx.callback_id, "Approved")

            # Check if all commands are approved
            if len(chain_state["approved_indices"]) >= len(chain_state["commands"]):
                debug_chain("All commands approved, auto-approving chain")
                await ctx.storage.resolve_request(
                    request_id=request_id,
                    status="approved",
                    resolved_by="user:chain_all_approved",
                )
                await chain_mgr.clear_state(request_id)

                if ctx.message_id:
                    session = await ctx.storage.get_session(request.session_id)
                    project_id = format_project_id(
                        session.project_path if session else None, request.session_id
                    )
                    msg = format_chain_approved_message(
                        chain_state["commands"], project_id
                    )
                    await ctx.notifier.edit_message(ctx.message_id, msg)

                await ctx.storage.log_audit(
                    event_type="response",
                    session_id=request.session_id,
                    details={
                        "request_id": request_id,
                        "action": "approve",
                        "resolved_by": "user:chain_all_approved",
                        "chain": True,
                        "command_count": len(chain_state["commands"]),
                    },
                )
            else:
                # Find first unapproved command
                next_idx = 0
                while (
                    next_idx < len(chain_state["commands"])
                    and next_idx in chain_state["approved_indices"]
                ):
                    next_idx += 1

                debug_chain(
                    "Moving to next command",
                    next_idx=next_idx,
                    approved_indices=chain_state["approved_indices"],
                )

                if ctx.message_id and next_idx < len(chain_state["commands"]):
                    session = await ctx.storage.get_session(request.session_id)
                    await ctx.notifier.update_chain_progress(
                        message_id=ctx.message_id,
                        request_id=request_id,
                        session_id=request.session_id,
                        commands=chain_state["commands"],
                        current_idx=next_idx,
                        approved_indices=chain_state["approved_indices"],
                        project_path=session.project_path if session else None,
                    )
        except Exception as e:
            debug_callback(
                "Error in ChainApproveHandler",
                error=str(e)[:100],
                request_id=request_id,
            )
            await ctx.notifier.answer_callback(ctx.callback_id, "Error occurred")


class ChainDenyHandler:
    """Handle denial of entire chain."""

    async def handle(self, ctx: CallbackContext) -> None:
        """Deny the entire chain.

        Target ID format: request_id
        """
        request_id = ctx.target_id

        request = await ctx.storage.get_request(request_id)
        if not request:
            await ctx.notifier.answer_callback(ctx.callback_id, "Request not found")
            if ctx.message_id:
                await ctx.notifier.edit_message(ctx.message_id, "⚠️ Request expired")
            return

        # Resolve as denied
        await ctx.storage.resolve_request(
            request_id=request_id,
            status="denied",
            resolved_by="user",
        )

        # Clear chain state
        chain_mgr = ChainStateManager(ctx.storage)
        await chain_mgr.clear_state(request_id)

        await ctx.notifier.answer_callback(ctx.callback_id, "Denied")

        # Update message
        if ctx.message_id:
            result = await chain_mgr.get_state(request_id)
            if result:
                chain_state, _version = result
                session = await ctx.storage.get_session(request.session_id)
                await ctx.notifier.update_chain_progress(
                    message_id=ctx.message_id,
                    request_id=request_id,
                    session_id=request.session_id,
                    commands=chain_state["commands"],
                    current_idx=0,
                    approved_indices=chain_state["approved_indices"],
                    project_path=session.project_path if session else None,
                    denied=True,
                )
            else:
                await ctx.notifier.edit_message(ctx.message_id, "❌ Chain denied")

        await ctx.storage.log_audit(
            event_type="response",
            session_id=request.session_id,
            details={
                "request_id": request_id,
                "action": "deny",
                "resolved_by": "user",
                "chain": True,
            },
        )


class ChainDenyMsgHandler:
    """Handle chain deny with message - prompt for feedback."""

    async def handle(self, ctx: CallbackContext) -> None:
        """Prompt for feedback on chain denial.

        Target ID format: request_id
        """
        request_id = ctx.target_id
        debug_callback("ChainDenyMsgHandler called", request_id=request_id)

        request = await ctx.storage.get_request(request_id)
        if not request:
            debug_callback("Request not found", request_id=request_id)
            await ctx.notifier.answer_callback(ctx.callback_id, "Request not found")
            if ctx.message_id:
                await ctx.notifier.edit_message(ctx.message_id, "⚠️ Request expired")
            return

        # Store chain context for when feedback arrives
        prompt_msg_id = await ctx.notifier.send_feedback_prompt(request.tool_name)
        debug_callback("Sent feedback prompt", prompt_msg_id=prompt_msg_id)
        if prompt_msg_id:
            # Store with chain prefix so feedback handler knows it's a chain denial
            await ctx.storage.set_pending_feedback(prompt_msg_id, f"chain:{request_id}")
            debug_callback(
                "Stored pending_feedback",
                prompt_msg_id=prompt_msg_id,
                value=f"chain:{request_id}",
            )

        await ctx.notifier.answer_callback(ctx.callback_id, "Reply with feedback")


class ChainApproveAllHandler:
    """Approve all remaining commands in chain."""

    async def handle(self, ctx: CallbackContext) -> None:
        """Approve all remaining commands at once.

        Target ID format: request_id
        """
        request_id = ctx.target_id
        debug_chain("chain_approve_all called", request_id=request_id)

        try:
            request = await ctx.storage.get_request(request_id)
            if not request:
                await ctx.notifier.answer_callback(ctx.callback_id, "Request not found")
                if ctx.message_id:
                    await ctx.notifier.edit_message(ctx.message_id, "⚠️ Request expired")
                return

            # Skip if already resolved (handles duplicate callbacks from multiple pollers)
            if request.status != "pending":
                debug_chain(
                    "Request already resolved, skipping",
                    request_id=request_id,
                    status=request.status,
                )
                # Still answer the callback to dismiss Telegram loading state
                await ctx.notifier.answer_callback(ctx.callback_id, "Already processed")
                return

            chain_mgr = ChainStateManager(ctx.storage)
            result = await chain_mgr.get_or_init_state(request_id, request.tool_input)
            if not result:
                await ctx.notifier.answer_callback(
                    ctx.callback_id, "Failed to parse chain"
                )
                return

            chain_state, _version = result

            # Approve all at once
            await ctx.storage.resolve_request(
                request_id=request_id,
                status="approved",
                resolved_by="user:chain_approve_all",
            )
            await chain_mgr.clear_state(request_id)

            await ctx.notifier.answer_callback(ctx.callback_id, "All approved")

            if ctx.message_id:
                session = await ctx.storage.get_session(request.session_id)
                project_id = format_project_id(
                    session.project_path if session else None, request.session_id
                )
                msg = format_chain_approved_message(chain_state["commands"], project_id)
                await ctx.notifier.edit_message(ctx.message_id, msg)

            await ctx.storage.log_audit(
                event_type="response",
                session_id=request.session_id,
                details={
                    "request_id": request_id,
                    "action": "approve",
                    "resolved_by": "user:chain_approve_all",
                    "chain": True,
                    "command_count": len(chain_state["commands"]),
                },
            )
        except Exception as e:
            debug_callback(
                "Error in ChainApproveAllHandler",
                error=str(e)[:100],
                request_id=request_id,
            )
            await ctx.notifier.answer_callback(ctx.callback_id, "Error occurred")


class ChainApproveEntireHandler:
    """Approve entire chain without individual command review."""

    async def handle(self, ctx: CallbackContext) -> None:
        """Approve entire chain at once.

        Target ID format: request_id
        """
        request_id = ctx.target_id
        debug_chain("chain_approve_entire called", request_id=request_id)

        try:
            request = await ctx.storage.get_request(request_id)
            if not request:
                await ctx.notifier.answer_callback(ctx.callback_id, "Request not found")
                if ctx.message_id:
                    await ctx.notifier.edit_message(ctx.message_id, "⚠️ Request expired")
                return

            # Skip if already resolved (handles duplicate callbacks from multiple pollers)
            if request.status != "pending":
                debug_chain(
                    "Request already resolved, skipping",
                    request_id=request_id,
                    status=request.status,
                )
                # Still answer the callback to dismiss Telegram loading state
                await ctx.notifier.answer_callback(ctx.callback_id, "Already processed")
                return

            debug_chain("Getting chain state", request_id=request_id)
            chain_mgr = ChainStateManager(ctx.storage)
            result = await chain_mgr.get_or_init_state(request_id, request.tool_input)
            if not result:
                debug_chain("Failed to get chain state", request_id=request_id)
                await ctx.notifier.answer_callback(
                    ctx.callback_id, "Failed to parse chain"
                )
                return

            chain_state, _version = result
            debug_chain(
                "Got chain state",
                request_id=request_id,
                command_count=len(chain_state.get("commands", [])),
            )

            # Approve entire chain
            debug_chain("Resolving chain request", request_id=request_id)
            await ctx.storage.resolve_request(
                request_id=request_id,
                status="approved",
                resolved_by="user:chain_entire",
            )
            debug_chain("Chain request resolved", request_id=request_id)
            await chain_mgr.clear_state(request_id)

            debug_chain("Answering callback", request_id=request_id)
            await ctx.notifier.answer_callback(ctx.callback_id, "Chain approved")
            debug_chain("Callback answered", request_id=request_id)

            debug_chain(
                "Editing chain message",
                request_id=request_id,
                msg_id=ctx.message_id,
            )
            if ctx.message_id:
                session = await ctx.storage.get_session(request.session_id)
                project_id = format_project_id(
                    session.project_path if session else None, request.session_id
                )
                msg = format_chain_approved_message(chain_state["commands"], project_id)
                await ctx.notifier.edit_message(ctx.message_id, msg)
                debug_chain("Chain message edited", request_id=request_id)
            else:
                debug_chain("No message_id for chain!", request_id=request_id)

            await ctx.storage.log_audit(
                event_type="response",
                session_id=request.session_id,
                details={
                    "request_id": request_id,
                    "action": "approve",
                    "resolved_by": "user:chain_entire",
                    "chain": True,
                    "command_count": len(chain_state["commands"]),
                },
            )
        except Exception as e:
            debug_callback(
                "Error in ChainApproveEntireHandler",
                error=str(e)[:100],
                request_id=request_id,
            )
            await ctx.notifier.answer_callback(ctx.callback_id, "Error occurred")


class ChainCancelRuleHandler:
    """Cancel rule selection for chain command."""

    async def handle(self, ctx: CallbackContext) -> None:
        """Cancel rule selection and restore chain progress.

        Target ID format: request_id:command_index
        """
        parts = ctx.target_id.rsplit(":", 1)
        if len(parts) != 2:
            await ctx.notifier.answer_callback(ctx.callback_id, "Invalid format")
            return

        request_id = parts[0]
        try:
            command_idx = int(parts[1])
        except ValueError:
            await ctx.notifier.answer_callback(ctx.callback_id, "Invalid index")
            return

        debug_chain(
            "chain_cancel_rule called", request_id=request_id, command_idx=command_idx
        )

        request = await ctx.storage.get_request(request_id)
        if not request:
            await ctx.notifier.answer_callback(ctx.callback_id, "Request not found")
            if ctx.message_id:
                await ctx.notifier.edit_message(ctx.message_id, "⚠️ Request expired")
            return

        await ctx.notifier.answer_callback(ctx.callback_id, "Cancelled")

        # Restore chain progress view
        if ctx.message_id:
            chain_mgr = ChainStateManager(ctx.storage)
            result = await chain_mgr.get_or_init_state(request_id, request.tool_input)
            if result:
                chain_state, _version = result
                session = await ctx.storage.get_session(request.session_id)
                await ctx.notifier.update_chain_progress(
                    message_id=ctx.message_id,
                    request_id=request_id,
                    session_id=request.session_id,
                    commands=chain_state["commands"],
                    current_idx=command_idx,
                    approved_indices=chain_state.get("approved_indices", []),
                    project_path=session.project_path if session else None,
                )


class ChainRuleHandler:
    """Show rule pattern options for a chain command."""

    async def handle(self, ctx: CallbackContext) -> None:
        """Show rule patterns for a specific chain command.

        Target ID format: request_id:command_index
        """
        from pyafk.utils.pattern_generator import generate_rule_patterns

        parts = ctx.target_id.rsplit(":", 1)
        if len(parts) != 2:
            await ctx.notifier.answer_callback(ctx.callback_id, "Invalid format")
            return

        request_id = parts[0]
        try:
            command_idx = int(parts[1])
        except ValueError:
            await ctx.notifier.answer_callback(ctx.callback_id, "Invalid index")
            return

        debug_chain("chain_rule called", request_id=request_id, command_idx=command_idx)

        request = await ctx.storage.get_request(request_id)
        if not request:
            await ctx.notifier.answer_callback(ctx.callback_id, "Request not found")
            if ctx.message_id:
                await ctx.notifier.edit_message(ctx.message_id, "⚠️ Request expired")
            return

        # Get chain state
        chain_mgr = ChainStateManager(ctx.storage)
        result = await chain_mgr.get_or_init_state(request_id, request.tool_input)
        if not result:
            await ctx.notifier.answer_callback(ctx.callback_id, "Failed to parse chain")
            return

        chain_state, version = result

        # Save state if newly initialized
        if version == 0:
            await chain_mgr.save_state(request_id, chain_state, 0)

        if command_idx >= len(chain_state["commands"]):
            await ctx.notifier.answer_callback(ctx.callback_id, "Invalid command index")
            return

        # Get the specific command and generate patterns
        cmd = chain_state["commands"][command_idx]
        tool_input = json.dumps({"command": cmd})
        patterns = generate_rule_patterns("Bash", tool_input)

        await ctx.notifier.answer_callback(ctx.callback_id, "Choose pattern")

        # Show rule pattern keyboard
        if ctx.message_id:
            await ctx.notifier.edit_message_with_rule_keyboard(
                ctx.message_id,
                f"Command {command_idx + 1}: <code>{escape_html(truncate_command(cmd))}</code>",
                request_id,
                patterns,
                callback_prefix=f"chain_rule_pattern:{request_id}:{command_idx}",
                cancel_callback=f"chain_cancel_rule:{request_id}:{command_idx}",
            )


class ChainRulePatternHandler:
    """Handle rule pattern selection for a chain command."""

    async def handle(self, ctx: CallbackContext) -> None:
        """Create rule from selected pattern for chain command.

        Target ID format: request_id:command_index:pattern_index
        """
        from pyafk.utils.pattern_generator import generate_rule_patterns

        parts = ctx.target_id.split(":")
        if len(parts) < 3:
            await ctx.notifier.answer_callback(ctx.callback_id, "Invalid format")
            return

        request_id = parts[0]
        try:
            command_idx = int(parts[1])
            pattern_idx = int(parts[2])
        except ValueError:
            await ctx.notifier.answer_callback(ctx.callback_id, "Invalid index")
            return

        debug_chain(
            "chain_rule_pattern called",
            request_id=request_id,
            command_idx=command_idx,
            pattern_idx=pattern_idx,
        )

        try:
            request = await ctx.storage.get_request(request_id)
            if not request:
                await ctx.notifier.answer_callback(ctx.callback_id, "Request not found")
                if ctx.message_id:
                    await ctx.notifier.edit_message(ctx.message_id, "⚠️ Request expired")
                return

            # Get chain state
            chain_mgr = ChainStateManager(ctx.storage)
            result = await chain_mgr.get_state(request_id)
            if not result:
                await ctx.notifier.answer_callback(
                    ctx.callback_id, "Chain state not found"
                )
                return

            chain_state, version = result
            if command_idx >= len(chain_state["commands"]):
                await ctx.notifier.answer_callback(ctx.callback_id, "Invalid command")
                return

            # Get the specific command and generate patterns
            cmd = chain_state["commands"][command_idx]
            tool_input = json.dumps({"command": cmd})
            patterns = generate_rule_patterns("Bash", tool_input)

            if pattern_idx >= len(patterns):
                await ctx.notifier.answer_callback(ctx.callback_id, "Invalid pattern")
                return

            pattern, label = patterns[pattern_idx]

            # Add the rule
            from pyafk.core.rules import RulesEngine

            engine = RulesEngine(ctx.storage)
            await engine.add_rule(
                pattern, "approve", priority=0, created_via="telegram"
            )

            # Mark this command as approved
            if command_idx not in chain_state["approved_indices"]:
                chain_state["approved_indices"].append(command_idx)

            # Check if the new rule also matches other commands
            auto_approved = []
            for idx, other_cmd in enumerate(chain_state["commands"]):
                if idx in chain_state["approved_indices"]:
                    continue

                other_input = json.dumps({"command": other_cmd})
                rule_result = await engine.check("Bash", other_input)
                if rule_result == "approve":
                    chain_state["approved_indices"].append(idx)
                    auto_approved.append(idx)

            # Save with optimistic locking
            if not await chain_mgr.save_state(request_id, chain_state, version):
                # Conflict - retry once
                result = await chain_mgr.get_state(request_id)
                if result:
                    chain_state, version = result
                    if command_idx not in chain_state["approved_indices"]:
                        chain_state["approved_indices"].append(command_idx)
                    # Re-check auto-approvals
                    auto_approved = []
                    for idx, other_cmd in enumerate(chain_state["commands"]):
                        if idx in chain_state["approved_indices"]:
                            continue
                        other_input = json.dumps({"command": other_cmd})
                        rule_result = await engine.check("Bash", other_input)
                        if rule_result == "approve":
                            chain_state["approved_indices"].append(idx)
                            auto_approved.append(idx)
                    await chain_mgr.save_state(request_id, chain_state, version)

            if auto_approved:
                await ctx.notifier.answer_callback(
                    ctx.callback_id,
                    f"Always rule added (+{len(auto_approved)} auto-approved)",
                )
            else:
                await ctx.notifier.answer_callback(ctx.callback_id, "Always rule added")

            # Update UI
            if ctx.message_id:
                session = await ctx.storage.get_session(request.session_id)

                # Check if all commands are approved
                if len(chain_state["approved_indices"]) >= len(chain_state["commands"]):
                    await ctx.storage.resolve_request(
                        request_id=request_id,
                        status="approved",
                        resolved_by="chain_all_approved",
                    )
                    await chain_mgr.clear_state(request_id)

                    await ctx.storage.log_audit(
                        event_type="chain_approved",
                        session_id=request.session_id,
                        details={
                            "request_id": request_id,
                            "commands": chain_state["commands"],
                            "method": "all_commands_approved",
                        },
                    )

                    project_id = format_project_id(
                        session.project_path if session else None, request.session_id
                    )
                    msg = format_chain_approved_message(
                        chain_state["commands"], project_id
                    )
                    await ctx.notifier.edit_message(ctx.message_id, msg)
                else:
                    # Find first unapproved command
                    next_idx = 0
                    while (
                        next_idx < len(chain_state["commands"])
                        and next_idx in chain_state["approved_indices"]
                    ):
                        next_idx += 1

                    if next_idx < len(chain_state["commands"]):
                        await ctx.notifier.update_chain_progress(
                            message_id=ctx.message_id,
                            request_id=request_id,
                            session_id=request.session_id,
                            commands=chain_state["commands"],
                            current_idx=next_idx,
                            approved_indices=chain_state["approved_indices"],
                            project_path=session.project_path if session else None,
                        )
        except Exception as e:
            debug_callback(
                "Error in ChainRulePatternHandler",
                error=str(e)[:100],
                request_id=request_id,
            )
            await ctx.notifier.answer_callback(ctx.callback_id, "Error occurred")


async def check_chain_rules(storage: "Storage", cmd: str) -> Optional[str]:
    """Check if a bash command chain matches any rules.

    Args:
        storage: Storage instance for rule lookups
        cmd: The bash command (may contain && || ; chains)

    Returns:
        "approve" if ALL commands match allow rules
        "deny" if ANY command matches deny rule
        None if manual approval needed
    """
    from pyafk.core.rules import RulesEngine

    parser = CommandParser()
    nodes = parser.parse(cmd)

    engine = RulesEngine(storage)
    has_unmatched = False

    for node in nodes:
        patterns = parser.generate_patterns(node)

        matched = False
        for pattern in patterns:
            rule_result = await engine.check("Bash", json.dumps({"command": pattern}))

            if rule_result == "deny":
                return "deny"
            elif rule_result == "approve":
                matched = True
                break

        if not matched:
            has_unmatched = True

    if not has_unmatched:
        return "approve"

    return None
