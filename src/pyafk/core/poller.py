"""Telegram poller with file-based locking."""

import asyncio
import fcntl
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

from pyafk.core.command_parser import CommandParser
from pyafk.core.storage import Storage
from pyafk.notifiers.telegram import TelegramNotifier
from pyafk.utils.debug import debug_callback, debug_chain, debug_rule
from pyafk.utils.formatting import format_project_id, truncate_command


def _safe_int(value: str, default: int = 0) -> int:
    """Safely parse an integer from callback data."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


class PollLock:
    """File-based lock for single poller."""

    def __init__(self, lock_path: Path) -> None:
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

    async def release(self) -> None:
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
    ) -> None:
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
        except (ValueError, OSError) as e:
            debug_callback(f"Ignored error loading offset", error=str(e)[:50])
        return None

    def _save_offset(self, offset: int) -> None:
        """Persist Telegram update offset."""
        try:
            self._offset_file.write_text(str(offset))
        except OSError as e:
            debug_callback(f"Ignored error saving offset", error=str(e)[:50])

    async def process_updates_once(self) -> int:
        """Process one batch of updates.

        Returns number of updates processed.
        """
        try:
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
        except Exception as e:
            import traceback
            debug_callback(f"Error in process_updates_once", error=str(e)[:200])
            debug_callback(f"Traceback", tb=traceback.format_exc()[:500])
            return 0

    async def _handle_message(self, message: dict[str, Any]) -> None:
        """Handle a text message - check for commands, feedback, or subagent replies."""
        text = message.get("text", "")
        debug_callback(f"_handle_message called", text=text[:50] if text else "", has_text=bool(text))

        # Handle /msg command
        if text.startswith("/msg"):
            await self._handle_msg_command(text, message)
            return

        reply_to = message.get("reply_to_message", {})
        reply_msg_id = reply_to.get("message_id")
        if not reply_msg_id:
            debug_callback(f"No reply_to_message, ignoring")
            return

        # Check if this is a reply to a feedback prompt we sent
        request_id = await self.storage.get_pending_feedback(reply_msg_id)
        debug_callback(f"Looked up pending_feedback", reply_msg_id=reply_msg_id, request_id=request_id)

        if not request_id:
            # Check if it's a reply to a subagent finish message
            subagent = await self.storage.get_subagent_by_telegram_msg(reply_msg_id)
            if subagent:
                instructions = message.get("text", "")
                subagent_id = subagent["subagent_id"]
                await self.storage.resolve_subagent(subagent_id, "continue", instructions)
                await self.notifier.send_message(f"📨 Instructions sent to agent")
                # Update the original message to show it's been handled
                await self.notifier.edit_message(reply_msg_id, "✅ Subagent continued with instructions")
                debug_callback(f"Sent instructions to subagent", subagent_id=subagent_id[:8])
                return

            # Check if it's a reply to an approval message (for followup instructions)
            request = await self.storage.get_request_by_telegram_msg(reply_msg_id)
            if request:
                followup = message.get("text", "")
                await self.storage.add_pending_message(request.session_id, followup)
                await self.notifier.send_message(
                    f"📝 Followup queued for next tool call"
                )
                debug_callback(f"Queued followup message", session_id=request.session_id[:8])
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
    ) -> None:
        """Handle subagent continue instructions."""
        debug_callback(f"_handle_subagent_feedback called", subagent_id=subagent_id, instructions=instructions[:50])

        # Clear the pending feedback entry
        await self.storage.clear_pending_feedback(prompt_msg_id)

        # Resolve the subagent with continue status and instructions
        await self.storage.resolve_subagent(subagent_id, "continue", instructions)
        debug_callback(f"Resolved subagent with continue", subagent_id=subagent_id)

        # Delete the prompt message and send confirmation
        await self.notifier.delete_message(prompt_msg_id)
        await self.notifier.send_message(f"📨 Instructions sent to agent")

    async def _handle_msg_command(self, text: str, message: dict[str, Any]) -> None:
        """Handle /msg command to send message to a Claude session.

        Usage:
            /msg - Show active sessions
            /msg <session_id> <message> - Send message to session
        """
        parts = text.split(None, 2)  # Split: /msg, session_id, message

        if len(parts) == 1:
            # Just /msg - show active sessions
            sessions = await self.storage.get_active_sessions()
            if not sessions:
                await self.notifier.send_message("No active sessions")
                return

            lines = ["<b>Active sessions:</b>\n"]
            for s in sessions[-10:]:  # Last 10 sessions
                # Show short ID and project path
                short_id = s.session_id[:8]
                project = s.project_path.split("/")[-1] if s.project_path else "unknown"
                lines.append(f"<code>{short_id}</code> - {project}")

            lines.append("\n<i>Use: /msg &lt;id&gt; &lt;message&gt;</i>")
            await self.notifier.send_message("\n".join(lines))
            return

        if len(parts) < 3:
            await self.notifier.send_message("Usage: /msg <session_id> <message>")
            return

        session_prefix = parts[1]
        msg_text = parts[2]

        # Find session by prefix
        sessions = await self.storage.get_active_sessions()
        matching = [s for s in sessions if s.session_id.startswith(session_prefix)]

        if not matching:
            await self.notifier.send_message(f"No session found matching '{session_prefix}'")
            return

        if len(matching) > 1:
            await self.notifier.send_message(
                f"Multiple sessions match '{session_prefix}'. Be more specific."
            )
            return

        session = matching[0]
        await self.storage.add_pending_message(session.session_id, msg_text)

        short_id = session.session_id[:8]
        project = session.project_path.split("/")[-1] if session.project_path else "unknown"
        await self.notifier.send_message(
            f"📨 Message queued for <code>{short_id}</code> ({project})"
        )

    async def _handle_callback(self, callback: dict[str, Any]) -> None:
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
            pattern_idx = _safe_int(parts[1]) if len(parts) > 1 else 0
            await self._handle_add_rule(request_id, callback_id, message_id, pattern_idx)
        elif action == "chain_rule_pattern":
            # Format: chain_rule_pattern:request_id:command_idx:pattern_index
            parts = target_id.split(":")
            if len(parts) >= 3:
                request_id = parts[0]
                command_idx = _safe_int(parts[1])
                pattern_idx = _safe_int(parts[2])
                await self._handle_chain_rule_pattern(request_id, command_idx, pattern_idx, callback_id, message_id)
        elif action == "subagent_ok":
            await self._handle_subagent_ok(target_id, callback_id, message_id)
        elif action == "subagent_continue":
            await self._handle_subagent_continue(target_id, callback_id, message_id)
        elif action == "chain_approve":
            # Format: chain_approve:request_id:command_index
            parts = target_id.split(":", 1)
            request_id = parts[0]
            command_idx = _safe_int(parts[1]) if len(parts) > 1 else 0
            await self._handle_chain_approve(request_id, command_idx, callback_id, message_id)
        elif action == "chain_deny":
            await self._handle_chain_deny(target_id, callback_id, message_id)
        elif action == "chain_deny_msg":
            await self._handle_chain_deny_msg(target_id, callback_id, message_id)
        elif action == "chain_rule":
            # Format: chain_rule:request_id:command_index
            parts = target_id.split(":", 1)
            request_id = parts[0]
            command_idx = _safe_int(parts[1]) if len(parts) > 1 else 0
            await self._handle_chain_rule(request_id, command_idx, callback_id, message_id)
        elif action == "chain_approve_all":
            await self._handle_chain_approve_all(target_id, callback_id, message_id)
        elif action == "chain_approve_entire":
            await self._handle_chain_approve_entire(target_id, callback_id, message_id)
        elif action == "chain_cancel_rule":
            # Format: chain_cancel_rule:request_id:command_index
            parts = target_id.split(":", 1)
            request_id = parts[0]
            command_idx = _safe_int(parts[1]) if len(parts) > 1 else 0
            await self._handle_chain_cancel_rule(request_id, command_idx, callback_id, message_id)

    async def _handle_approval(
        self,
        request_id: str,
        action: str,
        callback_id: str,
        message_id: Optional[int] = None,
    ) -> None:
        """Handle approve/deny callback."""
        try:
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
                project_id = format_project_id(session.project_path if session else None, request.session_id)
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
        except Exception as e:
            debug_callback(f"Error in _handle_approval", error=str(e)[:100], request_id=request_id)
            await self.notifier.answer_callback(callback_id, "Error occurred")

    async def _handle_deny_msg(
        self,
        request_id: str,
        callback_id: str,
        message_id: Optional[int] = None,
    ) -> None:
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
    ) -> None:
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

    async def _handle_approve_all(self, session_id: str, tool_name: Optional[str], callback_id: str) -> None:
        """Approve all pending requests for a session and tool type, and add a rule for future requests."""
        try:
            from pyafk.core.rules import RulesEngine
            debug_callback(f"_handle_approve_all called", session_id=session_id, tool_name=tool_name)
            pending = await self.storage.get_pending_requests()
            debug_callback(f"Found pending requests", count=len(pending), pending_session_ids=[r.session_id for r in pending])

            # Filter by session and tool type
            to_approve = [
                r for r in pending
                if r.session_id == session_id and (tool_name is None or r.tool_name == tool_name)
            ]
            debug_callback(f"Filtered to_approve", count=len(to_approve))

            for request in to_approve:
                debug_callback(f"Approving request", request_id=request.id, tool=request.tool_name)
                await self.storage.resolve_request(
                    request_id=request.id,
                    status="approved",
                    resolved_by="user:approve_all",
                )
                # Update the Telegram message
                if request.telegram_msg_id:
                    session = await self.storage.get_session(request.session_id)
                    project_id = format_project_id(session.project_path if session else None, request.session_id)
                    tool_summary = self._format_tool_summary(request.tool_name, request.tool_input)
                    await self.notifier.edit_message(
                        request.telegram_msg_id,
                        f"<i>{project_id}</i>\n✅ <b>[{request.tool_name}]</b> <code>{tool_summary}</code>",
                    )
                debug_callback(f"Request approved", request_id=request.id)

            # Add a rule to auto-approve future requests of this tool type
            rule_added = False
            if tool_name:
                pattern = f"{tool_name}(*)"
                engine = RulesEngine(self.storage)
                await engine.add_rule(pattern, "approve", priority=0, created_via="telegram:approve_all")
                debug_callback(f"Added rule for future requests", pattern=pattern)
                rule_added = True

            tool_label = tool_name or "all"
            debug_callback(f"Approve all complete", approved=len(to_approve), tool=tool_label, rule_added=rule_added)

            if rule_added:
                await self.notifier.answer_callback(
                    callback_id,
                    f"Approved {len(to_approve)} + added rule for all {tool_name}",
                )
            else:
                await self.notifier.answer_callback(
                    callback_id,
                    f"Approved {len(to_approve)} {tool_label}",
                )
        except Exception as e:
            debug_callback(f"Error in _handle_approve_all", error=str(e)[:100], session_id=session_id)
            await self.notifier.answer_callback(callback_id, "Error occurred")

    async def _handle_cancel_rule(
        self,
        request_id: str,
        callback_id: str,
        message_id: Optional[int] = None,
    ) -> None:
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
    ) -> None:
        """Show rule pattern options menu inline."""
        request = await self.storage.get_request(request_id)
        if not request:
            await self.notifier.answer_callback(callback_id, "Request not found")
            if message_id:
                await self.notifier.edit_message(message_id, "⚠️ Request expired")
            return

        # Get session for project_path
        session = await self.storage.get_session(request.session_id)
        project_path = session.project_path if session else None

        # Generate pattern options
        patterns = self._generate_rule_patterns(request.tool_name, request.tool_input, project_path)

        await self.notifier.answer_callback(callback_id, "Choose pattern")

        # Edit message inline with pattern options
        if message_id:
            # Strip any previous rule prompt text for clean display
            base_text = original_text.split("\n\n📝")[0] if "\n\n📝" in original_text else original_text
            await self.notifier.edit_message_with_rule_keyboard(
                message_id, base_text, request_id, patterns
            )

    async def _handle_add_rule(self, request_id: str, callback_id: str, message_id: Optional[int] = None, pattern_idx: int = 0) -> None:
        """Handle add rule selection - creates auto-approve rule and approves request."""
        try:
            request = await self.storage.get_request(request_id)
            if not request:
                await self.notifier.answer_callback(callback_id, "Request not found")
                if message_id:
                    await self.notifier.edit_message(message_id, "⚠️ Request expired")
                return

            # Get session for project_path
            session = await self.storage.get_session(request.session_id)
            project_path = session.project_path if session else None

            # Get the selected pattern (tuple of pattern, label)
            patterns = self._generate_rule_patterns(request.tool_name, request.tool_input, project_path)
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
                project_id = format_project_id(session.project_path if session else None, request.session_id)
                tool_summary = self._format_tool_summary(request.tool_name, request.tool_input)
                await self.notifier.edit_message(
                    message_id,
                    f"<i>{project_id}</i>\n✅ <b>[{request.tool_name}]</b> <code>{tool_summary}</code>\n📝 Rule: {label}",
                )

            await self.notifier.answer_callback(
                callback_id,
                f"Rule added",
            )
        except Exception as e:
            debug_callback(f"Error in _handle_add_rule", error=str(e)[:100], request_id=request_id)
            await self.notifier.answer_callback(callback_id, "Error occurred")

    async def _handle_subagent_ok(
        self,
        subagent_id: str,
        callback_id: str,
        message_id: Optional[int] = None,
    ) -> None:
        """Handle subagent OK button - let subagent stop normally."""
        debug_callback(f"_handle_subagent_ok called", subagent_id=subagent_id, message_id=message_id)
        await self.storage.resolve_subagent(subagent_id, "ok")
        debug_callback(f"Resolved subagent", status="ok")

        await self.notifier.answer_callback(callback_id, "OK")

        if message_id:
            debug_callback(f"Editing message", message_id=message_id)
            await self.notifier.edit_message(
                message_id,
                "✅ Subagent finished",
            )
            debug_callback(f"Message edited")

    async def _handle_subagent_continue(
        self,
        subagent_id: str,
        callback_id: str,
        message_id: Optional[int] = None,
    ) -> None:
        """Handle subagent Continue button - prompt for instructions."""
        debug_callback(f"_handle_subagent_continue called", subagent_id=subagent_id, message_id=message_id)
        await self.notifier.answer_callback(callback_id, "Reply with instructions")

        # Send continue prompt
        prompt_msg_id = await self.notifier.send_continue_prompt()
        debug_callback(f"Sent continue prompt", prompt_msg_id=prompt_msg_id)
        if prompt_msg_id:
            await self.storage.set_subagent_continue_prompt(subagent_id, prompt_msg_id)
            debug_callback(f"Stored continue prompt", subagent_id=subagent_id)

        # Update the original message to show waiting for instructions
        if message_id:
            await self.notifier.edit_message(
                message_id,
                "⏳ Waiting for instructions...",
            )

    async def _handle_chain_approve(
        self,
        request_id: str,
        command_idx: int,
        callback_id: str,
        message_id: Optional[int] = None,
    ) -> None:
        """Handle chain approval for one command."""
        try:
            debug_chain(f"chain_approve called", request_id=request_id, command_idx=command_idx)
            request = await self.storage.get_request(request_id)
            if not request:
                debug_chain(f"Request not found", request_id=request_id)
                await self.notifier.answer_callback(callback_id, "Request not found")
                if message_id:
                    await self.notifier.edit_message(message_id, "⚠️ Request expired")
                return

            # Get chain state from pending_feedback (stored as JSON)
            result = await self._get_chain_state(request_id)
            debug_chain(f"Got chain state", result=result)
            if result:
                chain_state, version = result
            else:
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
                    version = 0
                except Exception:
                    await self.notifier.answer_callback(callback_id, "Failed to parse chain")
                    return

            # Mark this command as approved
            if command_idx not in chain_state["approved_indices"]:
                chain_state["approved_indices"].append(command_idx)
                debug_chain(f"Added command to approved", command_idx=command_idx, approved=chain_state["approved_indices"])

            # Save updated state with optimistic locking
            if not await self._save_chain_state(request_id, chain_state, version):
                # Conflict - re-read and retry once
                debug_chain(f"Save conflict, retrying", request_id=request_id)
                result = await self._get_chain_state(request_id)
                if result:
                    chain_state, version = result
                    if command_idx not in chain_state["approved_indices"]:
                        chain_state["approved_indices"].append(command_idx)
                    await self._save_chain_state(request_id, chain_state, version)
            debug_chain(f"Saved chain state", approved_count=len(chain_state["approved_indices"]), total=len(chain_state["commands"]))

            await self.notifier.answer_callback(callback_id, "Approved")

            # Check if all commands are approved
            if len(chain_state["approved_indices"]) >= len(chain_state["commands"]):
                debug_chain(f"All commands approved, auto-approving chain")
                # All approved - auto-approve the entire chain (no extra button click needed)
                await self.storage.resolve_request(
                    request_id=request_id,
                    status="approved",
                    resolved_by="user:chain_all_approved",
                )
                await self._clear_chain_state(request_id)

                if message_id:
                    session = await self.storage.get_session(request.session_id)
                    project_id = format_project_id(session.project_path if session else None, request.session_id)
                    msg = self._format_chain_approved_message(chain_state["commands"], project_id)
                    await self.notifier.edit_message(message_id, msg)

                await self.storage.log_audit(
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
        except Exception as e:
            debug_callback(f"Error in _handle_chain_approve", error=str(e)[:100], request_id=request_id)
            await self.notifier.answer_callback(callback_id, "Error occurred")

    async def _handle_chain_deny(
        self,
        request_id: str,
        callback_id: str,
        message_id: Optional[int] = None,
    ) -> None:
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
            result = await self._get_chain_state(request_id)
            if result:
                chain_state, _version = result
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
    ) -> None:
        """Handle chain deny with message - prompt for feedback."""
        print(f"[pyafk] _handle_chain_deny_msg called: {request_id}", file=sys.stderr)
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
    ) -> None:
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
            resolved_by="user:feedback",
            denial_reason=feedback,
        )

        # Clear chain state
        await self._clear_chain_state(request_id)

        # Delete the feedback prompt message
        debug_callback(f"Deleting feedback prompt", prompt_msg_id=prompt_msg_id)
        await self.notifier.delete_message(prompt_msg_id)

        # Update the original approval message
        debug_callback(f"Updating original message", telegram_msg_id=request.telegram_msg_id)
        if request.telegram_msg_id:
            session = await self.storage.get_session(request.session_id)
            project_id = format_project_id(session.project_path if session else None, request.session_id)
            tool_summary = self._format_tool_summary(request.tool_name, request.tool_input)
            await self.notifier.edit_message(
                request.telegram_msg_id,
                f"<i>{project_id}</i>\n❌ <b>[{request.tool_name}]</b> <code>{tool_summary}</code>\n\n💬 {feedback}",
            )
            debug_callback(f"Message updated for chain denial")

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
    ) -> None:
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
        result = await self._get_chain_state(request_id)
        debug_rule(f"Got chain state", result=result)
        if result:
            chain_state, _version = result
        else:
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
                await self._save_chain_state(request_id, chain_state, version=0)
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
                f"Command {command_idx + 1}: <code>{truncate_command(cmd)}</code>",
                request_id,
                patterns,
                callback_prefix=f"chain_rule_pattern:{request_id}:{command_idx}",
                cancel_callback=f"chain_cancel_rule:{request_id}:{command_idx}",
            )

    async def _handle_chain_cancel_rule(
        self,
        request_id: str,
        command_idx: int,
        callback_id: str,
        message_id: Optional[int] = None,
    ) -> None:
        """Handle cancel from chain rule menu - go back to chain progress."""
        debug_rule(f"chain_cancel_rule called", request_id=request_id, command_idx=command_idx)
        request = await self.storage.get_request(request_id)
        if not request:
            await self.notifier.answer_callback(callback_id, "Request not found")
            if message_id:
                await self.notifier.edit_message(message_id, "⚠️ Request expired")
            return

        # Get chain state
        result = await self._get_chain_state(request_id)
        if not result:
            await self.notifier.answer_callback(callback_id, "Chain state not found")
            return
        chain_state, _version = result

        await self.notifier.answer_callback(callback_id, "Cancelled")

        # Restore the chain progress view
        if message_id:
            session = await self.storage.get_session(request.session_id)
            await self.notifier.update_chain_progress(
                message_id=message_id,
                request_id=request_id,
                session_id=request.session_id,
                commands=chain_state["commands"],
                current_idx=command_idx,
                approved_indices=chain_state["approved_indices"],
                project_path=session.project_path if session else None,
            )

    async def _handle_chain_rule_pattern(
        self,
        request_id: str,
        command_idx: int,
        pattern_idx: int,
        callback_id: str,
        message_id: Optional[int] = None,
    ) -> None:
        """Handle rule pattern selection for a chain command."""
        try:
            debug_rule(f"chain_rule_pattern called", request_id=request_id, command_idx=command_idx, pattern_idx=pattern_idx)
            request = await self.storage.get_request(request_id)
            if not request:
                debug_rule(f"Request not found", request_id=request_id)
                await self.notifier.answer_callback(callback_id, "Request not found")
                if message_id:
                    await self.notifier.edit_message(message_id, "⚠️ Request expired")
                return

            # Get chain state
            result = await self._get_chain_state(request_id)
            debug_rule(f"Got chain state", result=result)
            if not result:
                debug_rule(f"Chain state not found", request_id=request_id)
                await self.notifier.answer_callback(callback_id, "Chain state not found")
                return
            chain_state, version = result
            if command_idx >= len(chain_state["commands"]):
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

            # Check if the new rule also matches other commands in the chain
            auto_approved = []
            for idx, other_cmd in enumerate(chain_state["commands"]):
                if idx in chain_state["approved_indices"]:
                    continue  # Already approved

                # Check if this command matches the new rule
                other_input = json.dumps({"command": other_cmd})
                rule_result = await engine.check("Bash", other_input)
                if rule_result == "approve":
                    chain_state["approved_indices"].append(idx)
                    auto_approved.append(idx)
                    debug_rule(f"Auto-approved by new rule", idx=idx, cmd=other_cmd[:50])

            # Save with optimistic locking
            if not await self._save_chain_state(request_id, chain_state, version):
                # Conflict - re-read and retry once
                debug_rule(f"Save conflict, retrying", request_id=request_id)
                result = await self._get_chain_state(request_id)
                if result:
                    chain_state, version = result
                    # Re-apply changes
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
                    await self._save_chain_state(request_id, chain_state, version)

            if auto_approved:
                await self.notifier.answer_callback(callback_id, f"Rule added (+{len(auto_approved)} auto-approved)")
            else:
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
                    project_id = format_project_id(session.project_path if session else None, request.session_id)
                    msg = self._format_chain_approved_message(chain_state["commands"], project_id)
                    await self.notifier.edit_message(message_id, msg)
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
        except Exception as e:
            debug_callback(f"Error in _handle_chain_rule_pattern", error=str(e)[:100], request_id=request_id)
            await self.notifier.answer_callback(callback_id, "Error occurred")

    async def _handle_chain_approve_all(
        self,
        request_id: str,
        callback_id: str,
        message_id: Optional[int] = None,
    ) -> None:
        """Handle final approval of entire chain."""
        request = await self.storage.get_request(request_id)
        if not request:
            await self.notifier.answer_callback(callback_id, "Request not found")
            if message_id:
                await self.notifier.edit_message(message_id, "⚠️ Request expired")
            return

        # Verify all commands are approved
        result = await self._get_chain_state(request_id)
        if not result:
            await self.notifier.answer_callback(callback_id, "Chain state not found")
            return
        chain_state, _version = result

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
            project_id = format_project_id(session.project_path if session else None, request.session_id)
            msg = self._format_chain_approved_message(chain_state["commands"], project_id)
            await self.notifier.edit_message(message_id, msg)

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

    async def _handle_chain_approve_entire(
        self,
        request_id: str,
        callback_id: str,
        message_id: Optional[int] = None,
    ) -> None:
        """Handle upfront approval of entire chain (without individual command approval)."""
        try:
            debug_chain(f"chain_approve_entire called", request_id=request_id)
            request = await self.storage.get_request(request_id)
            if not request:
                debug_chain(f"Request not found", request_id=request_id)
                await self.notifier.answer_callback(callback_id, "Request not found")
                if message_id:
                    await self.notifier.edit_message(message_id, "⚠️ Request expired")
                return

            # Parse commands from tool_input
            try:
                data = json.loads(request.tool_input)
                cmd = data.get("command", "")
                parser = CommandParser()
                commands = parser.split_chain(cmd)
            except Exception:
                commands = []

            # Approve the request directly
            await self.storage.resolve_request(
                request_id=request_id,
                status="approved",
                resolved_by="user:chain_entire",
            )

            await self.notifier.answer_callback(callback_id, "Chain approved")

            # Update message
            if message_id:
                session = await self.storage.get_session(request.session_id)
                project_id = format_project_id(session.project_path if session else None, request.session_id)
                if commands:
                    msg = self._format_chain_approved_message(commands, project_id)
                else:
                    msg = f"<i>{project_id}</i>\n✅ <b>Chain approved</b>"
                await self.notifier.edit_message(message_id, msg)

            await self.storage.log_audit(
                event_type="response",
                session_id=request.session_id,
                details={
                    "request_id": request_id,
                    "action": "approve",
                    "resolved_by": "user:chain_entire",
                    "chain": True,
                    "command_count": len(commands) if commands else 0,
                },
            )
        except Exception as e:
            debug_callback(f"Error in _handle_chain_approve_entire", error=str(e)[:100], request_id=request_id)
            await self.notifier.answer_callback(callback_id, "Error occurred")

    def _chain_state_key(self, request_id: str) -> int:
        """Generate stable key for chain state storage.

        Uses hashlib for stable hashing across process restarts
        (Python's hash() is randomized by PYTHONHASHSEED).
        """
        import hashlib
        return int(hashlib.md5(f"chain:{request_id}".encode()).hexdigest()[:8], 16)

    async def _get_chain_state(self, request_id: str) -> Optional[tuple[dict[str, Any], int]]:
        """Get chain approval state and version from storage.

        Uses pending_feedback table with a hash of request_id as the message_id.
        The state is stored in the request_id field as JSON.

        Returns (state_dict, version) or None.
        """
        msg_id = self._chain_state_key(request_id)
        result = await self.storage.get_chain_state(msg_id)
        if result:
            state_json, version = result
            try:
                return (json.loads(state_json), version)
            except (json.JSONDecodeError, TypeError):
                pass
        return None

    async def _save_chain_state(self, request_id: str, state: dict[str, Any], version: int) -> bool:
        """Save chain approval state atomically.

        Uses pending_feedback table with a stable hash of request_id as the message_id.
        The state is stored in the request_id field as JSON.

        Args:
            request_id: The request identifier
            state: The chain state dict to save
            version: Expected version for optimistic locking (0 for new state)

        Returns:
            True if saved successfully, False on version conflict.
        """
        state_json = json.dumps(state)
        msg_id = self._chain_state_key(request_id)
        if version == 0:
            # New state - use regular save
            await self.storage.save_chain_state(msg_id, state_json)
            return True
        return await self.storage.save_chain_state_atomic(msg_id, state_json, version)

    async def _clear_chain_state(self, request_id: str) -> None:
        """Clear chain approval state from storage."""
        msg_id = self._chain_state_key(request_id)
        await self.storage.clear_chain_state(msg_id)

    def _generate_rule_patterns(
        self,
        tool_name: str,
        tool_input: Optional[str],
        project_path: Optional[str] = None,
    ) -> list[tuple[str, str]]:
        """Generate rule pattern options with labels.

        Args:
            tool_name: Name of the tool (Bash, Edit, Read, etc.)
            tool_input: JSON string of tool input
            project_path: Optional project path for directory-scoped patterns

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

            # Add project-scoped pattern if project_path is available
            if project_path and path.startswith(project_path):
                project_name = project_path.rstrip("/").split("/")[-1]
                if "." in path:
                    ext = path.rsplit(".", 1)[-1]
                    patterns.append((f"{tool_name}({project_path}/*.{ext})", f"📂 Any *.{ext} in {project_name}/"))
                patterns.append((f"{tool_name}({project_path}/*)", f"📂 Any in {project_name}/"))

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

            # Add project-scoped pattern if project_path is available
            if project_path and path.startswith(project_path):
                project_name = project_path.rstrip("/").split("/")[-1]
                patterns.append((f"Read({project_path}/*)", f"📂 Any in {project_name}/"))

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

    def _format_chain_approved_message(
        self,
        commands: list[str],
        project_id: str,
    ) -> str:
        """Format chain approved message with list of commands."""
        cmd_lines = []
        for cmd in commands:
            cmd_lines.append(f"  • <code>{truncate_command(cmd)}</code>")

        return f"<i>{project_id}</i>\n✅ <b>Chain approved</b>\n" + "\n".join(cmd_lines)

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

    async def poll_loop(self, timeout: float = 30.0) -> None:
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

    def stop(self) -> None:
        """Signal the poll loop to stop."""
        self._running = False
