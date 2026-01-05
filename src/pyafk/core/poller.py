"""Telegram poller with file-based locking."""

import asyncio
import fcntl
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

from pyafk.core.command_parser import CommandParser
from pyafk.core.storage import Storage
from pyafk.notifiers.telegram import TelegramNotifier
from pyafk.utils.debug import debug_callback, debug_chain, debug_rule


class PollLock:
    """File-based lock for single poller."""

    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self._fd: Optional[int] = None

    async def acquire(self, timeout: float = 5.0) -> bool:
        """Try to acquire the lock.

        Returns True if acquired, False if timeout.
        """
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

        start = time.monotonic()
        while True:
            try:
                self._fd = os.open(
                    str(self.lock_path),
                    os.O_CREAT | os.O_RDWR,
                )
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                os.ftruncate(self._fd, 0)
                os.write(self._fd, str(os.getpid()).encode())
                return True
            except (BlockingIOError, OSError):
                if self._fd is not None:
                    try:
                        os.close(self._fd)
                    except OSError:
                        pass
                    self._fd = None

                elapsed = time.monotonic() - start
                if elapsed >= timeout:
                    return False

                await asyncio.sleep(0.1)

    async def release(self):
        """Release the lock."""
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

            try:
                self.lock_path.unlink()
            except OSError:
                pass


class Poller:
    """Poll Telegram for callback responses."""

    def __init__(
        self,
        storage: Storage,
        notifier: TelegramNotifier,
        pyafk_dir: Path,
    ):
        self.storage = storage
        self.notifier = notifier
        self.lock = PollLock(pyafk_dir / "poll.lock")
        self._offset_file = pyafk_dir / "telegram_offset"
        self._offset: Optional[int] = self._load_offset()
        self._running = False

    def _load_offset(self) -> Optional[int]:
        """Load persisted Telegram update offset."""
        try:
            if self._offset_file.exists():
                return int(self._offset_file.read_text().strip())
        except (ValueError, OSError):
            pass
        return None

    def _save_offset(self, offset: int):
        """Persist Telegram update offset."""
        try:
            self._offset_file.write_text(str(offset))
        except OSError:
            pass

    async def process_updates_once(self) -> int:
        """Process one batch of updates.

        Returns number of updates processed.
        """
        # If no saved offset, skip all old updates to avoid processing stale callbacks
        if self._offset is None:
            updates = await self.notifier.get_updates(offset=None, timeout=0)
            if updates:
                # Set offset to skip all old updates
                self._offset = updates[-1]["update_id"] + 1
                self._save_offset(self._offset)
            return 0

        updates = await self.notifier.get_updates(
            offset=self._offset,
            timeout=1,
        )

        processed = 0
        for update in updates:
            self._offset = update["update_id"] + 1
            self._save_offset(self._offset)

            if "callback_query" in update:
                await self._handle_callback(update["callback_query"])
                processed += 1
            elif "message" in update:
                # Check if this is a reply to a feedback prompt
                await self._handle_message(update["message"])
                processed += 1

        return processed

    async def _handle_message(self, message: dict):
        """Handle a text message - check if it's feedback for a denial or subagent."""
        reply_to = message.get("reply_to_message", {})
        reply_msg_id = reply_to.get("message_id")
        debug_callback(f"_handle_message called", reply_msg_id=reply_msg_id, has_text=bool(message.get("text")))
        if not reply_msg_id:
            debug_callback(f"No reply_to_message, ignoring")
            return

        # Check if this is a reply to a feedback prompt we sent
        request_id = await self.storage.get_pending_feedback(reply_msg_id)
        debug_callback(f"Looked up pending_feedback", reply_msg_id=reply_msg_id, request_id=request_id)
        if not request_id:
            return

        feedback = message.get("text", "")

        # Check if this is for a subagent or chain denial
        if request_id.startswith("subagent:"):
            subagent_id = request_id[9:]  # Strip "subagent:" prefix
            await self._handle_subagent_feedback(subagent_id, feedback, reply_msg_id)
        elif request_id.startswith("chain:"):
            chain_request_id = request_id[6:]  # Strip "chain:" prefix
            await self._handle_chain_deny_with_feedback(chain_request_id, feedback, reply_msg_id)
        else:
            await self._handle_deny_with_feedback(request_id, feedback, reply_msg_id)

    async def _handle_subagent_feedback(
        self,
        subagent_id: str,
        instructions: str,
        prompt_msg_id: int,
    ):
        """Handle subagent continue instructions."""
        # Clear the pending feedback entry
        await self.storage.clear_pending_feedback(prompt_msg_id)

        # Resolve the subagent with continue status and instructions
        await self.storage.resolve_subagent(subagent_id, "continue", instructions)

    async def _handle_callback(self, callback: dict):
        """Handle a callback query from inline button."""
        callback_id = callback["id"]
        data = callback.get("data", "")
        # Get message_id from callback for editing
        message_id = callback.get("message", {}).get("message_id")

        debug_callback(f"Received callback", data=data, message_id=message_id)

        if ":" not in data:
            return

        action, target_id = data.split(":", 1)
        debug_callback(f"Parsed callback", action=action, target_id=target_id)

        if action in ("approve", "deny"):
            await self._handle_approval(target_id, action, callback_id, message_id)
        elif action == "deny_msg":
            await self._handle_deny_msg(target_id, callback_id, message_id)
        elif action == "approve_all":
            # Format: approve_all:session_id:tool_name
            parts = target_id.split(":", 1)
            session_id = parts[0]
            tool_name = parts[1] if len(parts) > 1 else None
            await self._handle_approve_all(session_id, tool_name, callback_id)
        elif action == "add_rule":
            # Get original message text for inline edit
            original_text = callback.get("message", {}).get("text", "")
            await self._handle_add_rule_menu(target_id, callback_id, message_id, original_text)
        elif action == "cancel_rule":
            await self._handle_cancel_rule(target_id, callback_id, message_id)
        elif action == "add_rule_pattern":
            # Format: add_rule_pattern:request_id:pattern_index
            parts = target_id.split(":", 1)
            request_id = parts[0]
            pattern_idx = int(parts[1]) if len(parts) > 1 else 0
            await self._handle_add_rule(request_id, callback_id, message_id, pattern_idx)
        elif action == "chain_rule_pattern":
            # Format: chain_rule_pattern:request_id:command_idx:pattern_index
            parts = target_id.split(":")
            if len(parts) >= 3:
                request_id = parts[0]
                command_idx = int(parts[1])
                pattern_idx = int(parts[2]) if len(parts) > 2 else 0
                await self._handle_chain_rule_pattern(request_id, command_idx, pattern_idx, callback_id, message_id)
        elif action == "subagent_ok":
            await self._handle_subagent_ok(target_id, callback_id, message_id)
        elif action == "subagent_continue":
            await self._handle_subagent_continue(target_id, callback_id, message_id)
        elif action == "chain_approve":
            # Format: chain_approve:request_id:command_index
            parts = target_id.split(":", 1)
            request_id = parts[0]
            command_idx = int(parts[1]) if len(parts) > 1 else 0
            await self._handle_chain_approve(request_id, command_idx, callback_id, message_id)
        elif action == "chain_deny":
            await self._handle_chain_deny(target_id, callback_id, message_id)
        elif action == "chain_deny_msg":
            await self._handle_chain_deny_msg(target_id, callback_id, message_id)
        elif action == "chain_rule":
            # Format: chain_rule:request_id:command_index
            parts = target_id.split(":", 1)
            request_id = parts[0]
            command_idx = int(parts[1]) if len(parts) > 1 else 0
            await self._handle_chain_rule(request_id, command_idx, callback_id, message_id)
        elif action == "chain_approve_all":
            await self._handle_chain_approve_all(target_id, callback_id, message_id)

    async def _handle_approval(
        self,
        request_id: str,
        action: str,
        callback_id: str,
        message_id: Optional[int] = None,
    ):
        """Handle approve/deny callback."""
        debug_callback(f"_handle_approval called", request_id=request_id, action=action)
        request = await self.storage.get_request(request_id)
        if not request:
            debug_callback(f"Request not found", request_id=request_id)
            await self.notifier.answer_callback(callback_id, "Request not found")
            if message_id:
                await self.notifier.edit_message(message_id, "⚠️ Request expired")
            return
        debug_callback(f"Found request", id=request.id, status=request.status)

        status = "approved" if action == "approve" else "denied"

        await self.storage.resolve_request(
            request_id=request_id,
            status=status,
            resolved_by="user",
        )

        await self.notifier.answer_callback(
            callback_id,
            f"{'Approved' if action == 'approve' else 'Denied'}",
        )

        # Use message_id from callback (the message user clicked) or fall back to stored id
        msg_id = message_id or request.telegram_msg_id
        if msg_id:
            # Format: [project] tool_summary ✅/❌
            session = await self.storage.get_session(request.session_id)
            project_id = self._format_project_id(session.project_path if session else None, request.session_id)
            tool_summary = self._format_tool_summary(request.tool_name, request.tool_input)
            emoji = "✅" if action == "approve" else "❌"
            await self.notifier.edit_message(
                msg_id,
                f"<i>{project_id}</i>\n{emoji} <b>[{request.tool_name}]</b> <code>{tool_summary}</code>",
            )

        await self.storage.log_audit(
            event_type="response",
            session_id=request.session_id,
            details={
                "request_id": request_id,
                "action": action,
                "resolved_by": "user",
            },
        )

    async def _handle_deny_msg(
        self,
        request_id: str,
        callback_id: str,
        message_id: Optional[int] = None,
    ):
        """Handle deny with message button - prompt for feedback."""
        request = await self.storage.get_request(request_id)
        if not request:
            await self.notifier.answer_callback(callback_id, "Request not found")
            if message_id:
                await self.notifier.edit_message(message_id, "⚠️ Request expired")
            return

        # Send feedback prompt
        prompt_msg_id = await self.notifier.send_feedback_prompt(request.tool_name)
        if prompt_msg_id:
            await self.storage.set_pending_feedback(prompt_msg_id, request_id)

        await self.notifier.answer_callback(callback_id, "Reply with feedback")

    async def _handle_deny_with_feedback(
        self,
        request_id: str,
        feedback: str,
        prompt_msg_id: int,
    ):
        """Handle denial with user feedback."""
        request = await self.storage.get_request(request_id)
        if not request:
            return

        # Clear the pending feedback entry
        await self.storage.clear_pending_feedback(prompt_msg_id)

        # Resolve the request with denial reason
        await self.storage.resolve_request(
            request_id=request_id,
            status="denied",
            resolved_by="user:feedback",
            denial_reason=feedback,
        )

        # Update the original message
        if request.telegram_msg_id:
            await self.notifier.edit_message(
                request.telegram_msg_id,
                f"❌ DENIED - {request.tool_name}\n💬 {feedback}",
            )

        await self.storage.log_audit(
            event_type="response",
            session_id=request.session_id,
            details={
                "request_id": request_id,
                "action": "deny",
                "resolved_by": "user:feedback",
                "feedback": feedback,
            },
        )

    async def _handle_approve_all(self, session_id: str, tool_name: Optional[str], callback_id: str):
        """Approve all pending requests for a session and tool type."""
        pending = await self.storage.get_pending_requests()

        # Filter by session and tool type
        to_approve = [
            r for r in pending
            if r.session_id == session_id and (tool_name is None or r.tool_name == tool_name)
        ]

        for request in to_approve:
            await self.storage.resolve_request(
                request_id=request.id,
                status="approved",
                resolved_by="user:approve_all",
            )
            # Update the Telegram message
            if request.telegram_msg_id:
                await self.notifier.edit_message(
                    request.telegram_msg_id,
                    f"✅ APPROVED (all) - {request.tool_name}",
                )

        tool_label = tool_name or "all"
        await self.notifier.answer_callback(
            callback_id,
            f"Approved {len(to_approve)} {tool_label}",
        )

    async def _handle_cancel_rule(
        self,
        request_id: str,
        callback_id: str,
        message_id: Optional[int] = None,
    ):
        """Cancel rule selection and restore original keyboard."""
        request = await self.storage.get_request(request_id)
        if not request:
            await self.notifier.answer_callback(callback_id, "Request not found")
            if message_id:
                await self.notifier.edit_message(message_id, "⚠️ Request expired")
            return

        await self.notifier.answer_callback(callback_id, "Cancelled")

        # Restore original message with approval keyboard
        if message_id:
            await self.notifier.restore_approval_keyboard(
                message_id, request_id, request.session_id, request.tool_name, request.tool_input
            )

    async def _handle_add_rule_menu(
        self,
        request_id: str,
        callback_id: str,
        message_id: Optional[int] = None,
        original_text: str = "",
    ):
        """Show rule pattern options menu inline."""
        request = await self.storage.get_request(request_id)
        if not request:
            await self.notifier.answer_callback(callback_id, "Request not found")
            if message_id:
                await self.notifier.edit_message(message_id, "⚠️ Request expired")
            return

        # Generate pattern options
        patterns = self._generate_rule_patterns(request.tool_name, request.tool_input)

        await self.notifier.answer_callback(callback_id, "Choose pattern")

        # Edit message inline with pattern options
        if message_id:
            # Strip any previous rule prompt text for clean display
            base_text = original_text.split("\n\n📝")[0] if "\n\n📝" in original_text else original_text
            await self.notifier.edit_message_with_rule_keyboard(
                message_id, base_text, request_id, patterns
            )

    async def _handle_add_rule(self, request_id: str, callback_id: str, message_id: Optional[int] = None, pattern_idx: int = 0):
        """Handle add rule selection - creates auto-approve rule and approves request."""
        request = await self.storage.get_request(request_id)
        if not request:
            await self.notifier.answer_callback(callback_id, "Request not found")
            if message_id:
                await self.notifier.edit_message(message_id, "⚠️ Request expired")
            return

        # Get the selected pattern (tuple of pattern, label)
        patterns = self._generate_rule_patterns(request.tool_name, request.tool_input)
        pattern, label = patterns[pattern_idx] if pattern_idx < len(patterns) else patterns[0]

        # Add the rule
        from pyafk.core.rules import RulesEngine
        engine = RulesEngine(self.storage)
        await engine.add_rule(pattern, "approve", priority=0, created_via="telegram")

        # Also approve this request
        await self.storage.resolve_request(
            request_id=request_id,
            status="approved",
            resolved_by="user:add_rule",
        )

        # Update the message (same as original since we're inline now)
        if message_id:
            session = await self.storage.get_session(request.session_id)
            project_id = self._format_project_id(session.project_path if session else None, request.session_id)
            tool_summary = self._format_tool_summary(request.tool_name, request.tool_input)
            await self.notifier.edit_message(
                message_id,
                f"<i>{project_id}</i>\n✅ <b>[{request.tool_name}]</b> <code>{tool_summary}</code>\n📝 Rule: {label}",
            )

        await self.notifier.answer_callback(
            callback_id,
            f"Rule added",
        )

    async def _handle_subagent_ok(
        self,
        subagent_id: str,
        callback_id: str,
        message_id: Optional[int] = None,
    ):
        """Handle subagent OK button - let subagent stop normally."""
        await self.storage.resolve_subagent(subagent_id, "ok")

        await self.notifier.answer_callback(callback_id, "OK")

        if message_id:
            await self.notifier.edit_message(
                message_id,
                "✅ Subagent finished",
            )

    async def _handle_subagent_continue(
        self,
        subagent_id: str,
        callback_id: str,
        message_id: Optional[int] = None,
    ):
        """Handle subagent Continue button - prompt for instructions."""
        await self.notifier.answer_callback(callback_id, "Reply with instructions")

        # Send continue prompt
        prompt_msg_id = await self.notifier.send_continue_prompt()
        if prompt_msg_id:
            await self.storage.set_subagent_continue_prompt(subagent_id, prompt_msg_id)

    async def _handle_chain_approve(
        self,
        request_id: str,
        command_idx: int,
        callback_id: str,
        message_id: Optional[int] = None,
    ):
        """Handle chain approval for one command."""
        debug_chain(f"chain_approve called", request_id=request_id, command_idx=command_idx)
        request = await self.storage.get_request(request_id)
        if not request:
            debug_chain(f"Request not found", request_id=request_id)
            await self.notifier.answer_callback(callback_id, "Request not found")
            if message_id:
                await self.notifier.edit_message(message_id, "⚠️ Request expired")
            return

        # Get chain state from pending_feedback (stored as JSON)
        chain_state = await self._get_chain_state(request_id)
        debug_chain(f"Got chain state", chain_state=chain_state)
        if not chain_state:
            # Initialize chain state from tool_input
            import json
            try:
                data = json.loads(request.tool_input)
                cmd = data.get("command", "")
                # Parse commands from the bash chain using split_chain
                parser = CommandParser()
                commands = parser.split_chain(cmd)
                chain_state = {
                    "commands": commands,
                    "approved_indices": [],
                }
            except Exception:
                await self.notifier.answer_callback(callback_id, "Failed to parse chain")
                return

        # Mark this command as approved
        if command_idx not in chain_state["approved_indices"]:
            chain_state["approved_indices"].append(command_idx)
            debug_chain(f"Added command to approved", command_idx=command_idx, approved=chain_state["approved_indices"])

        # Save updated state
        await self._save_chain_state(request_id, chain_state)
        debug_chain(f"Saved chain state", approved_count=len(chain_state["approved_indices"]), total=len(chain_state["commands"]))

        await self.notifier.answer_callback(callback_id, "Approved")

        # Check if all commands are approved
        if len(chain_state["approved_indices"]) >= len(chain_state["commands"]):
            debug_chain(f"All commands approved, showing final button")
            # All approved - show final approval button
            if message_id:
                session = await self.storage.get_session(request.session_id)
                await self.notifier.update_chain_progress(
                    message_id=message_id,
                    request_id=request_id,
                    session_id=request.session_id,
                    commands=chain_state["commands"],
                    current_idx=len(chain_state["commands"]) - 1,
                    approved_indices=chain_state["approved_indices"],
                    project_path=session.project_path if session else None,
                    final_approve=True,
                )
        else:
            # Find first unapproved command (start from 0, not command_idx + 1)
            next_idx = 0
            while next_idx < len(chain_state["commands"]) and next_idx in chain_state["approved_indices"]:
                next_idx += 1

            debug_chain(f"Moving to next command", next_idx=next_idx, approved_indices=chain_state["approved_indices"])

            if message_id and next_idx < len(chain_state["commands"]):
                session = await self.storage.get_session(request.session_id)
                await self.notifier.update_chain_progress(
                    message_id=message_id,
                    request_id=request_id,
                    session_id=request.session_id,
                    commands=chain_state["commands"],
                    current_idx=next_idx,
                    approved_indices=chain_state["approved_indices"],
                    project_path=session.project_path if session else None,
                )

    async def _handle_chain_deny(
        self,
        request_id: str,
        callback_id: str,
        message_id: Optional[int] = None,
    ):
        """Handle chain denial."""
        request = await self.storage.get_request(request_id)
        if not request:
            await self.notifier.answer_callback(callback_id, "Request not found")
            if message_id:
                await self.notifier.edit_message(message_id, "⚠️ Request expired")
            return

        # Resolve the request as denied
        await self.storage.resolve_request(
            request_id=request_id,
            status="denied",
            resolved_by="user",
        )

        # Clear chain state
        await self._clear_chain_state(request_id)

        await self.notifier.answer_callback(callback_id, "Denied")

        # Update message to show denial
        if message_id:
            chain_state = await self._get_chain_state(request_id)
            if chain_state:
                session = await self.storage.get_session(request.session_id)
                await self.notifier.update_chain_progress(
                    message_id=message_id,
                    request_id=request_id,
                    session_id=request.session_id,
                    commands=chain_state["commands"],
                    current_idx=0,
                    approved_indices=chain_state["approved_indices"],
                    project_path=session.project_path if session else None,
                    denied=True,
                )
            else:
                await self.notifier.edit_message(message_id, "❌ Chain denied")

        await self.storage.log_audit(
            event_type="response",
            session_id=request.session_id,
            details={
                "request_id": request_id,
                "action": "deny",
                "resolved_by": "user",
                "chain": True,
            },
        )

    async def _handle_chain_deny_msg(
        self,
        request_id: str,
        callback_id: str,
        message_id: Optional[int] = None,
    ):
        """Handle chain deny with message - prompt for feedback."""
        debug_callback(f"_handle_chain_deny_msg called", request_id=request_id)
        request = await self.storage.get_request(request_id)
        if not request:
            debug_callback(f"Request not found", request_id=request_id)
            await self.notifier.answer_callback(callback_id, "Request not found")
            if message_id:
                await self.notifier.edit_message(message_id, "⚠️ Request expired")
            return

        # Store the chain context for when feedback arrives
        prompt_msg_id = await self.notifier.send_feedback_prompt(request.tool_name)
        debug_callback(f"Sent feedback prompt", prompt_msg_id=prompt_msg_id)
        if prompt_msg_id:
            # Store with chain prefix so feedback handler knows it's a chain denial
            await self.storage.set_pending_feedback(prompt_msg_id, f"chain:{request_id}")
            debug_callback(f"Stored pending_feedback", prompt_msg_id=prompt_msg_id, value=f"chain:{request_id}")

        await self.notifier.answer_callback(callback_id, "Reply with feedback")

    async def _handle_chain_deny_with_feedback(
        self,
        request_id: str,
        feedback: str,
        prompt_msg_id: int,
    ):
        """Handle chain denial with user feedback."""
        debug_callback(f"_handle_chain_deny_with_feedback called", request_id=request_id, feedback=feedback[:50])
        request = await self.storage.get_request(request_id)
        if not request:
            debug_callback(f"Request not found", request_id=request_id)
            return

        # Clear the pending feedback entry
        await self.storage.clear_pending_feedback(prompt_msg_id)

        # Resolve the request with denial reason
        await self.storage.resolve_request(
            request_id=request_id,
            status="denied",
            resolved_by="user",
            reason=feedback,
        )

        # Clear chain state
        await self._clear_chain_state(request_id)

        # Delete the feedback prompt message
        await self.notifier.delete_message(prompt_msg_id)

        # Update the original approval message
        if request.telegram_msg_id:
            session = await self.storage.get_session(request.session_id)
            project_id = self._format_project_id(session.project_path if session else None, request.session_id)
            tool_summary = self._format_tool_summary(request.tool_name, request.tool_input)
            await self.notifier.edit_message(
                request.telegram_msg_id,
                f"<i>{project_id}</i>\n❌ <b>[{request.tool_name}]</b> <code>{tool_summary}</code>\n\n💬 {feedback}",
            )

        await self.storage.log_audit(
            event_type="response",
            session_id=request.session_id,
            details={
                "request_id": request_id,
                "action": "deny",
                "resolved_by": "user",
                "feedback": feedback,
                "chain": True,
            },
        )

    async def _handle_chain_rule(
        self,
        request_id: str,
        command_idx: int,
        callback_id: str,
        message_id: Optional[int] = None,
    ):
        """Handle chain rule creation for one command."""
        debug_rule(f"chain_rule called", request_id=request_id, command_idx=command_idx)
        request = await self.storage.get_request(request_id)
        if not request:
            debug_rule(f"Request not found", request_id=request_id)
            await self.notifier.answer_callback(callback_id, "Request not found")
            if message_id:
                await self.notifier.edit_message(message_id, "⚠️ Request expired")
            return

        # Get chain state - initialize if not present
        chain_state = await self._get_chain_state(request_id)
        debug_rule(f"Got chain state", chain_state=chain_state)
        if not chain_state:
            # Initialize chain state from tool_input
            try:
                data = json.loads(request.tool_input)
                cmd = data.get("command", "")
                # Parse commands from the bash chain using split_chain
                parser = CommandParser()
                commands = parser.split_chain(cmd)
                chain_state = {
                    "commands": commands,
                    "approved_indices": [],
                }
                await self._save_chain_state(request_id, chain_state)
            except Exception:
                await self.notifier.answer_callback(callback_id, "Failed to parse chain")
                return

        if command_idx >= len(chain_state["commands"]):
            await self.notifier.answer_callback(callback_id, "Invalid command index")
            return

        # Get the specific command
        cmd = chain_state["commands"][command_idx]

        # Generate patterns for this command
        tool_input = json.dumps({"command": cmd})
        patterns = self._generate_rule_patterns("Bash", tool_input)

        await self.notifier.answer_callback(callback_id, "Choose pattern")

        # Show rule pattern keyboard for this command
        # Note: We encode command_idx in the callback data for the rule pattern
        if message_id:
            await self.notifier.edit_message_with_rule_keyboard(
                message_id,
                f"Command {command_idx + 1}: <code>{cmd[:60]}</code>",
                request_id,
                patterns,
                callback_prefix=f"chain_rule_pattern:{request_id}:{command_idx}",
                cancel_callback=f"chain_approve:{request_id}:{command_idx}",
            )

    async def _handle_chain_rule_pattern(
        self,
        request_id: str,
        command_idx: int,
        pattern_idx: int,
        callback_id: str,
        message_id: Optional[int] = None,
    ):
        """Handle rule pattern selection for a chain command."""
        debug_rule(f"chain_rule_pattern called", request_id=request_id, command_idx=command_idx, pattern_idx=pattern_idx)
        request = await self.storage.get_request(request_id)
        if not request:
            debug_rule(f"Request not found", request_id=request_id)
            await self.notifier.answer_callback(callback_id, "Request not found")
            if message_id:
                await self.notifier.edit_message(message_id, "⚠️ Request expired")
            return

        # Get chain state
        chain_state = await self._get_chain_state(request_id)
        debug_rule(f"Got chain state", chain_state=chain_state)
        if not chain_state or command_idx >= len(chain_state["commands"]):
            debug_rule(f"Invalid command", command_idx=command_idx, chain_state=chain_state)
            await self.notifier.answer_callback(callback_id, "Invalid command")
            return

        # Get the specific command and generate patterns
        cmd = chain_state["commands"][command_idx]
        tool_input = json.dumps({"command": cmd})
        patterns = self._generate_rule_patterns("Bash", tool_input)
        debug_rule(f"Generated patterns", cmd=cmd[:50], pattern_count=len(patterns))

        if pattern_idx >= len(patterns):
            await self.notifier.answer_callback(callback_id, "Invalid pattern")
            return

        pattern, label = patterns[pattern_idx]
        debug_rule(f"Selected pattern", pattern=pattern, label=label)

        # Add the rule
        from pyafk.core.rules import RulesEngine
        engine = RulesEngine(self.storage)
        await engine.add_rule(pattern, "approve", priority=0, created_via="telegram")

        # Also mark this command as approved in the chain
        if command_idx not in chain_state["approved_indices"]:
            chain_state["approved_indices"].append(command_idx)
            debug_rule(f"Marked command approved", command_idx=command_idx, approved=chain_state["approved_indices"])
        await self._save_chain_state(request_id, chain_state)

        await self.notifier.answer_callback(callback_id, "Rule added")

        # Update UI to show progress
        if message_id:
            session = await self.storage.get_session(request.session_id)

            # Check if all commands are approved
            if len(chain_state["approved_indices"]) >= len(chain_state["commands"]):
                # All approved - auto-approve the entire chain instead of showing button
                await self.storage.resolve_request(
                    request_id=request_id,
                    status="approved",
                    resolved_by="chain_all_approved",
                )
                await self._clear_chain_state(request_id)

                await self.storage.log_audit(
                    event_type="chain_approved",
                    session_id=request.session_id,
                    details={
                        "request_id": request_id,
                        "commands": chain_state["commands"],
                        "method": "all_commands_approved",
                    },
                )

                # Update message to show all approved
                await self.notifier.update_chain_progress(
                    message_id=message_id,
                    request_id=request_id,
                    session_id=request.session_id,
                    commands=chain_state["commands"],
                    current_idx=len(chain_state["commands"]) - 1,
                    approved_indices=chain_state["approved_indices"],
                    project_path=session.project_path if session else None,
                    final_approve=False,  # Don't show button, just show all approved
                    denied=False,
                )

                await self.notifier.edit_message(
                    message_id,
                    f"✅ Chain approved - all {len(chain_state['commands'])} commands matched rules or were approved"
                )
            else:
                # Find first unapproved command (start from 0, not command_idx + 1)
                next_idx = 0
                while next_idx < len(chain_state["commands"]) and next_idx in chain_state["approved_indices"]:
                    next_idx += 1

                if next_idx < len(chain_state["commands"]):
                    await self.notifier.update_chain_progress(
                        message_id=message_id,
                        request_id=request_id,
                        session_id=request.session_id,
                        commands=chain_state["commands"],
                        current_idx=next_idx,
                        approved_indices=chain_state["approved_indices"],
                        project_path=session.project_path if session else None,
                    )

    async def _handle_chain_approve_all(
        self,
        request_id: str,
        callback_id: str,
        message_id: Optional[int] = None,
    ):
        """Handle final approval of entire chain."""
        request = await self.storage.get_request(request_id)
        if not request:
            await self.notifier.answer_callback(callback_id, "Request not found")
            if message_id:
                await self.notifier.edit_message(message_id, "⚠️ Request expired")
            return

        # Verify all commands are approved
        chain_state = await self._get_chain_state(request_id)
        if not chain_state:
            await self.notifier.answer_callback(callback_id, "Chain state not found")
            return

        if len(chain_state["approved_indices"]) < len(chain_state["commands"]):
            await self.notifier.answer_callback(callback_id, "Not all commands approved")
            return

        # Approve the request
        await self.storage.resolve_request(
            request_id=request_id,
            status="approved",
            resolved_by="user",
        )

        # Clear chain state
        await self._clear_chain_state(request_id)

        await self.notifier.answer_callback(callback_id, "Approved")

        # Update message
        if message_id:
            session = await self.storage.get_session(request.session_id)
            project_id = self._format_project_id(session.project_path if session else None, request.session_id)
            await self.notifier.edit_message(
                message_id,
                f"<i>{project_id}</i>\n✅ <b>Chain approved</b> ({len(chain_state['commands'])} commands)",
            )

        await self.storage.log_audit(
            event_type="response",
            session_id=request.session_id,
            details={
                "request_id": request_id,
                "action": "approve",
                "resolved_by": "user",
                "chain": True,
                "command_count": len(chain_state["commands"]),
            },
        )

    def _chain_state_key(self, request_id: str) -> int:
        """Generate stable key for chain state storage.

        Uses hashlib for stable hashing across process restarts
        (Python's hash() is randomized by PYTHONHASHSEED).
        """
        import hashlib
        return int(hashlib.md5(f"chain:{request_id}".encode()).hexdigest()[:8], 16)

    async def _get_chain_state(self, request_id: str) -> Optional[dict]:
        """Get chain approval state from storage.

        Uses pending_feedback table with a hash of request_id as the message_id.
        The state is stored in the request_id field as JSON.
        """
        # Use a stable hash of the request_id as the message_id
        msg_id = self._chain_state_key(request_id)

        cursor = await self.storage._conn.execute(
            "SELECT request_id FROM pending_feedback WHERE prompt_msg_id = ?",
            (msg_id,),
        )
        row = await cursor.fetchone()
        if row:
            try:
                return json.loads(row["request_id"])
            except (json.JSONDecodeError, TypeError):
                pass
        return None

    async def _save_chain_state(self, request_id: str, state: dict):
        """Save chain approval state to storage.

        Uses pending_feedback table with a stable hash of request_id as the message_id.
        The state is stored in the request_id field as JSON.
        """
        state_json = json.dumps(state)
        msg_id = self._chain_state_key(request_id)

        await self.storage._conn.execute(
            """
            INSERT OR REPLACE INTO pending_feedback (prompt_msg_id, request_id, created_at)
            VALUES (?, ?, ?)
            """,
            (msg_id, state_json, time.time()),
        )
        await self.storage._conn.commit()

    async def _clear_chain_state(self, request_id: str):
        """Clear chain approval state from storage."""
        msg_id = self._chain_state_key(request_id)
        await self.storage._conn.execute(
            "DELETE FROM pending_feedback WHERE prompt_msg_id = ?",
            (msg_id,),
        )
        await self.storage._conn.commit()

    def _generate_rule_patterns(self, tool_name: str, tool_input: Optional[str]) -> list[tuple[str, str]]:
        """Generate rule pattern options with labels.

        Returns list of (pattern, label) tuples.
        """
        import json

        patterns = []

        if not tool_input:
            return [(f"{tool_name}(*)", f"Any {tool_name}")]

        try:
            data = json.loads(tool_input)
        except (json.JSONDecodeError, TypeError):
            return [(f"{tool_name}(*)", f"Any {tool_name}")]

        # For Bash commands - use CommandParser for rich pattern generation
        if tool_name == "Bash" and "command" in data:
            cmd = data["command"].strip()

            try:
                # Parse the command using CommandParser
                parser = CommandParser()
                nodes = parser.parse(cmd)

                # Generate patterns from all parsed nodes
                all_patterns = []
                for node in nodes:
                    node_patterns = parser.generate_patterns(node)
                    all_patterns.extend(node_patterns)

                # Convert raw patterns to (pattern, label) tuples with Bash() wrapping
                for pattern in all_patterns:
                    if pattern:  # Skip empty patterns
                        # Create a label based on whether it's an exact command or wildcard
                        if pattern.endswith("*"):
                            label = f"🔧 {pattern}"
                        elif " " in pattern:
                            label = f"📌 {pattern[:50]}"  # Truncate long commands for label
                        else:
                            label = f"📌 {pattern}"

                        patterns.append((f"Bash({pattern})", label))

                if patterns:
                    # Remove duplicates while preserving order
                    seen = set()
                    unique = []
                    for pattern, label in patterns:
                        if pattern not in seen:
                            seen.add(pattern)
                            unique.append((pattern, label))
                    return unique
            except Exception:
                # Fallback to basic pattern if parsing fails
                pass

            # Fallback if parsing fails or no patterns generated
            return [(f"Bash({cmd})", "📌 This exact command"), (f"Bash(*)", "🔧 Any Bash")]

        # For Edit/Write - file patterns
        if tool_name in ("Edit", "Write") and "file_path" in data:
            path = data["file_path"]
            filename = path.rsplit("/", 1)[-1] if "/" in path else path

            patterns.append((f"{tool_name}({path})", f"📌 {filename}"))

            if "." in path:
                ext = path.rsplit(".", 1)[-1]
                patterns.append((f"{tool_name}(*.{ext})", f"📄 Any *.{ext}"))

            if "/" in path:
                dir_path = path.rsplit("/", 1)[0]
                short_dir = dir_path.split("/")[-1] or dir_path
                patterns.append((f"{tool_name}({dir_path}/*)", f"📁 Any in .../{short_dir}/"))

            patterns.append((f"{tool_name}(*)", f"⚡ Any {tool_name}"))

        # For Read - directory patterns
        elif tool_name == "Read" and "file_path" in data:
            path = data["file_path"]
            filename = path.rsplit("/", 1)[-1] if "/" in path else path

            patterns.append((f"Read({path})", f"📌 {filename}"))

            if "/" in path:
                dir_path = path.rsplit("/", 1)[0]
                short_dir = dir_path.split("/")[-1] or dir_path
                patterns.append((f"Read({dir_path}/*)", f"📁 Any in .../{short_dir}/"))

            patterns.append(("Read(*)", "⚡ Any Read"))

        # For other tools
        else:
            patterns.append((f"{tool_name}(*)", f"⚡ Any {tool_name}"))

        # Remove duplicates while preserving order (by pattern)
        seen = set()
        unique = []
        for pattern, label in patterns:
            if pattern not in seen:
                seen.add(pattern)
                unique.append((pattern, label))

        return unique

    async def _check_chain_rules(self, cmd: str) -> Optional[str]:
        """Check if a bash command chain matches any rules.

        Returns:
            "approve" if ALL commands match allow rules
            "deny" if ANY command matches deny rule
            None if manual approval needed
        """
        from pyafk.core.rules import RulesEngine

        # Parse the command into chain nodes
        parser = CommandParser()
        nodes = parser.parse(cmd)

        # Check each command in the chain
        engine = RulesEngine(self.storage)
        has_unmatched = False

        for node in nodes:
            # Generate patterns for this command
            patterns = parser.generate_patterns(node)

            # Check if any pattern matches a rule
            matched = False
            for pattern in patterns:
                # Check the pattern as a Bash command
                rule_result = await engine.check("Bash", json.dumps({"command": pattern}))

                if rule_result == "deny":
                    # Any deny rule in the chain means deny the whole chain
                    return "deny"
                elif rule_result == "approve":
                    # This command matched an allow rule
                    matched = True
                    break

            if not matched:
                # This command didn't match any rule
                has_unmatched = True

        # If all commands matched allow rules, approve the whole chain
        if not has_unmatched:
            return "approve"

        # Some commands didn't match any rule - need manual approval
        return None

    def _format_project_id(self, project_path: Optional[str], session_id: str) -> str:
        """Format project path for display."""
        if project_path:
            parts = project_path.rstrip("/").split("/")
            return "/".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
        return session_id[:8]

    def _format_tool_summary(self, tool_name: str, tool_input: Optional[str]) -> str:
        """Format tool input for display."""
        import json

        if not tool_input:
            return ""

        try:
            data = json.loads(tool_input)
        except (json.JSONDecodeError, TypeError):
            return str(tool_input)[:100]

        # Extract the most relevant field
        if "command" in data:
            summary = data["command"]
        elif "file_path" in data:
            summary = data["file_path"]
        elif "path" in data:
            summary = data["path"]
        elif "url" in data:
            summary = data["url"]
        else:
            summary = json.dumps(data)

        # Truncate if too long
        if len(summary) > 100:
            summary = summary[:100] + "..."

        # Escape HTML
        return summary.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _create_rule_pattern(self, tool_name: str, tool_input: Optional[str]) -> str:
        """Create a smart rule pattern from tool and input."""
        import json

        if not tool_input:
            return f"{tool_name}(*)"

        try:
            data = json.loads(tool_input)
        except (json.JSONDecodeError, TypeError):
            return f"{tool_name}(*)"

        # For Bash, extract command prefix (first word)
        if tool_name == "Bash" and "command" in data:
            cmd = data["command"].strip()
            first_word = cmd.split()[0] if cmd.split() else ""
            if first_word:
                return f"Bash({first_word} *)"

        # For Edit/Write, use file extension pattern
        if tool_name in ("Edit", "Write") and "file_path" in data:
            path = data["file_path"]
            if "." in path:
                ext = path.rsplit(".", 1)[-1]
                return f"{tool_name}(*.{ext})"

        # For Read, use directory pattern
        if tool_name == "Read" and "file_path" in data:
            path = data["file_path"]
            if "/" in path:
                dir_path = path.rsplit("/", 1)[0]
                return f"Read({dir_path}/*)"

        return f"{tool_name}(*)"

    async def poll_loop(self, timeout: float = 30.0):
        """Main polling loop. Acquires lock first."""
        acquired = await self.lock.acquire(timeout=0.1)
        if not acquired:
            return

        try:
            self._running = True
            start = time.monotonic()

            while self._running:
                elapsed = time.monotonic() - start
                if elapsed >= timeout:
                    break

                await self.process_updates_once()
                await asyncio.sleep(0.5)
        finally:
            self._running = False
            await self.lock.release()

    def stop(self):
        """Signal the poll loop to stop."""
        self._running = False
